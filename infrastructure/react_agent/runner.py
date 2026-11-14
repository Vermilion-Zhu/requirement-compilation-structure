"""Run with python -m infrastructure.react_agent.runner INPUT -o APPLICATION."""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from time import monotonic, sleep
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

from infrastructure.react_agent.prompt import INSTRUCTIONS
from infrastructure.react_agent.provenance import fingerprint as framework_fingerprint
from infrastructure.react_agent.requirements import compile_requirements
from infrastructure.react_agent.tools import Workspace
from infrastructure.shared.models.text import TextModel, parse_json_object, reasoning_arguments
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.utils.files import save_json
from infrastructure.utils.processes import capture_process, npm_command, start_process, stop_process


class ConversationModel(TextModel):
    """Use the existing endpoint compatibility with an append-only conversation."""

    def generate(self, messages: list[dict], timeout: float, *, instructions=INSTRUCTIONS) -> tuple[dict, dict]:
        # Keep provider retries inside the run deadline. No stage-level retry loop.
        self.client = self.client.with_options(timeout=min(timeout, 180), max_retries=0)
        response = self._request_adapting(lambda: {
            "model": self.name,
            "messages": [{"role": "system", "content": instructions + "\n" + self.instruction_suffix()},
                         *messages],
            **reasoning_arguments(self.name, self.reasoning),
        })
        usage = response.usage.model_dump() if response.usage else {}
        if not response.choices or response.choices[0].finish_reason == "length":
            raise ValueError("Missing or truncated response; return a smaller complete action batch")
        return parse_json_object(response.choices[0].message.content), usage


def startup_check(output: Path, timeout: float, *, acceptance=None) -> dict:
    """Check the actual build and a temporary server, cleaning up its entire tree."""
    started = monotonic()
    bind = getattr(acceptance, "for_application", None)
    if callable(bind):
        acceptance = bind(output)
    build = capture_process([*npm_command(), "run", "build"], cwd=output, timeout=min(timeout, 120),
                            env={"OPENAI_API_KEY": "", "VISUAL_API_KEY": "", "DEEPSEEK_API_KEY": ""})
    if build["returncode"]:
        return {"passed": False, "build": build["output"]}
    remaining = timeout - (monotonic() - started)
    if remaining <= 0:
        return {"passed": False, "error": "Time budget exhausted after build"}
    artifacts = output / ".arc" / "verification" / uuid4().hex[:12]
    artifacts.mkdir(parents=True)
    log = artifacts / "server.log"
    opener = build_opener(ProxyHandler({}))
    with log.open("w+", encoding="utf-8") as stream:
        process = start_process(["node", "backend/dist/server.js"], cwd=output,
                                env={"PORT": "0", "HOST": "127.0.0.1", "DATABASE_URL": str(artifacts / "test.db"),
                                     "OPENAI_API_KEY": "", "VISUAL_API_KEY": "", "DEEPSEEK_API_KEY": ""},
                                stdout=stream, stderr=stream)
        try:
            deadline = monotonic() + min(remaining, 15)
            while monotonic() < deadline and process.poll() is None:
                stream.flush()
                content = log.read_text(encoding="utf-8", errors="replace")
                match = re.search(r"Application listening at http://127\.0\.0\.1:(\d+)", content)
                if match:
                    url = f"http://127.0.0.1:{match[1]}"
                    with opener.open(url + "/api/health", timeout=min(2, max(.1, deadline-monotonic()))) as response:
                        healthy = response.status == 200 and json.load(response).get("status") == "ok"
                    with opener.open(url + "/", timeout=min(2, max(.1, deadline-monotonic()))) as response:
                        page = response.status == 200 and b"<html" in response.read().lower()
                    result = {"passed": healthy and page, "build": True, "health": healthy, "page": page}
                    if result["passed"] and acceptance:
                        result["acceptance"] = acceptance(url, artifacts, max(.1, timeout-(monotonic()-started)))
                        result["passed"] = result["acceptance"]["passed"]
                    return result
                sleep(.1)
            return {"passed": False, "error": log.read_text(encoding="utf-8", errors="replace")[-6000:]}
        finally:
            stop_process(process)


