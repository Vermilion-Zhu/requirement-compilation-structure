"""Experimental public-input entry with automatic independent test compilation."""

import json
from pathlib import Path
from time import monotonic
from uuid import uuid4

from infrastructure.react_agent.browser_tools import prepare_browser
from infrastructure.react_agent.requirements import compile_requirements
from infrastructure.react_agent.runner import ConversationModel, run
from infrastructure.react_agent.test_plan import PLAN_INSTRUCTIONS, compile_plan, validate_plan
from infrastructure.react_agent.verification import BrowserSuite
from infrastructure.utils.files import save_json


def compile_application(requirements: Path, output: Path, *, playwright_cli: Path | None = None,
                        channel=None, time_budget=900, max_steps=40, test_model=None,
                        implementation_model=None, install=True, checker=None) -> dict:
    """Include independent test generation and collection in the same run deadline."""
    requirements, output = requirements.resolve(), output.resolve()
    if time_budget <= 0 or max_steps < 1:
        raise ValueError("time_budget and max_steps must be positive")
    if output == requirements or output.is_relative_to(requirements) or requirements.is_relative_to(output):
        raise ValueError("Input and output directories must be separate")
    if playwright_cli is not None and not playwright_cli.is_file():
        raise ValueError("A prepared Playwright CLI is required for independent acceptance")
    started = monotonic()
    deadline = started + time_budget
    raw, contracts = compile_requirements(requirements)
    evidence = output.parent / (output.name + ".react-evidence") / uuid4().hex
    evidence.mkdir(parents=True)
    report = {"status": "COMPILING_TESTS", "behavior_verified": False,
              "requirement_sha256": contracts["requirement_sha256"], "evidence": str(evidence)}
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / ".arc/react-submission.json"
    try:
        save_json(report_path, report)
        if playwright_cli is None:
            report["status"] = "PREPARING_BROWSER"
            playwright_cli, channel = prepare_browser(evidence / "tools", deadline-monotonic(), channel=channel)
            report["status"] = "COMPILING_TESTS"
        test_model = test_model or ConversationModel()
        before = monotonic()
        test_deadline = min(deadline, before+180)
        messages = [{"role": "user", "content": json.dumps(contracts, ensure_ascii=False)}]
        report["test_generation"] = {"attempts": [],
            "model": {key: getattr(test_model, key, None) for key in ("name", "reasoning")}}
        for attempt in range(1, 3):
            remaining = test_deadline-monotonic()
            if remaining <= 0:
                report["status"] = "TIME_LIMIT"
                return report
            plan, usage = test_model.generate(messages, remaining, instructions=PLAN_INSTRUCTIONS)
            save_json(evidence / f"test-proposal-{attempt}.json", plan)
            record = {"attempt": attempt, "usage": usage}
            report["test_generation"]["attempts"].append(record)
            report["test_generation"]["elapsed_seconds"] = monotonic()-before
            try:
                validate_plan(raw, contracts, plan)
                break
            except ValueError as error:
                record["validation_error"] = str(error)
                if attempt == 2:
                    raise
                messages.extend([{"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)},
                    {"role": "user", "content": json.dumps({"validation_error": str(error),
                        "instruction": "Correct the test-plan format using the original contracts. Return the complete plan."})}])
        manifest = compile_plan(requirements, evidence / "tests", plan)
        (evidence / "test-instructions.txt").write_text(PLAN_INSTRUCTIONS, encoding="utf-8")
        report["test_compiler"] = {key: value for key, value in manifest["compiler"].items() if key != "files"}
        suite = BrowserSuite(evidence / "tests", playwright_cli, channel=channel)
        if monotonic() >= deadline:
            report["status"] = "TIME_LIMIT"
            return report
        collection = suite.collect(evidence / "collection", timeout=min(30, deadline-monotonic()))
        report["collection"] = collection
        if not collection["passed"]:
            report["status"] = collection["kind"]
            return report
        if monotonic() >= deadline:
            report["status"] = "TIME_LIMIT"
            return report
        report["status"] = "IMPLEMENTING"
        save_json(report_path, report)
        application = run(requirements, output, model=implementation_model, acceptance=suite,
                          install=install, checker=checker, max_steps=max_steps,
                          time_budget=deadline-monotonic())
        report.update(status=application["status"], behavior_verified=application["behavior_verified"],
                      application_report=".arc/react-report.json")
        return report
    except BaseException as error:
        report.update(status="INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "FAILED", error=str(error))
        raise
    finally:
        report["elapsed_seconds"] = monotonic()-started
        save_json(report_path, report)
        save_json(evidence / "submission-report.json", report)
