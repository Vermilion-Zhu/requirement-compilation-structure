"""M10: the pre-submission probe extracts application contracts and reports them."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.project import preflight


RAW = {"id": "ROOT", "name": "Root", "children": [{"id": "REQ-1", "name": "Home",
    "description": ("Opening / displays a homepage with \"Question feed\"(role=region). "
        "Follow Questions in Main navigation. \"Log in\"(role=button) opens "
        "\"Log in\"(role=region). \"<registered email>\"(role=button) is an example."),
    "scenarios": [{"id": "S1", "steps": [{"id": "STEP-1",
        "When": "Follow Questions in Main navigation", "Then": "Question feed appears"}]}]}]}

DESIGN = {"pages": {
    "questions": {"name": "Questions", "route": "/questions", "root": "UI-questions", "images": []},
    "question": {"name": "Question", "route": "/questions/:id", "root": "UI-question", "images": []},
    "home": {"name": "Home", "route": "/", "root": "UI-home", "images": []}},
    "elements": {"UI-questions": {"type": "page", "parent": None, "prop": {}},
        "UI-question": {"type": "page", "parent": None, "prop": {}},
        "UI-home": {"type": "page", "parent": None, "prop": {}}},
    "requirements": {"REQ-1": ["UI-home"]}, "steps": {"STEP-1": ["UI-home"]}}


def prepare(directory: Path) -> Path:
    arc = directory / ".arc"
    arc.mkdir(parents=True)
    (arc / "requirements.json").write_text(json.dumps(RAW), encoding="utf-8")
    (arc / "ui_design.json").write_text(json.dumps(DESIGN), encoding="utf-8")
    return directory


class ContractExtraction(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.app = prepare(Path(temporary.name))
        self.contract = preflight.load_contract(self.app)

    def test_static_pages_exclude_dynamic_routes(self):
        routes = {page["route"] for page in self.contract["pages"]}
        self.assertEqual(routes, {"/", "/questions"})
        self.assertTrue(all(page["root"] for page in self.contract["pages"]))

    def test_named_navigation_and_follow_entries(self):
        self.assertIn({"role": "navigation", "name": "Main navigation"}, self.contract["landmarks"])
        self.assertIn({"item": "Questions", "nav": "Main navigation", "role": "button"},
            self.contract["follow"])

    def test_homepage_and_entry_regions(self):
        self.assertTrue(self.contract["entry"]["expected"])
        self.assertIn("Question feed", self.contract["entry"]["regions"])

    def test_quoted_contracts_exclude_placeholder_examples(self):
        quoted = {(item["name"], item["role"]) for item in self.contract["quoted"]}
        self.assertIn(("Question feed", "region"), quoted)
        self.assertIn(("Log in", "button"), quoted)
        self.assertNotIn(("<registered email>", "button"), quoted)


class ProbeOutput(unittest.TestCase):
    def test_the_last_json_line_is_the_report(self):
        report = preflight.parse_probe_output('noise\n{"failures":["x"],"warnings":[],"skipped":[]}\n')
        self.assertEqual(report, {"failures": ["x"], "warnings": [], "skipped": []})

    def test_output_without_json_is_rejected(self):
        with self.assertRaises(ValueError):
            preflight.parse_probe_output("no report")


class RunAndCli(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.app = prepare(Path(temporary.name))

    def test_run_starts_the_server_and_attaches_the_contract(self):
        with patch.object(preflight, "_start_server", return_value=(Mock(), "http://127.0.0.1:9", None)), \
                patch.object(preflight, "_probe", return_value={"failures": [], "warnings": [], "skipped": []}):
            report = preflight.run(self.app)
        self.assertEqual(report["base_url"], "http://127.0.0.1:9")
        self.assertIn("landmarks", report["contract"])

    def test_cli_fails_on_failures_and_passes_without_them(self):
        with patch.object(preflight, "run", return_value={"failures": ["boom"], "warnings": [], "skipped": []}):
            self.assertEqual(preflight.main(["--app", str(self.app)]), 1)
        with patch.object(preflight, "run", return_value={"failures": [], "warnings": ["advisory"], "skipped": []}):
            self.assertEqual(preflight.main(["--app", str(self.app)]), 0)
            self.assertEqual(preflight.main(["--app", str(self.app), "--strict"]), 1)


if __name__ == "__main__":
    unittest.main()
