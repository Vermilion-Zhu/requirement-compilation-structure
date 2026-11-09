"""Step 12: connect frontend triggers to backend APIs through functional smoke tests."""

from pathlib import Path

from infrastructure.shared.project.entrypoints import selected_path

from infrastructure.stages.frontend.triggers.context import load_e2e_context
from infrastructure.stages.frontend.triggers.e2e_runtime import stop_e2e_servers
from infrastructure.stages.frontend.triggers.implementation import run_trigger_tdd, verify_frontend
from infrastructure.stages.frontend.triggers.acceptance import acceptance_path, run_independent_acceptance
from infrastructure.stages.frontend.triggers.testing import test_path
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.shared.project import runtime_events
from infrastructure.utils.files import save_json


def implement_frontend_triggers(input_dir: Path, arc_dir: Path, pause: bool = False,
        max_turns: int = 20, max_tests: int = 2) -> dict:
    if min(max_turns, max_tests) < 1:
        raise ValueError("--max-turns and --max-tests must be positive")
    tree, schema, backend, ui, interactions, images, contexts = load_e2e_context(arc_dir, input_dir)
    report = {"status": "PREPARING", "requirements": {rid: {"status": "NO_DIRECT_TRIGGERS", "triggers": []}
        for rid in tree.requirements if tree.children[rid]}}
    save_json(arc_dir / "frontend_e2e.json", report)
    try:
        if not ui["pages"]:
            report.update({"status": "NO_UI", "summary": {"requirements": 0, "triggers": 0, "e2e_tests": 0, "ui_tests": 0, "failed": 0}})
            save_json(arc_dir / "frontend_e2e.json", report)
            return report
        model = TextModel()
        result = run_trigger_tdd(arc_dir, tree, schema, backend, ui, interactions, images,
            contexts, model, DemoConsole(pause), report, max_turns, max_tests)
        for requirement_id, entry in result.get("requirements", {}).items():
            passed = entry.get("status") in {"GREEN", "NO_TRIGGERS", "NO_DIRECT_TRIGGERS"}
            runtime_events.test_result(requirement_id, passed)
            runtime_events.test_case(f"e2e:{requirement_id}", requirement_id=requirement_id,
                kind="e2e", file_path=test_path(requirement_id, arc_dir.parent), passed=passed,
                interface_ids=entry.get("triggers", []))
        acceptance = run_independent_acceptance(input_dir, arc_dir, schema, backend, ui, interactions,
            model, DemoConsole(pause), max_turns, process_report=result)
        if any(entry.get("repair_checks") for entry in acceptance["requirements"].values()):
            result = verify_frontend(arc_dir, tree, backend, ui, DemoConsole(pause), result)
        result["verification"]["independent_acceptance"] = {"status": "GREEN" if acceptance["status"] == "GREEN" else "FAILED",
            "report": ".arc/independent_acceptance.json"}
        for requirement_id, entry in acceptance["requirements"].items():
            accepted = entry.get("status") == "GREEN"
            runtime_events.test_result(requirement_id, accepted, entry.get("error"))
            runtime_events.test_case(f"acceptance:{requirement_id}", requirement_id=requirement_id,
                kind="acceptance", file_path=acceptance_path(requirement_id),
                passed=accepted, scenario_id=None)
        if acceptance["status"] != "GREEN":
            result["status"] = "COMPLETED_WITH_FAILURES"
        # Use the final process report so acceptance repairs can recover trigger status.
        for entry in result.get("requirements", {}).values():
            if entry.get("status") == "GREEN":
                for trigger_id in entry.get("triggers", []):
                    runtime_events.interface_implemented(trigger_id,
                        selected_path(arc_dir.parent, "trigger", trigger_id))
        save_json(arc_dir / "frontend_e2e.json", result)
        print(f"Frontend functional smoke {result['status']}: {result['summary']}\nReport: {arc_dir / 'frontend_e2e.json'}", flush=True)
        return result
    except BaseException as error:
        report.update({"status": "FAILED", "error": str(error)})
        for requirement in report["requirements"].values():
            if requirement["status"] not in {"GREEN", "NO_TRIGGERS", "NO_DIRECT_TRIGGERS"}:
                requirement["status"] = "FAILED"
        save_json(arc_dir / "frontend_e2e.json", report)
        raise
    finally:
        # One reused server pair per stage; release it so nothing is left running.
        stop_e2e_servers(arc_dir.parent)
