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


def partition_contracts(contracts: dict, scenario_limit=12) -> list[dict]:
    """Bound each test proposal while retaining original ancestors and source pointers."""
    records = {item["id"]: item for item in contracts["contracts"]}
    groups, current, count = [], [], 0
    for rid in contracts["implementation_ids"]:
        weight = max(1, len(records[rid].get("scenarios", [])))
        if current and count+weight > scenario_limit:
            groups.append(current)
            current, count = [], 0
        current.append(rid)
        count += weight
    if current:
        groups.append(current)
    batches = []
    for ids in groups:
        sources = [records[rid]["source"] for rid in ids]
        context = [record for record in contracts["contracts"] if any(
            source == record["source"] or source.startswith(record["source"] + "/") for source in sources)]
        context_ids = {record["id"] for record in context}
        batches.append({**contracts, "implementation_ids": ids, "contracts": context,
            "ui_declarations": [item for item in contracts["ui_declarations"] if item["requirement_id"] in context_ids]})
    return batches


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
        batches = partition_contracts(contracts)
        test_deadline = min(deadline, before+max(180, min(360, time_budget*.45)))
        report["test_generation"] = {"attempts": [], "batches": len(batches),
            "model": {key: getattr(test_model, key, None) for key in ("name", "reasoning")}}
        plan = {"cases": [], "name_resolutions": {}}
        for index, batch in enumerate(batches, 1):
            messages = [{"role": "user", "content": json.dumps(batch, ensure_ascii=False)}]
            for attempt in range(1, 3):
                remaining = test_deadline-monotonic()
                if remaining <= 0:
                    report["status"] = "TIME_LIMIT"
                    return report
                proposal, usage = test_model.generate(messages, min(180, remaining), instructions=PLAN_INSTRUCTIONS)
                prefix = "" if len(batches) == 1 else f"batch-{index}-"
                save_json(evidence / f"test-proposal-{prefix}{attempt}.json", proposal)
                record = {"batch": index, "attempt": attempt, "usage": usage}
                report["test_generation"]["attempts"].append(record)
                report["test_generation"]["elapsed_seconds"] = monotonic()-before
                try:
                    validate_plan(raw, batch, proposal)
                    break
                except ValueError as error:
                    record["validation_error"] = str(error)
                    if attempt == 2:
                        raise
                    messages.extend([{"role": "assistant", "content": json.dumps(proposal, ensure_ascii=False)},
                        {"role": "user", "content": json.dumps({"validation_error": str(error),
                            "instruction": "Correct the test-plan format using the original contracts. Return the complete plan."})}])
            plan["cases"].extend(proposal["cases"])
            for uid, resolution in proposal.get("name_resolutions", {}).items():
                if uid in plan["name_resolutions"] and resolution != plan["name_resolutions"][uid]:
                    raise ValueError("Conflicting accessible-name evidence between test batches")
                plan["name_resolutions"][uid] = resolution
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
