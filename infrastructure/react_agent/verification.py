"""Execute a separately prepared Playwright suite and retain requirement-level evidence."""

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess

from infrastructure.utils.files import save_json
from infrastructure.utils.processes import capture_process


def summarize(report: dict, returncode: int) -> dict:
    """Keep assertions, suite errors, skipped cases and infrastructure failures distinguishable."""
    cases = []

    def visit(suite):
        for spec in suite.get("specs", []):
            tests = spec.get("tests", [])
            executed = bool(tests) and all(test.get("expectedStatus", "passed") == "passed" and
                bool(test.get("results")) and all(result.get("status") == "passed" for result in test["results"])
                for test in tests)
            states = [result.get("status") for test in tests for result in test.get("results", [])]
            status = "PASSED" if executed else "FAILED"
            if not states or all(state == "skipped" for state in states):
                status = "UNVERIFIED"
            cases.append({"title": spec.get("title"), "file": spec.get("file"), "status": status,
                "passed": spec.get("ok", False) and executed,
                "errors": [result.get("error", {}) for test in spec.get("tests", [])
                           for result in test.get("results", []) if result.get("error")]})
        for child in suite.get("suites", []):
            visit(child)

    for suite in report.get("suites", []):
        visit(suite)
    stats = report.get("stats", {})
    errors, runner_notes = [], []
    for error in report.get("errors", []):
        message = re.sub(r"\x1b\[[0-9;]*m", "", error.get("message", ""))
        if stats.get("unexpected", 0) and re.fullmatch(r"Testing stopped early after \d+ maximum allowed failures\.", message):
            runner_notes.append(error)
        else:
            errors.append(error)
    passed = returncode == 0 and bool(cases) and all(case["passed"] for case in cases) and bool(stats.get("expected")) and not any(
        stats.get(key, 0) for key in ("unexpected", "skipped", "flaky")) and not errors
    error_records = [*errors, *(error for case in cases for error in case["errors"])]
    headlines = [re.sub(r"\x1b\[[0-9;]*m", "", error.get("message", "")).strip().split("\n", 1)[0]
                 for error in error_records]
    infrastructure = any(re.search(
        r"^(?:Error:\s*)?(?:browserType\.launch|Cannot find module|Executable doesn't exist|ERR_NETWORK_ACCESS_DENIED|page\.goto:.*ERR_NETWORK_ACCESS_DENIED)",
        headline) for headline in headlines)
    kind = "ACCEPTANCE_PASSED" if passed else "ASSERTION_FAILURE"
    if errors or not cases:
        kind = "TEST_SUITE_ERROR"
    if infrastructure:
        kind = "CHECK_ENVIRONMENT_ERROR"
    return {"passed": passed, "kind": kind, "stats": stats, "cases": cases, "errors": errors,
            "runner_notes": runner_notes}


