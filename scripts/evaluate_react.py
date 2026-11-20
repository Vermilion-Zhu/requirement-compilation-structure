"""Generate a fresh application, then evaluate it with a fixed external suite."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.react_agent.prompt import INSTRUCTIONS
from infrastructure.react_agent.provenance import fingerprint
from infrastructure.react_agent.runner import startup_check
from infrastructure.react_agent.submission import compile_application
from infrastructure.react_agent.verification import BrowserSuite
from infrastructure.utils.files import save_json


def evaluate(requirements: Path, output: Path, external_tests: Path, playwright_cli: Path, *,
             channel=None, time_budget=None, max_steps=None, evaluation_timeout=300, test_timeout=10000):
    requirements, output = requirements.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Use a new output directory for fresh generation")
    if output.is_relative_to(requirements) or requirements.is_relative_to(output):
        raise ValueError("Keep requirements and generated output separate")
    if evaluation_timeout <= 0:
        raise ValueError("Evaluation timeout must be positive")
    suite = BrowserSuite(external_tests, playwright_cli, channel=channel,
                         max_failures=0, test_timeout=test_timeout)
    started = monotonic()
    report_path = output.parent / (output.name + ".evaluation.json")
    report = {"passed": False, "framework": fingerprint(INSTRUCTIONS),
              "requirements": str(requirements), "output": str(output),
              "external_tests": str(suite.directory), "external_source_hashes": suite.hashes,
              "external_test_timeout_ms": test_timeout}
    try:
        report["generation"] = compile_application(requirements, output, playwright_cli=playwright_cli,
            channel=channel, time_budget=time_budget, max_steps=max_steps)
        application_report = output / ".arc/react-report.json"
        if application_report.is_file():
            report["application"] = json.loads(application_report.read_text(encoding="utf-8"))
        report["application_source_hashes"] = {}
        for directory in ("backend/src", "frontend/src"):
            for path in (output / directory).rglob("*"):
                if path.is_file():
                    report["application_source_hashes"][path.relative_to(output).as_posix()] = sha256(path.read_bytes()).hexdigest()
        report["external"] = startup_check(output, evaluation_timeout, acceptance=suite)
        report["passed"] = (report["generation"]["status"] == "ACCEPTANCE_PASSED"
                            and report["external"]["passed"])
        return report
    except BaseException as error:
        report["error"] = str(error)
        raise
    finally:
        report["elapsed_seconds"] = monotonic() - started
        save_json(report_path, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirements", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    parser.add_argument("--external-tests", required=True, type=Path)
    parser.add_argument("--playwright-cli", required=True, type=Path)
    parser.add_argument("--channel")
    parser.add_argument("--time-budget", type=float, default=None)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--evaluation-timeout", type=float, default=300)
    parser.add_argument("--test-timeout-ms", type=int, default=10000)
    args = parser.parse_args()
    report = evaluate(args.requirements, args.output, args.external_tests, args.playwright_cli,
        channel=args.channel, time_budget=args.time_budget, max_steps=args.max_steps,
        evaluation_timeout=args.evaluation_timeout, test_timeout=args.test_timeout_ms)
    print(json.dumps({"passed": report["passed"], "generation": report["generation"]["status"],
        "external": report["external"].get("acceptance", {}).get("stats"),
        "report": str(args.output.resolve().parent / (args.output.name + ".evaluation.json"))}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
