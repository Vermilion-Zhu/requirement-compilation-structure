"""Offline checks for task-independent test compilation and the public entrypoint."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import main
from infrastructure.react_agent.submission import compile_application
from infrastructure.react_agent.test_plan import PLAN_INSTRUCTIONS
from infrastructure.react_agent.browser_tools import prepare_browser


class ReactSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / "requirements"
        self.input.mkdir()
        (self.input / "requirements.yaml").write_text("id: R\ndescription: Show Hello\n", encoding="utf-8")
        self.output = self.root / "application"
        self.cli = self.root / "node_modules/@playwright/test/cli.js"
        self.cli.parent.mkdir(parents=True)
        self.cli.write_text("", encoding="utf-8")
        self.plan = {"cases": [{"requirement_id": "R", "title": "Greeting", "source": "requirements.yaml#/description",
            "steps": [{"op": "goto", "url": "/"},
                      {"op": "expect", "target": {"text": "Hello"}, "check": "visible"}]}]}
        self.tests = Mock()
        self.tests.name, self.tests.reasoning = "scripted-tests", "none"
        self.tests.generate.return_value = (self.plan, {"total_tokens": 15})
        self.implementation = Mock()
        self.implementation.name, self.implementation.reasoning = "scripted-implementation", "none"
        self.implementation.generate.return_value = ({"actions": [{"tool": "verify"}]}, {"total_tokens": 10})

    def compile(self, **options):
        return compile_application(self.input, self.output, playwright_cli=self.cli,
            test_model=self.tests, implementation_model=self.implementation, install=False, **options)

    def test_source_only_test_generation_precedes_application_and_records_total_time(self):
        evidence = {"passed": True, "kind": "ACCEPTANCE_PASSED", "requirements": {"R": {"status": "PASSED"}}}
        with patch("infrastructure.react_agent.submission.BrowserSuite.collect",
                   return_value={"passed": True, "kind": "COLLECTION_PASSED"}):
            report = self.compile(checker=lambda *_: {"passed": True, "acceptance": evidence})
        request = self.tests.generate.call_args
        self.assertEqual(request.kwargs["instructions"], PLAN_INSTRUCTIONS)
        self.assertNotIn("application_root", json.loads(request.args[0][0]["content"]))
        self.assertEqual(report["status"], "ACCEPTANCE_PASSED")
        self.assertTrue(report["behavior_verified"])
        self.assertGreaterEqual(report["elapsed_seconds"], report["test_generation"]["elapsed_seconds"])
        self.assertTrue((Path(report["evidence"]) / "tests/acceptance-manifest.json").is_file())
        self.assertEqual(json.loads((self.output / ".arc/react-submission.json").read_text()), report)
        implementation = json.loads((self.output / ".arc/react-report.json").read_text())
        self.assertTrue(implementation["acceptance_source_hashes"])

    def test_collection_failure_prevents_application_generation(self):
        with patch("infrastructure.react_agent.submission.BrowserSuite.collect",
                   return_value={"passed": False, "kind": "TEST_SUITE_ERROR"}):
            report = self.compile()
        self.assertEqual(report["status"], "TEST_SUITE_ERROR")
        self.implementation.generate.assert_not_called()
        self.assertFalse((self.output / "package.json").exists())

    def test_invalid_plan_or_transport_failure_is_retained_without_implementation(self):
        for failure in ("invalid plan", "transport"):
            with self.subTest(failure=failure):
                if failure == "invalid plan":
                    self.tests.generate.return_value = ({"cases": []}, {})
                else:
                    self.tests.generate.side_effect = RuntimeError("provider unavailable")
                with self.assertRaises((ValueError, RuntimeError)):
                    self.compile()
                self.implementation.generate.assert_not_called()
                report = json.loads((self.output / ".arc/react-submission.json").read_text())
                self.assertEqual(report["status"], "FAILED")
                self.assertFalse(report["behavior_verified"])

    def test_test_generation_exhausts_shared_deadline_before_implementation(self):
        clock = [0]
        def generate(*args, **kwargs):
            clock[0] = 2
            return self.plan, {}
        self.tests.generate.side_effect = generate
        with patch("infrastructure.react_agent.submission.monotonic", side_effect=lambda: clock[0]):
            report = self.compile(time_budget=1)
        self.assertEqual(report["status"], "TIME_LIMIT")
        self.implementation.generate.assert_not_called()

    def test_invalid_proposal_is_retained_and_receives_one_bounded_source_only_correction(self):
        self.tests.generate.side_effect = [({"cases": []}, {}), (self.plan, {})]
        with patch("infrastructure.react_agent.submission.BrowserSuite.collect",
                   return_value={"passed": False, "kind": "TEST_SUITE_ERROR"}):
            report = self.compile()
        self.assertEqual(self.tests.generate.call_count, 2)
        self.assertEqual(len(report["test_generation"]["attempts"]), 2)
        self.assertIn("validation_error", self.tests.generate.call_args.args[0][-1]["content"])
        self.assertTrue((Path(report["evidence"]) / "test-proposal-1.json").is_file())
        self.assertTrue((Path(report["evidence"]) / "test-proposal-2.json").is_file())
        self.implementation.generate.assert_not_called()

    def test_public_entrypoint_selects_experiment_and_preserves_default_engine(self):
        args = [str(self.input), "-o", str(self.output)]
        self.assertEqual(main.parse_args(args).engine, "staged")
        with patch.dict("os.environ", {"REACT_PLAYWRIGHT_CLI": str(self.cli)}), patch(
                "infrastructure.react_agent.submission.compile_application",
                return_value={"status": "ACCEPTANCE_PASSED"}) as compile_mock:
            with self.assertRaises(SystemExit) as result:
                main.main([*args, "--engine", "react"])
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(compile_mock.call_args.args, (self.input, self.output))

    def test_release_manifest_selects_engine_for_the_platforms_fixed_invocation(self):
        release = self.root / "agent-release.json"
        release.write_text(json.dumps({"engine": "react"}), encoding="utf-8")
        with patch.object(main, "__file__", str(self.root / "main.py")):
            args = main.parse_args([str(self.input), "-o", str(self.output)])
        self.assertEqual(args.engine, "react")

    def test_browser_bootstrap_prepares_a_runner_outside_application_without_credentials(self):
        directory = self.root / "browser-tools"
        cli = directory / "node_modules/@playwright/test/cli.js"
        def install(*args, **kwargs):
            cli.parent.mkdir(parents=True)
            cli.write_text("", encoding="utf-8")
            self.assertEqual(kwargs["env"]["DEEPSEEK_API_KEY"], "")
            self.assertIn("@playwright/test@1.55.0", args[0])
            return {"returncode": 0, "output": "prepared"}
        with patch("infrastructure.react_agent.browser_tools.capture_process", side_effect=install):
            prepared, channel = prepare_browser(directory, 10, channel="chrome")
        self.assertEqual(prepared, cli)
        self.assertEqual(channel, "chrome")
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
