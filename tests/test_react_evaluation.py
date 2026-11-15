"""A fresh generated application must also pass the fixed external suite."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.evaluate_react import evaluate


class ReactEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / "requirements"
        self.input.mkdir()
        self.output = self.root / "application"
        self.tests = self.root / "external"
        self.tests.mkdir()
        (self.tests / "case.spec.ts").write_text("// frozen external case", encoding="utf-8")
        self.cli = self.root / "cli.js"
        self.cli.touch()

    def test_existing_application_is_rejected_before_generation(self):
        self.output.mkdir()
        with patch("scripts.evaluate_react.compile_application") as generate:
            with self.assertRaisesRegex(ValueError, "new output"):
                evaluate(self.input, self.output, self.tests, self.cli)
        generate.assert_not_called()

    def test_internal_pass_and_external_failure_leave_a_failed_report(self):
        with patch("scripts.evaluate_react.compile_application", return_value={
                "status": "ACCEPTANCE_PASSED"}) as generate, patch(
                "scripts.evaluate_react.startup_check", return_value={"passed": False}) as check:
            report = evaluate(self.input, self.output, self.tests, self.cli)
        self.assertFalse(report["passed"])
        self.assertNotIn("external_tests", generate.call_args.kwargs)
        self.assertEqual(generate.call_args.args, (self.input.resolve(), self.output.resolve()))
        suite = check.call_args.kwargs["acceptance"]
        self.assertEqual(suite.test_timeout, 10000)
        self.assertEqual(suite.max_failures, 0)
        saved = json.loads((self.root / "application.evaluation.json").read_text(encoding="utf-8"))
        self.assertFalse(saved["passed"])
        self.assertTrue(saved["external_source_hashes"])
