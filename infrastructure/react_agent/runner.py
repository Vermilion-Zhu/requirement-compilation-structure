"""Run with python -m infrastructure.react_agent.runner INPUT -o APPLICATION."""

import argparse
import itertools
import math
from openai import APIConnectionError
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from time import monotonic, sleep
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4
from hashlib import sha256

from infrastructure.react_agent.planning import batch_contract_context
from infrastructure.react_agent.prompt import INSTRUCTIONS
from infrastructure.react_agent.provenance import fingerprint as framework_fingerprint
from infrastructure.react_agent.requirements import compile_requirements
from infrastructure.react_agent.tools import Workspace
from infrastructure.shared.models.text import TextModel, parse_json_object, reasoning_arguments
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.utils.files import save_json
from infrastructure.utils.processes import capture_process, npm_command, start_process, stop_process


def request_with_retries(request, timeout, events):
    started = monotonic()
    for attempt in range(3):
        remaining = timeout - (monotonic() - started)
        try:
            return request(remaining)
        except Exception as error:
            cause = error
            transient = False
            status = None
            while cause is not None:
                status = getattr(cause, "status_code", None)
                transient = isinstance(cause, APIConnectionError) or status in {408, 409, 429} or (isinstance(status, int) and status >= 500)
                if transient or cause.__cause__ is None:
                    break
                cause = cause.__cause__
            if not transient or attempt == 2:
                raise
            delay = float(2 ** attempt)
            retry_after = getattr(getattr(cause, "response", None), "headers", {}).get("retry-after")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    pass
            if delay >= timeout - (monotonic() - started):
                raise
            events.append({"attempt": attempt + 1, "error_type": type(cause).__name__,
                           "status_code": status, "backoff_seconds": delay})
            sleep(delay)


class ConversationModel(TextModel):
    """Use the existing endpoint compatibility with an append-only conversation."""

    def generate(self, messages: list[dict], timeout: float, *, instructions=INSTRUCTIONS) -> tuple[dict, dict]:
        if not hasattr(self, "transport_events"):
            self.transport_events = []
        def request(remaining):
            self.client = self.client.with_options(timeout=min(remaining, 300), max_retries=0)
            return self._request_adapting(lambda: {
                "model": self.name,
                "messages": [{"role": "system", "content": instructions + "\n" + self.instruction_suffix()},
                             *messages],
                **reasoning_arguments(self.name, self.reasoning),
            })
        response = request_with_retries(request, timeout, self.transport_events)
        usage = response.usage.model_dump() if response.usage else {}
        if not response.choices or response.choices[0].finish_reason == "length":
            raise ValueError("Missing or truncated response; return a smaller complete action batch")
        return parse_json_object(response.choices[0].message.content), usage


def _run_acceptance(acceptance, url: str, artifacts: Path, timeout: float, cases=None) -> dict:
    """Call a suite with an optional case selection; plain callables keep the old signature."""
    if cases is None:
        return acceptance(url, artifacts, timeout)
    try:
        return acceptance(url, artifacts, timeout, cases=cases)
    except TypeError as error:
        if "cases" not in str(error):
            raise
        return acceptance(url, artifacts, timeout)


