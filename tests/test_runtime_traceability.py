"""Contract visualization: API/page/trigger interfaces and generated test rows.

The website renders the traceability tables, so every published contract and every
generated suite has to appear there with its requirement owners, file path and
current status. These tests drive the real passes with their model work replaced
and assert the rows the platform reads.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.project import runtime_events
from infrastructure.stages.passes.stage_11_design_frontend_triggers import design_frontend_triggers
from infrastructure.stages.passes.stage_09_design_frontend_ui import design_frontend_ui
from infrastructure.stages.passes.stage_12_implement_frontend_triggers import implement_frontend_triggers
from infrastructure.stages.passes.stage_10_implement_frontend_ui import implement_frontend_ui
from infrastructure.utils.files import save_json


REQUIREMENTS = {"id": "ROOT", "name": "Root", "children": [
    {"id": "REQ-1", "name": "Home", "description": "Show a page.",
        "scenarios": [{"id": "SCE-1", "name": "open", "steps": [
            {"id": "STEP-1", "when": "the user opens it", "then": "a list is visible"}]}]}]}

DESIGN = {
    "pages": {"UI-home": {"name": "home", "route": "/", "root": "UI-home", "images": []}},
    "elements": {"UI-home": {"type": "page", "parent": None, "mode": [], "data": [], "prop": {}}},
    "requirements": {"ROOT": [], "REQ-1": ["UI-home"]},
    "steps": {"STEP-1": ["UI-home"]},
}

BACKEND = {
    "apis": {"API-list": {
        "description": "List items",
        "signature": {"name": "listItems", "method": "GET", "path": "/api/items"},
        "request": {}, "response": {}, "precondition": [], "postcondition": [],
        "read": [], "write": []}},
    "requirements": {"ROOT": [], "REQ-1": ["API-list"]},
}

INTERACTIONS = {
    "triggers": {"TR-open": {"source": "UI-home", "event": "click", "guard": None,
        "read": [], "write": [], "action": [{"kind": "api", "api": "API-list", "description": "load"}]}},
    "requirements": {"ROOT": [], "REQ-1": ["TR-open"]},
    "steps": {"STEP-1": ["TR-open"]},
}


def write_arc(arc: Path) -> None:
    """Create the minimum artifacts each frontend pass reads."""
    save_json(arc / "requirements.json", REQUIREMENTS)
    save_json(arc / "visual_analysis.json", {})
    save_json(arc / "db_schema.json", {"entities": {}, "requirements": {}})
    save_json(arc / "backend_apis.json", BACKEND)
    save_json(arc / "ui_design.json", DESIGN)
    save_json(arc / "frontend_triggers.json", INTERACTIONS)


def table(arc: Path, name: str) -> dict:
    path = arc / "traceability" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


class TraceabilityTestCase(unittest.TestCase):
    def setUp(self):
        runtime_events._RUNTIME = None
        runtime_events._ENABLED = False
        runtime_events._WARNED = False
        self.addCleanup(setattr, runtime_events, "_RUNTIME", None)
        self.addCleanup(setattr, runtime_events, "_ENABLED", False)
        self.addCleanup(setattr, runtime_events, "_WARNED", False)
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / "application"
        self.arc = self.app / ".arc"
        self.arc.mkdir(parents=True)
        self.input = self.root / "input"
        self.input.mkdir()
        write_arc(self.arc)
        self.assertTrue(runtime_events.initialize(self.app))


class AdapterRows(TraceabilityTestCase):
    def test_interface_rows_keep_owners_content_and_links(self):
        runtime_events.interface("API-a", req_ids=["REQ-1", "REQ-2"], kind="api",
            content="GET /api/a — first", callers=["TR-1"])
        row = table(self.arc, "interfaces")["API-a"]
        self.assertEqual(row["req_ids"], ["REQ-1", "REQ-2"])
        self.assertEqual(row["type"], "api")
        self.assertEqual(row["content"], "GET /api/a — first")
        self.assertEqual(row["callers"], ["TR-1"])
        self.assertFalse(row["implemented"])

        runtime_events.link("API-a", callers=["TR-2"], callees=["DB-1"])
        row = table(self.arc, "interfaces")["API-a"]
        self.assertEqual(row["callers"], ["TR-1", "TR-2"])
        self.assertEqual(row["callees"], ["DB-1"])
        self.assertEqual(row["content"], "GET /api/a — first")

        runtime_events.interface_implemented("API-a", "backend/src/features/a.ts")
        row = table(self.arc, "interfaces")["API-a"]
        self.assertTrue(row["implemented"])
        self.assertEqual(row["file_path"], "backend/src/features/a.ts")

    def test_unknown_interface_updates_are_quiet_noops(self):
        runtime_events.interface_implemented("API-missing", "backend/src/x.ts")
        runtime_events.link("API-missing", callers=["TR-1"])
        self.assertEqual(table(self.arc, "interfaces"), {})

    def test_test_rows_carry_owner_kind_path_and_status(self):
        runtime_events.test_case("api:API-a", requirement_id="REQ-1", kind="api",
            file_path="backend/tests/REQ-1/API-a.test.ts", passed=False, interface_ids=["API-a"])
        row = table(self.arc, "tests")["api:API-a"]
        self.assertEqual((row["req_id"], row["type"], row["passed"]), ("REQ-1", "integration", False))
        self.assertEqual(row["file_path"], "backend/tests/REQ-1/API-a.test.ts")
        self.assertEqual(row["interface_ids"], ["API-a"])

        runtime_events.test_passed("api:API-a", True)
        self.assertTrue(table(self.arc, "tests")["api:API-a"]["passed"])

        runtime_events.test_passed("api:missing", True)
        self.assertNotIn("api:missing", table(self.arc, "tests"))

    def test_a_test_id_collision_between_requirements_does_not_raise(self):
        runtime_events.test_case("suite:shared", requirement_id="REQ-1", kind="e2e")
        runtime_events.test_case("suite:shared", requirement_id="REQ-2", kind="e2e")
        self.assertEqual(table(self.arc, "tests")["suite:shared"]["req_id"], "REQ-1")

    def test_new_rows_are_noops_without_the_sdk(self):
        runtime_events._RUNTIME = None
        runtime_events._ENABLED = False
        runtime_events.interface("API-a", req_ids=["REQ-1"], kind="api", content="x")
        runtime_events.test_case("api:API-a", requirement_id="REQ-1", kind="api")
        self.assertEqual(table(self.arc, "interfaces"), {})
        self.assertEqual(table(self.arc, "tests"), {})


class PassHooks(TraceabilityTestCase):
    def test_design_and_implementation_publish_page_contract_and_ui_suite(self):
        with patch("infrastructure.stages.passes.stage_09_design_frontend_ui.TextModel"), \
                patch("infrastructure.stages.passes.stage_09_design_frontend_ui.DemoConsole"), \
                patch("infrastructure.stages.passes.stage_09_design_frontend_ui.synthesize_ui",
                    return_value=json.loads(json.dumps(DESIGN))):
            design_frontend_ui(self.input, self.arc)

        page = table(self.arc, "interfaces")["UI-home"]
        self.assertEqual((page["type"], page["req_ids"]), ("ui", ["REQ-1"]))
        self.assertEqual(page["content"], "/ → UI-home")

        report = {"status": "GREEN", "pages": {"UI-home": {"status": "GREEN", "requirements": ["REQ-1"]}}}
        with patch("infrastructure.stages.passes.stage_10_implement_frontend_ui.TextModel"), \
                patch("infrastructure.stages.passes.stage_10_implement_frontend_ui.DemoConsole"), \
                patch("infrastructure.stages.passes.stage_10_implement_frontend_ui.implement_ui",
                    return_value=report):
            implement_frontend_ui(self.input, self.arc)

        self.assertTrue(table(self.arc, "interfaces")["UI-home"]["implemented"])
        suite = table(self.arc, "tests")["ui:UI-home"]
        self.assertEqual((suite["req_id"], suite["type"], suite["passed"]), ("REQ-1", "unit", True))
        self.assertEqual(suite["file_path"], "frontend/tests/ui/UI-home.spec.ts")
        self.assertEqual(suite["interface_ids"], ["UI-home"])

    def test_trigger_design_publishes_contract_and_back_links_called_apis(self):
        runtime_events.interface("API-list", req_ids=["REQ-1"], kind="api",
            content="GET /api/items — List items")
        with patch("infrastructure.stages.passes.stage_11_design_frontend_triggers.TextModel"), \
                patch("infrastructure.stages.passes.stage_11_design_frontend_triggers.DemoConsole"), \
                patch("infrastructure.stages.passes.stage_11_design_frontend_triggers.load_ui_design",
                    return_value=json.loads(json.dumps(DESIGN))), \
                patch("infrastructure.stages.passes.stage_11_design_frontend_triggers.synthesize_triggers",
                    return_value=json.loads(json.dumps(INTERACTIONS))):
            design_frontend_triggers(self.input, self.arc)

        trigger = table(self.arc, "interfaces")["TR-open"]
        self.assertEqual((trigger["type"], trigger["req_ids"]), ("trigger", ["REQ-1"]))
        self.assertEqual(trigger["content"], "UI-home.click → API-list")
        self.assertEqual(trigger["callees"], ["API-list"])
        self.assertEqual(table(self.arc, "interfaces")["API-list"]["callers"], ["TR-open"])

    def test_e2e_acceptance_suites_are_published_with_status(self):
        tree = Mock()
        tree.requirements = {"ROOT": {}, "REQ-1": {}}
        tree.children = {"ROOT": ["REQ-1"], "REQ-1": []}
        tree.leaves = ["REQ-1"]
        context = (tree, {"entities": {}}, {"apis": {}, "requirements": {}},
            json.loads(json.dumps(DESIGN)), {"triggers": {}, "requirements": {}}, {}, {})
        process = {"status": "GREEN", "summary": {}, "requirements": {"REQ-1": {"status": "GREEN", "triggers": []}},
            "verification": {}}
        acceptance = {"status": "GREEN", "requirements": {"REQ-1": {"status": "GREEN"}}}
        with patch("infrastructure.stages.passes.stage_12_implement_frontend_triggers.load_e2e_context",
                    return_value=context), \
                patch("infrastructure.stages.passes.stage_12_implement_frontend_triggers.TextModel"), \
                patch("infrastructure.stages.passes.stage_12_implement_frontend_triggers.DemoConsole"), \
                patch("infrastructure.stages.passes.stage_12_implement_frontend_triggers.run_trigger_tdd",
                    return_value=process), \
                patch("infrastructure.stages.passes.stage_12_implement_frontend_triggers.run_independent_acceptance",
                    return_value=acceptance):
            implement_frontend_triggers(self.input, self.arc)

        tests = table(self.arc, "tests")
        self.assertEqual(tests["e2e:REQ-1"]["type"], "e2e")
        self.assertEqual(tests["e2e:REQ-1"]["file_path"], "frontend/tests/e2e/REQ-1.spec.ts")
        self.assertTrue(tests["e2e:REQ-1"]["passed"])
        self.assertEqual(tests["acceptance:REQ-1"]["type"], "e2e")
        self.assertTrue(tests["acceptance:REQ-1"]["file_path"].startswith("frontend/tests/e2e/acceptance/"))
        self.assertTrue(tests["acceptance:REQ-1"]["passed"])
        self.assertEqual(table(self.arc, "node_states")["REQ-1"]["state"], "PASSED")


if __name__ == "__main__":
    unittest.main()
