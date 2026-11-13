"""Pre-submission semantic probe for the generated application.

The internal TDD stages test artifacts (API tests, page presence, per-requirement E2E), so
they cannot see application-level contracts: the entry route's content, the exact name of a
landmark, or the role of a primary-navigation entry. This module extracts those contracts
from the requirement tree plus the accepted UI design, starts the built application, and runs
a small real-browser probe against it.

``failures`` block a submission; ``warnings`` are advisory checks (for example controls that
only appear after signing in).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen

from infrastructure.stages.frontend.ui.design import (FOLLOW_NAVIGATION, NAMED_NAVIGATION,
    QUOTED_ROLE, _navigation_name, normalize_design, requirement_text_of)
from infrastructure.stages.requirements.tree import RequirementTree


HOMEPAGE = re.compile(r"\b(homepage|home page|landing page|entry route|entry page)\b", re.I)
DYNAMIC_ROUTE = re.compile(r"[:\{\}\*]")


def load_contract(app: Path) -> dict:
    """Extract the application-level contracts from requirements and the accepted design."""
    app = Path(app)
    arc = app / ".arc"
    raw = json.loads((arc / "requirements.json").read_text(encoding="utf-8-sig"))
    tree = RequirementTree(raw)
    design = normalize_design(json.loads((arc / "ui_design.json").read_text(encoding="utf-8-sig")), tree)
    text = requirement_text_of(tree)

    pages, seen_routes = [], set()
    for pid, page in design["pages"].items():
        route = str(page.get("route") or "")
        if not route.startswith("/") or DYNAMIC_ROUTE.search(route) or route in seen_routes:
            continue
        seen_routes.add(route)
        pages.append({"route": route, "root": str(page.get("root") or ""),
            "name": str(page.get("name") or pid)})

    navigations = []
    for match in NAMED_NAVIGATION.finditer(text):
        name = _navigation_name(match.group(1))
        if name not in navigations:
            navigations.append(name)
    landmarks = [{"role": "navigation", "name": name} for name in navigations]
    if re.search(r"\bbanner\b", text, re.I):
        landmarks.append({"role": "banner", "name": ""})

    quoted, seen_controls = [], set()
    for match in QUOTED_ROLE.finditer(text):
        name, role = match.group(1).strip(), match.group(2)
        if any(marker in name for marker in ("<", ">", "{", "}", "?", "\n")):
            continue
        key = (name, role)
        if key in seen_controls:
            continue
        seen_controls.add(key)
        quoted.append({"name": name, "role": role})

    follow = []
    for match in FOLLOW_NAVIGATION.finditer(text):
        item = match.group(1).strip().rstrip('"')
        follow.append({"item": item, "nav": _navigation_name(match.group(2)), "role": "button"})

    entry_regions = []
    for match in HOMEPAGE.finditer(text):
        window = text[max(0, match.start() - 200):match.end() + 400]
        for item in quoted:
            if item["role"] == "region" and item["name"] in window and item["name"] not in entry_regions:
                entry_regions.append(item["name"])
    collection = [item["name"] for item in quoted if item["role"] == "region"
        and re.search(r"\b(feed|list|results|index|questions|posts|catalog)\b", item["name"], re.I)]
    entry_regions = list(dict.fromkeys(collection + entry_regions))[:3]
    if not entry_regions:
        entry_regions = [item["name"] for item in quoted if item["role"] == "region"][:3]
    return {
        "pages": pages,
        "landmarks": landmarks,
        "quoted": quoted,
        "follow": follow,
        "entry": {"expected": bool(HOMEPAGE.search(text)), "regions": entry_regions},
        "timeout": 15000,
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


def _server_output(process) -> str:
    try:
        output, _ = process.communicate(timeout=3)
    except (subprocess.TimeoutExpired, ValueError):
        output = ""
    return (output or "").strip()[-800:]


def _wait_for_server(base_url: str, process, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("application server exited during startup:\n" + _server_output(process))
        try:
            with urlopen(base_url + "/", timeout=2) as response:
                if response.status < 500:
                    return
        except Exception:
            time.sleep(0.25)
    raise TimeoutError(f"application server did not answer {base_url} within {timeout:.0f}s")


def _start_server(app: Path):
    server_file = app / "backend" / "dist" / "server.js"
    if not server_file.is_file():
        raise RuntimeError("backend/dist/server.js is missing; build the application first (npm run build)")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node is not available on PATH")
    port = _free_port()
    directory = tempfile.mkdtemp(prefix="arc-preflight-")
    environment = {**os.environ, "PORT": str(port), "HOST": "127.0.0.1",
        "DATABASE_URL": str(Path(directory) / "app.db")}
    process = subprocess.Popen([node, "backend/dist/server.js"], cwd=app, env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace")
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_server(base_url, process)
    except Exception:
        _stop_server(process)
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return process, base_url, directory


def _stop_server(process) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def parse_probe_output(stdout: str) -> dict:
    """Read the probe's final JSON line and normalise its report sections."""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            report = json.loads(line)
        except ValueError:
            continue
        if isinstance(report, dict):
            return {"failures": list(report.get("failures") or []),
                "warnings": list(report.get("warnings") or []),
                "skipped": list(report.get("skipped") or [])}
    raise ValueError("preflight probe did not return JSON: " + (stdout or "").strip()[-500:])


def _probe(app: Path, base_url: str, contract: dict, timeout: float = 180) -> dict:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node is not available on PATH")
    probe = Path(__file__).with_name("preflight_probe.mjs")
    if not probe.is_file():
        raise RuntimeError("preflight_probe.mjs is missing")
    handle, contract_path = tempfile.mkstemp(prefix="arc-preflight-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(contract, stream, ensure_ascii=False, indent=2)
        completed = subprocess.run([node, str(probe), base_url, contract_path], cwd=app,
            env={**os.environ, "APP_ROOT": str(app)}, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[-800:]
            raise RuntimeError("preflight probe failed:\n" + detail)
        return parse_probe_output(completed.stdout)
    finally:
        Path(contract_path).unlink(missing_ok=True)


def run(app: Path, base_url: str | None = None, timeout: float = 180) -> dict:
    """Run the contract probe against a built application root."""
    app = Path(app).resolve()
    contract = load_contract(app)
    process = directory = None
    try:
        if base_url is None:
            process, base_url, directory = _start_server(app)
        report = _probe(app, base_url, contract, timeout)
    finally:
        _stop_server(process)
        if directory:
            shutil.rmtree(directory, ignore_errors=True)
    report["contract"] = contract
    report["base_url"] = base_url
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the requirement-driven semantic probe on a built application.")
    parser.add_argument("--app", required=True, help="generated application root (contains .arc, backend, frontend)")
    parser.add_argument("--base-url", help="probe an already running application instead of starting it")
    parser.add_argument("--json", help="write the full report to this path")
    parser.add_argument("--strict", action="store_true", help="also fail on advisory warnings")
    arguments = parser.parse_args(argv)
    report = run(Path(arguments.app), arguments.base_url)
    if arguments.json:
        Path(arguments.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for failure in report["failures"]:
        print("FAIL " + failure)
    for warning in report["warnings"][:10]:
        print("WARN " + warning)
    if len(report["warnings"]) > 10:
        print(f"WARN ... {len(report['warnings']) - 10} more warning(s); see --json")
    for skipped in report["skipped"][:5]:
        print("SKIP " + skipped)
    print(f"preflight: {len(report['failures'])} failure(s), {len(report['warnings'])} warning(s), "
        f"{len(report['skipped'])} skipped")
    return 1 if report["failures"] or (arguments.strict and report["warnings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