def startup_check(output: Path, timeout: float, *, acceptance=None, cases=None) -> dict:
    """Check the actual build and a temporary server, cleaning up its entire tree."""
    if not math.isfinite(timeout):
        manifest = getattr(acceptance, "manifest", None) or {}
        selected = manifest.get("cases", [])
        if cases is not None:
            chosen = set(cases)
            selected = [case for case in selected if case.get("title") in chosen]
        timeout = 360 + sum(30 + 2 * case.get("step_count", 0) for case in selected)
    started = monotonic()
    bind = getattr(acceptance, "for_application", None)
    if callable(bind):
        acceptance = bind(output)
    build = capture_process([*npm_command(), "run", "build"], cwd=output, timeout=min(timeout, 300),
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
            deadline = monotonic() + min(remaining, 60)
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
                        result["acceptance"] = _run_acceptance(acceptance, url, artifacts,
                            max(.1, timeout-(monotonic()-started)), cases=cases)
                        result["passed"] = result["acceptance"]["passed"]
                    return result
                sleep(.1)
            return {"passed": False, "error": log.read_text(encoding="utf-8", errors="replace")[-6000:]}
        finally:
            stop_process(process)


def run(requirements: Path, output: Path, *, model=None, max_steps=None, time_budget=None,
        install=True, checker=None, acceptance=None, resume=False, plan=None) -> dict:
    """Build in one conversation. Every failure remains an observation or explicit status."""
    if (max_steps is not None and max_steps < 1) or (time_budget is not None and time_budget <= 0):
        raise ValueError("max_steps and time_budget must be positive")
    requirements, output = requirements.resolve(), output.resolve()
    if output == requirements or output.is_relative_to(requirements) or requirements.is_relative_to(output):
        raise ValueError("Input and output directories must be separate")
    raw, contracts = compile_requirements(requirements)
    requirements_count = len(contracts["implementation_ids"])
    scenarios_count = sum(len(c.get("scenarios", [])) for c in contracts["contracts"] if isinstance(c.get("scenarios"), list))
    initial_steps = max(1, 2 * requirements_count + scenarios_count)
    step_limit = max_steps if max_steps is not None else initial_steps
    progress_revision = 0
    progress_passed = 0
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
    deadline = started + time_budget if time_budget is not None else math.inf
    initialize_project(output)
    arc = output / ".arc"
    arc.mkdir(exist_ok=True)
    save_json(arc / "requirements.json", raw)
    save_json(arc / "requirement-contracts.json", contracts)
    workspace = Workspace(output, requirements)
    image_cache = {}
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
    batches = list((plan or {}).get("batches") or []) if plan else []
    if plan and not batches:
        raise ValueError("An implementation plan needs at least one batch")
    batch_index = 0
    batch_state = None
    contract_payload = contracts
    if plan:
        contract_payload = batch_contract_context(contracts, plan, batches[0])
        batch_state = {"source": plan.get("source", "unknown"), "current_index": 0,
            "batches": [{key: batch.get(key) for key in ("id", "requirements", "tests", "goal", "depends_on")}
                | {"status": "IN_PROGRESS" if index == 0 else "PENDING"}
                for index, batch in enumerate(batches)]}
        report["plan"] = batch_state
        save_json(arc / "implementation-plan.json", plan)
    messages = [{"role": "user", "content": json.dumps({
        "requirement_contracts": contract_payload, "application_root": str(output),
        "input_root": "input/", "platform": sys.platform,
        "budget": {"max_steps": max_steps, "initial_steps": initial_steps, "seconds": time_budget},
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
        "implementation_plan": plan,
        "current_batch": batches[batch_index] if plan else None,
        "batch_instructions": ("Implement current_batch first. verify runs only its mapped frozen tests; "
            "a pass advances the controller to the next batch. The final batch pass triggers the full suite. "
            "Keep earlier interfaces working when later batches need them; do not edit frozen tests.") if plan else None,
    }, ensure_ascii=False)}]
    if session is not None:
        current_context = json.loads(messages[0]["content"])
        resume_context = {"resume_context": current_context,
            "instruction": "Continue from the saved observations. Inspect any partially applied action. "
                "Use verify for the supplied independent acceptance and repair actual application failures."}
        if plan:
            resume_context["current_batch"] = batches[batch_index]
            resume_context["requirement_context_updated"] = True
        messages = [*session["messages"], {"role": "user", "content": json.dumps(resume_context, ensure_ascii=False)}]
        previous = session["report"]
        if plan and isinstance(previous.get("plan"), dict):
            saved = previous["plan"]
            saved_batches = saved.get("batches") or []
            if len(saved_batches) == len(batches):
                batch_state = saved
                batch_index = min(int(saved.get("current_index", 0)), len(batches) - 1)
                batch_state["current_index"] = batch_index
                batch_state["batches"][batch_index]["status"] = "IN_PROGRESS"
                report["plan"] = batch_state
        report["previous_runs"] = [*previous.get("previous_runs", []),
            {key: previous.get(key) for key in ("status", "steps", "elapsed_seconds", "usage", "framework")}]
    trajectory = arc / "react-trajectory.jsonl"
    if not resume:
        trajectory.write_text("", encoding="utf-8")

    def set_batch_context(batch):
        """Replace the rolling batch context; old batch clauses do not accumulate."""
        content = json.loads(messages[0]["content"])
        content["requirement_contracts"] = batch_contract_context(contracts, plan, batch)
        content["current_batch"] = batch
        messages[0]["content"] = json.dumps(content, ensure_ascii=False)

    if session is not None and plan:
        set_batch_context(batches[batch_index])

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
                                       "timeout": 600}, timeout=deadline-monotonic())
            report["setup_seconds"] = monotonic() - before
            record({"setup": setup})
            messages.append({"role": "user", "content": json.dumps({"dependency_install": setup})})
        model = model or ConversationModel()
        report["model"] = {key: getattr(model, key, None) for key in ("name", "reasoning")}
        for step in itertools.count(1):
            if step > step_limit:
                passed = sum(item["status"] == "PASSED" for item in report["requirements"].values())
                if max_steps is not None or (workspace.revision <= progress_revision and passed <= progress_passed):
                    break
                progress_revision, progress_passed = workspace.revision, passed
                step_limit += initial_steps
                record({"extended_steps": step_limit, "revision": progress_revision, "passed_requirements": passed})
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            report["steps"] = step
            preflight = resume and step == 1
            before = monotonic()
            try:
                if preflight:
                    reply, usage = {"progress": "Controller checking resumed application", "actions": [{"tool": "verify"}]}, {}
                else:
                    reply, usage = model.generate(messages, remaining)
            except ValueError as error:
                messages.append({"role": "user", "content": json.dumps({"format_error": str(error)})})
                record({"step": step, "format_error": str(error)})
                continue
            finally:
                if not preflight:
                    report["model_seconds"] += monotonic() - before
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                report["usage"][key] = report["usage"].get(key, 0) + usage.get(key, 0)
            for parent, field in (("prompt_tokens_details", "cached_tokens"),
                                  ("completion_tokens_details", "reasoning_tokens")):
                value = (usage.get(parent) or {}).get(field)
                if isinstance(value, int):
                    report["usage"][field] = report["usage"].get(field, 0) + value
            messages.append({"role": "user" if preflight else "assistant", "content": json.dumps(reply, ensure_ascii=False)})
            record({"step": step, "origin": "controller" if preflight else "model", "reply": reply, "usage": usage})
            print(f"[REACT] {step}/{step_limit} | {monotonic()-started:.1f}s | {reply.get('progress', '')}", flush=True)
            actions = reply.get("actions")
            if actions == [] and acceptance is not None:
                actions = [{"tool": "verify"}]
            if not isinstance(actions, list) or not actions or len(actions) > 20:
                actions = [{"tool": "invalid"}]
            observations = []
            batch_transition = None

            def apply_evidence(evidence, complete=False):
                observed = evidence.get("requirements") or {}
                for rid in report["requirements"]:
                    if rid in observed:
                        report["requirements"][rid] = observed[rid]
                    elif complete or not plan:
                        report["requirements"][rid] = {"status": "UNVERIFIED"}

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
                        batch = batches[batch_index] if plan else None
                        subset = batch.get("tests") if batch else None
                        check_acceptance = acceptance if (not plan or subset) else None
                        result = checker(output, remaining) if checker else startup_check(output, remaining,
                            acceptance=check_acceptance, cases=subset if plan else None)
                        report["checks"] = result
                        evidence = result.get("acceptance", {})
                        if evidence:
                            apply_evidence(evidence)
                        if evidence.get("kind") in {"CHECK_ENVIRONMENT_ERROR", "TEST_SUITE_ERROR", "TEST_SUITE_CHANGED"}:
                            report.update(status=evidence["kind"])
                        if result.get("passed") and plan:
                            batch_state["batches"][batch_index]["status"] = "PASSED"
                            report.setdefault("batch_checks", []).append({
                                "batch": batch["id"], "stage": "BATCH", "passed": True,
                                "cases": len(subset or []), "result": result})
                            if batch_index + 1 < len(batches):
                                batch_index += 1
                                batch_state["current_index"] = batch_index
                                batch_state["batches"][batch_index]["status"] = "IN_PROGRESS"
                                set_batch_context(batches[batch_index])
                                batch_transition = {"batch_completed": batch["id"],
                                    "next_batch": batches[batch_index],
                                    "requirement_context_updated": True,
                                    "instruction": "The batch passed. requirement_contracts in the initial context now describes the next batch; implement it; verify will run only its cases."}
                            else:
                                full = checker(output, remaining) if checker else startup_check(output, remaining,
                                    acceptance=acceptance)
                                report["checks"] = full
                                full_evidence = full.get("acceptance", {})
                                if full_evidence:
                                    apply_evidence(full_evidence, complete=True)
                                if full_evidence.get("kind") in {"CHECK_ENVIRONMENT_ERROR", "TEST_SUITE_ERROR", "TEST_SUITE_CHANGED"}:
                                    report.update(status=full_evidence["kind"])
                                if full.get("passed"):
                                    verified = bool(full_evidence) and all(item["status"] == "PASSED"
                                        for item in report["requirements"].values())
                                    report.update(status="ACCEPTANCE_PASSED" if full_evidence else "BUILD_AND_STARTUP_PASSED",
                                        behavior_verified=verified, summary=action.get("summary", ""))
                                else:
                                    result = full
                                    batch_state["batches"][batch_index]["status"] = "FINAL_CHECK_FAILED"
                        elif result.get("passed"):
                            verified = bool(evidence) and all(item["status"] == "PASSED" for item in report["requirements"].values())
                            report.update(status="ACCEPTANCE_PASSED" if evidence else "BUILD_AND_STARTUP_PASSED",
                                          behavior_verified=verified, summary=action.get("summary", ""))
                    elif action.get("tool") == "image":
                        from infrastructure.shared.models.vision import VisualModel
                        image_path = workspace.path(action["path"])
                        image_key = sha256(image_path.read_bytes()).hexdigest()
                        if image_key in image_cache:
                            result = image_cache[image_key]
                        else:
                            visual = VisualModel()
                            def analyze(allowance):
                                visual.client = visual.client.with_options(timeout=min(allowance, 120), max_retries=0)
                                return visual.analyze(image_path, max_attempts=1)
                            report["image_calls"] += 1
                            result = request_with_retries(analyze, remaining, report.setdefault("transport_retries", []))
                            image_cache[image_key] = result
                    else:
                        result = workspace.execute(action, timeout=remaining)
                except (ValueError, OSError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
                    result = {"error": str(error)}
                report["tool_seconds"] += monotonic()-before
                observations.append({"tool": action.get("tool") if isinstance(action, dict) else None, "result": result})
                if report["status"] != "RUNNING":
                    break
            record({"step": step, "observations": observations})
            payload = {"observations": observations,
                "remaining_steps": step_limit-step, "remaining_seconds": round(max(0, deadline-monotonic())) if math.isfinite(deadline) else None}
            if batch_transition:
                payload["batch_transition"] = batch_transition
                report["plan"] = batch_state
            messages.append({"role": "user", "content": json.dumps(payload, ensure_ascii=False)})
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
        events = getattr(model, "transport_events", None)
        if isinstance(events, list):
            report["transport_retries"] = [*report.get("transport_retries", []), *events]
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
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--time-budget", type=float, default=None)
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