class BrowserSuite:
    def __init__(self, directory: Path, cli: Path, *, channel: str | None = None, max_failures=1):
        self.directory = directory.resolve()
        self.cli = cli.resolve()
        if not self.directory.is_dir() or not self.cli.is_file():
            raise ValueError("Acceptance directory and Playwright CLI must exist")
        self.channel = channel
        self.max_failures = max_failures
        self.hashes = self.snapshot()
        manifest = self.directory / "acceptance-manifest.json"
        self.manifest = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else None
        if self.manifest:
            for name, digest in self.manifest.get("files", {}).items():
                if self.hashes.get(name) != digest:
                    raise ValueError("Acceptance files differ from their compilation manifest")

    def snapshot(self):
        return {path.relative_to(self.directory).as_posix(): sha256(path.read_bytes()).hexdigest()
                for path in self.directory.rglob("*") if path.is_file() and
                not any(part in {"node_modules", ".git"} for part in path.relative_to(self.directory).parts)}

    def for_application(self, root: Path):
        """Bind the application root without sharing mutable run state across checks."""
        return lambda url, artifacts, timeout: self(url, artifacts, timeout, application_root=root.resolve())

    def collect(self, artifacts: Path, timeout: float = 30) -> dict:
        """Check executable case inventory against the compiler's evidence manifest."""
        return self("http://127.0.0.1:9", artifacts, timeout, collect_only=True)

    def __call__(self, url: str, artifacts: Path, timeout: float, *, collect_only=False, application_root=None) -> dict:
        artifacts = artifacts.resolve()
        if self.snapshot() != self.hashes:
            return {"passed": False, "kind": "TEST_SUITE_CHANGED", "error": "Frozen acceptance files changed"}
        artifacts.mkdir(parents=True, exist_ok=True)
        use = {"baseURL": url, "screenshot": "only-on-failure", "trace": "retain-on-failure"}
        if self.channel:
            use["channel"] = self.channel
        config = {"testDir": str(self.directory), "testMatch": "*.spec.ts", "workers": 1,
                  "retries": 0, "fullyParallel": False, "timeout": 30000,
                  "maxFailures": self.max_failures,
                  "outputDir": str(artifacts / "artifacts"), "use": use}
        path = artifacts / "playwright.config.cjs"
        path.write_text("module.exports=" + json.dumps(config), encoding="utf-8")
        modules = str(self.cli.parents[2])
        node_path = os.pathsep.join(filter(None, (modules, os.environ.get("NODE_PATH"))))
        environment = {"NODE_PATH": node_path, "OPENAI_API_KEY": "", "VISUAL_API_KEY": "", "DEEPSEEK_API_KEY": "",
                       "ARC_TEST_APPLICATION_ROOT": ""}
        if application_root:
            environment["ARC_TEST_APPLICATION_ROOT"] = str(application_root)
        try:
            command = ["node", str(self.cli), "test", "--config", str(path), "--reporter=json"]
            if collect_only:
                command.append("--list")
            process = capture_process(command,
                                      cwd=artifacts, timeout=timeout, env=environment)
        except subprocess.TimeoutExpired:
            return {"passed": False, "kind": "CHECK_TIMEOUT", "error": "Acceptance execution timed out"}
        (artifacts / "playwright.raw.json").write_text(process["stdout"], encoding="utf-8")
        (artifacts / "stderr.log").write_text(process["stderr"], encoding="utf-8")
        try:
            result = summarize(json.loads(process["stdout"]), process["returncode"])
        except (ValueError, TypeError):
            return {"passed": False, "kind": "CHECK_ENVIRONMENT_ERROR", "error": process["output"][-6000:]}
        if collect_only and process["returncode"] == 0 and result["cases"] and not result["errors"]:
            result.update(passed=True, kind="COLLECTION_PASSED")
        requirements = {}
        observed = set()
        for case in result["cases"]:
            requirement_ids = [Path(case["file"]).name.removesuffix(".spec.ts")]
            if self.manifest:
                observed_file = Path(case["file"])
                if not observed_file.is_absolute():
                    observed_file = self.directory / observed_file
                observed.add((observed_file.resolve(), case["title"]))
                matches = [item for item in self.manifest["cases"] if item["title"] == case["title"] and
                           (self.directory / item["file"]).resolve() == observed_file.resolve()]
                requirement_ids = [item["requirement_id"] for item in matches] or ["UNMAPPED"]
            for rid in requirement_ids:
                requirements.setdefault(rid, []).append(case["status"])
        if self.manifest:
            missing = [item for item in self.manifest["cases"] if
                       ((self.directory / item["file"]).resolve(), item["title"]) not in observed]
            if missing or "UNMAPPED" in requirements:
                result.update(passed=False, kind="TEST_SUITE_ERROR", missing_case_claims=missing)
        result["requirements"] = {rid: {"status": "FAILED" if "FAILED" in states else
            "PASSED" if all(state == "PASSED" for state in states) else "UNVERIFIED", "cases": len(states)}
            for rid, states in requirements.items()}
        if self.snapshot() != self.hashes:
            result.update(passed=False, kind="TEST_SUITE_CHANGED")
        result["source_hashes"] = self.hashes
        save_json(artifacts / "acceptance-results.json", result)
        return result