def run(requirements: Path, output: Path, *, model=None, max_steps=40, time_budget=900,
        install=True, checker=None, acceptance=None, resume=False) -> dict:
    """Build in one conversation. Every failure remains an observation or explicit status."""
    if max_steps < 1 or time_budget <= 0:
        raise ValueError("max_steps and time_budget must be positive")
    requirements, output = requirements.resolve(), output.resolve()
    if output == requirements or output.is_relative_to(requirements) or requirements.is_relative_to(output):
        raise ValueError("Input and output directories must be separate")
    raw, contracts = compile_requirements(requirements)
    manifest = getattr(acceptance, "manifest", None)
    if isinstance(manifest, dict):
        fingerprint = "requirement_sha256" if manifest.get("requirement_sha256") else "source_sha256"
        if manifest.get(fingerprint) and manifest[fingerprint] != contracts[fingerprint]:
            raise ValueError("Acceptance suite was compiled for different requirements")
    session_path = output / ".arc/react-session.json"
    session = None
    if resume:
        session = json.loads(session_path.read_text(encoding="utf-8"))
        fingerprint = "requirement_sha256" if session.get("requirement_sha256") else "source_sha256"
        if session[fingerprint] != contracts[fingerprint]:
            raise ValueError("Requirement source changed; start a new conversation for the new input")
    started = monotonic()
    deadline = started + time_budget
    initialize_project(output)
    arc = output / ".arc"
    arc.mkdir(exist_ok=True)
    save_json(arc / "requirements.json", raw)
    save_json(arc / "requirement-contracts.json", contracts)
    workspace = Workspace(output, requirements)
    playwright_module = None
    if acceptance is not None and getattr(acceptance, "cli", None):
        driver = acceptance.cli.parents[2] / "playwright/index.mjs"
        if driver.is_file():
            playwright_module = driver.as_uri()
    report = {"status": "RUNNING", "steps": 0, "model_seconds": 0., "tool_seconds": 0.,
              "usage": {}, "image_calls": 0, "behavior_verified": False}
    version = framework_fingerprint(INSTRUCTIONS)
    save_json(arc / "framework-manifest.json", version)
    (arc / "react-instructions.txt").write_text(INSTRUCTIONS, encoding="utf-8")
    report["framework"] = {key: value for key, value in version.items() if key != "files"}
    report["input"] = {key: contracts[key] for key in ("source_sha256", "requirement_sha256")}
    report["acceptance_source_hashes"] = getattr(acceptance, "hashes", None)
    report["requirements"] = {rid: {"status": "UNVERIFIED"} for rid in contracts["implementation_ids"]}
    messages = [{"role": "user", "content": json.dumps({
        "requirement_contracts": contracts, "application_root": str(output),
        "input_root": "input/", "platform": sys.platform,
        "budget": {"max_steps": max_steps, "seconds": time_budget},
        "frozen_acceptance": {"available": acceptance is not None, "run_via": "verify"},
        "runtime_tools": {"node": shutil.which("node"), "npm": shutil.which("npm"),
            "playwright_module": playwright_module,
            "browser_executable": next((str(path) for path in (
                Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
                Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
                Path(shutil.which("google-chrome") or "/usr/bin/chromium")) if path.is_file()), None)},
        "files": [] if resume else sorted(p.relative_to(output).as_posix() for p in output.rglob("*")
                        if p.is_file() and not any(part in {"node_modules", ".arc", ".git", "dist"}
                                                 for part in p.relative_to(output).parts)),
    }, ensure_ascii=False)}]
    if session is not None:
        current_context = json.loads(messages[0]["content"])
        messages = [*session["messages"], {"role": "user", "content": json.dumps({
            "resume_context": current_context,
            "instruction": "Continue from the saved observations. Inspect any partially applied action. "
                "Use verify for the supplied independent acceptance and repair actual application failures.",
        }, ensure_ascii=False)}]
        previous = session["report"]
        report["previous_runs"] = [*previous.get("previous_runs", []),
            {key: previous.get(key) for key in ("status", "steps", "elapsed_seconds", "usage", "framework")}]
    trajectory = arc / "react-trajectory.jsonl"
    if not resume:
        trajectory.write_text("", encoding="utf-8")

    def save_session():
        save_json(session_path, {"source_sha256": contracts["source_sha256"],
            "requirement_sha256": contracts["requirement_sha256"], "messages": messages, "report": report})

    def record(event):
        with trajectory.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    try:
        if install:
            before = monotonic()
            setup = workspace.execute({"tool": "run", "argv": ["npm", "install", "--include=dev", "--no-audit", "--no-fund"],
                                       "timeout": 120}, timeout=deadline-monotonic())
            report["setup_seconds"] = monotonic() - before
            record({"setup": setup})
            messages.append({"role": "user", "content": json.dumps({"dependency_install": setup})})
        model = model or ConversationModel()
        report["model"] = {key: getattr(model, key, None) for key in ("name", "reasoning")}
        for step in range(1, max_steps + 1):
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            report["steps"] = step
            before = monotonic()
            try:
                reply, usage = model.generate(messages, remaining)
            except ValueError as error:
                messages.append({"role": "user", "content": json.dumps({"format_error": str(error)})})
                record({"step": step, "format_error": str(error)})
                continue
            finally:
                report["model_seconds"] += monotonic() - before
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                report["usage"][key] = report["usage"].get(key, 0) + usage.get(key, 0)
            for parent, field in (("prompt_tokens_details", "cached_tokens"),
                                  ("completion_tokens_details", "reasoning_tokens")):
                value = (usage.get(parent) or {}).get(field)
                if isinstance(value, int):
                    report["usage"][field] = report["usage"].get(field, 0) + value
            messages.append({"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)})
            record({"step": step, "reply": reply, "usage": usage})
            print(f"[REACT] {step}/{max_steps} | {monotonic()-started:.1f}s | {reply.get('progress', '')}", flush=True)
            actions = reply.get("actions")
            if not isinstance(actions, list) or not actions or len(actions) > 20:
                actions = [{"tool": "invalid"}]
            observations = []
            for action in actions:
                remaining = deadline-monotonic()
                if remaining <= 0:
                    break
                before = monotonic()
                try:
                    if not isinstance(action, dict):
                        raise ValueError("Each action must be an object")
                    if action.get("tool") in {"verify", "finish"}:
                        if len(actions) != 1:
                            raise ValueError("Verification must be the only action")
                        result = checker(output, remaining) if checker else startup_check(output, remaining, acceptance=acceptance)
                        report["checks"] = result
                        evidence = result.get("acceptance", {})
                        if evidence:
                            for rid in report["requirements"]:
                                report["requirements"][rid] = evidence.get("requirements", {}).get(rid, {"status": "UNVERIFIED"})
                        if evidence.get("kind") in {"CHECK_ENVIRONMENT_ERROR", "TEST_SUITE_ERROR", "TEST_SUITE_CHANGED"}:
                            report.update(status=evidence["kind"])
                        if result.get("passed"):
                            verified = bool(evidence) and all(item["status"] == "PASSED" for item in report["requirements"].values())
                            report.update(status="ACCEPTANCE_PASSED" if evidence else "BUILD_AND_STARTUP_PASSED",
                                          behavior_verified=verified, summary=action.get("summary", ""))
                    elif action.get("tool") == "image":
                        from infrastructure.shared.models.vision import VisualModel
                        visual = VisualModel()
                        visual.client = visual.client.with_options(timeout=min(remaining, 120), max_retries=0)
                        report["image_calls"] += 1
                        result = visual.analyze(workspace.path(action["path"]), max_attempts=1)
                    else:
                        result = workspace.execute(action, timeout=remaining)
                except (ValueError, OSError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
                    result = {"error": str(error)}
                report["tool_seconds"] += monotonic()-before
                observations.append({"tool": action.get("tool") if isinstance(action, dict) else None, "result": result})
                if report["status"] != "RUNNING":
                    break
            record({"step": step, "observations": observations})
            messages.append({"role": "user", "content": json.dumps({"observations": observations,
                "remaining_steps": max_steps-step, "remaining_seconds": round(max(0, deadline-monotonic()))},
                ensure_ascii=False)})
            save_json(arc / "react-report.json", report)
            save_session()
            if report["status"] != "RUNNING":
                break
        if report["status"] == "RUNNING":
            report["status"] = "TIME_LIMIT" if monotonic() >= deadline else "STEP_LIMIT"
    except BaseException as error:
        report.update(status="INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "FAILED", error=str(error))
        raise
    finally:
        report["elapsed_seconds"] = monotonic()-started
        report["total_elapsed_seconds"] = report["elapsed_seconds"] + sum(
            item.get("elapsed_seconds", 0) or 0 for item in report.get("previous_runs", []))
        save_json(arc / "react-report.json", report)
        save_session()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirements", type=Path)
    parser.add_argument("-o", "--output-dir", required=True, type=Path)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--time-budget", type=float, default=900)
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--acceptance-dir", type=Path)
    parser.add_argument("--playwright-cli", type=Path)
    parser.add_argument("--browser-channel")
    args = parser.parse_args()
    acceptance = None
    if args.acceptance_dir:
        from infrastructure.react_agent.verification import BrowserSuite
        if not args.playwright_cli:
            parser.error("--acceptance-dir requires --playwright-cli")
        if args.acceptance_dir.resolve().is_relative_to(args.output_dir.resolve()):
            parser.error("Acceptance sources must be outside the application")
        acceptance = BrowserSuite(args.acceptance_dir, args.playwright_cli, channel=args.browser_channel)
    report = run(args.requirements, args.output_dir, max_steps=args.max_steps,
                 time_budget=args.time_budget, install=not args.skip_install, acceptance=acceptance, resume=args.resume)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] in {"BUILD_AND_STARTUP_PASSED", "ACCEPTANCE_PASSED"} else 1)


if __name__ == "__main__":
    main()
