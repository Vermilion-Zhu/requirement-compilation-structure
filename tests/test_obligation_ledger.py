"""The obligation ledger joins the scattered read/write declarations and evidence.

Each test adds one artifact on top of the previous one, so the lifecycle is checked
where it advances: Inferred -> Allocated -> Verified -> Implemented.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.shared import obligations
from infrastructure.utils.files import save_json


TREE = {"id": "ROOT", "children": [
    {"id": "REQ-1", "name": "List", "scenarios": [{"id": "SCE-1", "steps": [
        {"id": "STEP-1.1", "when": "open", "then": "list is visible"}]}]},
    {"id": "REQ-2", "name": "Save", "scenarios": [{"id": "SCE-2", "steps": [
        {"id": "STEP-2.1", "when": "save", "then": "data is stored"}]}]},
]}

OBLIGATIONS = {
    "requirements": {
        "REQ-1": {"read": ["Book.id", "Book.title"], "write": []},
        "REQ-2": {"read": [], "write": ["Book.title"]},
    },
    "steps": {
        "STEP-1.1": {"read": ["Book.title"], "write": []},
        "STEP-2.1": {"read": [], "write": ["Book.title"]},
    },
}

APIS = {
    "apis": {
        "API-list": {"description": "List books", "read": ["Book.id", "Book.title"], "write": []},
        "API-save": {"description": "Save book", "read": [], "write": ["Book.title"]},
    },
    "requirements": {"REQ-1": ["API-list"], "REQ-2": ["API-save"]},
}

TRIGGERS = {
    "triggers": {"TR-save": {"source": "UI-save", "event": "click",
        "action": [{"kind": "api", "api": "API-save", "description": "save"}],
        "read": [], "write": []}},
    "requirements": {"REQ-1": [], "REQ-2": ["TR-save"]},
    "steps": {"STEP-1.1": [], "STEP-2.1": ["TR-save"]},
}

BACKEND_GREEN = {
    "status": "GREEN",
    "requirements": {"REQ-1": {"status": "GREEN", "apis": ["API-list"]},
        "REQ-2": {"status": "GREEN", "apis": ["API-save"]}},
    "tests": {"REQ-1": {"API-list": "backend/tests/REQ-1/API-list.test.ts"},
        "REQ-2": {"API-save": "backend/tests/REQ-2/API-save.test.ts"}},
}

E2E_FAILED = {
    "status": "COMPLETED_WITH_FAILURES",
    "requirements": {"REQ-1": {"status": "FAILED"}, "REQ-2": {"status": "FAILED"}},
}

ACCEPTANCE_GREEN = {
    "status": "GREEN",
    "requirements": {
        "REQ-1": {"status": "GREEN", "test_path": "frontend/tests/e2e/acceptance/a.spec.ts"},
        "REQ-2": {"status": "GREEN", "test_path": "frontend/tests/e2e/acceptance/b.spec.ts"},
    },
}


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.arc = Path(self.temporary.name) / ".arc"
        self.arc.mkdir(parents=True)
        save_json(self.arc / "requirements.json", TREE)
        save_json(self.arc / "db_obligations.json", OBLIGATIONS)

    def add(self, name, payload):
        save_json(self.arc / (name + ".json"), payload)

    def record(self, ledger, origin, kind, field):
        return next(item for item in ledger["records"].values()
            if (item["origin"], item["kind"], item["field"]) == (origin, kind, field))


class Lifecycle(LedgerCase):
    def test_declarations_start_inferred_with_stable_ids(self):
        first = obligations.build(self.arc)
        second = obligations.build(self.arc)
        self.assertEqual(sorted(first["records"]), sorted(second["records"]))
        self.assertEqual(first["totals"], {"total": 5, "allocated": 0, "verified": 0, "implemented": 0})
        self.assertFalse(first["resolved"])
        # build() is a projection; refresh() labels the lifecycle state.
        self.assertEqual(obligations.refresh(self.arc)["status"], "BUILDING")
        self.assertEqual(first["coverage"]["REQ-1"]["missing"], ["Book.id", "Book.title"])
        step = self.record(first, "STEP-1.1", obligations.KIND_READ, "Book.title")
        self.assertEqual((step["origin_kind"], step["requirement"]), ("step", "REQ-1"))

    def test_apis_allocate_requirement_and_step_obligations(self):
        self.add("backend_apis", APIS)
        ledger = obligations.build(self.arc)
        # APIs assigned to a requirement also cover its steps (the design gate
        # enforces O(step) as a subset of the requirement's API union).
        self.assertEqual(ledger["totals"]["allocated"], 5)
        self.assertEqual(ledger["totals"]["implemented"], 0)
        read = self.record(ledger, "REQ-1", obligations.KIND_READ, "Book.id")
        self.assertEqual(read["status"], "Allocated")
        self.assertEqual(read["allocated_to"], [{"type": "api", "id": "API-list"}])
        step = self.record(ledger, "STEP-1.1", obligations.KIND_READ, "Book.title")
        self.assertEqual(step["status"], "Allocated")
        self.assertFalse([item for item in step["allocated_to"] if item["type"] == "trigger"])

    def test_triggers_record_the_call_path_for_their_steps(self):
        self.add("backend_apis", APIS)
        self.add("frontend_triggers", TRIGGERS)
        ledger = obligations.build(self.arc)
        self.assertEqual(ledger["totals"]["allocated"], 5)
        routed = self.record(ledger, "STEP-2.1", obligations.KIND_WRITE, "Book.title")
        self.assertIn({"type": "trigger", "id": "TR-save"}, routed["allocated_to"])
        unrouted = self.record(ledger, "STEP-1.1", obligations.KIND_READ, "Book.title")
        self.assertFalse([item for item in unrouted["allocated_to"] if item["type"] == "trigger"])

    def test_backend_acceptance_verifies_and_frontend_gates_implementation(self):
        self.add("backend_apis", APIS)
        self.add("backend_tdd", BACKEND_GREEN)
        self.add("frontend_e2e", E2E_FAILED)
        ledger = obligations.build(self.arc)
        verified = self.record(ledger, "REQ-2", obligations.KIND_WRITE, "Book.title")
        self.assertEqual(verified["status"], "Verified")
        self.assertIn("backend/tests/REQ-2/API-save.test.ts", verified["evidence"])
        self.assertFalse(ledger["resolved"])

        self.add("independent_acceptance", ACCEPTANCE_GREEN)
        resolved = obligations.build(self.arc)
        implemented = self.record(resolved, "REQ-2", obligations.KIND_WRITE, "Book.title")
        self.assertEqual(implemented["status"], "Implemented")
        self.assertIn("frontend/tests/e2e/acceptance/b.spec.ts", implemented["evidence"])
        self.assertEqual(resolved["totals"]["implemented"], 5)
        self.assertEqual(resolved["totals"]["total"], 5)
        self.assertTrue(resolved["resolved"])

    def test_a_backend_only_requirement_is_implemented_once_verified(self):
        self.add("backend_apis", APIS)
        self.add("backend_tdd", BACKEND_GREEN)
        ledger = obligations.build(self.arc)
        record = self.record(ledger, "REQ-1", obligations.KIND_READ, "Book.id")
        self.assertEqual(record["status"], "Implemented")
        self.assertEqual(obligations.refresh(self.arc)["status"], "RESOLVED")

    def test_resolved_is_true_when_nothing_is_declared(self):
        empty = Path(self.temporary.name) / "empty"
        empty.mkdir()
        save_json(empty / "db_obligations.json", {"requirements": {}, "steps": {}})
        ledger = obligations.build(empty)
        self.assertEqual(ledger["totals"]["total"], 0)
        self.assertTrue(ledger["resolved"])


class Publishing(LedgerCase):
    def test_refresh_writes_the_artifact_and_labels_the_state(self):
        self.add("backend_apis", APIS)
        ledger = obligations.refresh(self.arc)
        self.assertEqual(ledger["status"], "PARTIAL")
        published = self.arc / obligations.LEDGER
        self.assertTrue(published.is_file())
        self.assertIn("OBL-", published.read_text(encoding="utf-8"))
        self.assertIn("PARTIAL", published.read_text(encoding="utf-8"))

    def test_corrupt_or_missing_artifacts_degrade_to_an_empty_ledger(self):
        (self.arc / "db_obligations.json").write_text("{not json", encoding="utf-8")
        (self.arc / "backend_apis.json").write_text("[]", encoding="utf-8")
        ledger = obligations.refresh(self.arc)
        self.assertEqual(ledger["totals"]["total"], 0)
        self.assertEqual(ledger["status"], "BUILDING")
        self.assertTrue((self.arc / obligations.LEDGER).is_file())

    def test_refresh_never_raises_when_the_directory_is_unusable(self):
        blocked = Path(self.temporary.name) / "blocked"
        blocked.write_text("not a directory", encoding="utf-8")
        self.assertIsNone(obligations.refresh(blocked))

    def test_summary_reports_counts(self):
        self.add("backend_apis", APIS)
        text = obligations.summary(obligations.build(self.arc))
        self.assertIn("0/5 implemented", text)
        self.assertIn("resolved=False", text)


if __name__ == "__main__":
    unittest.main()
