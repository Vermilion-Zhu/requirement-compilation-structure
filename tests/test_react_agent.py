"""Offline contracts for the lightweight conversation and its real file/process tools."""

import copy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.react_agent.runner import run
from infrastructure.react_agent.requirements import compile_requirements
from infrastructure.react_agent.acceptance import generate_tests
from infrastructure.react_agent.verification import BrowserSuite, summarize
from infrastructure.react_agent.tools import Workspace


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def generate(self, messages, timeout):
        self.requests.append(copy.deepcopy(messages))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


class ReactAgentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / "input"
        self.input.mkdir()
        (self.input / "requirements.yaml").write_text("description: A notes application\n", encoding="utf-8")
        self.output = self.root / "application"

    def run_agent(self, replies, **options):
        model = ScriptedModel(replies)
        report = run(self.input, self.output, model=model, install=False, **options)
        return model, report

    def test_batched_edits_then_finish_preserve_history_and_usage(self):
        model, report = self.run_agent([
            {"actions": [{"tool": "write", "path": "hello.txt", "content": "hello"},
                         {"tool": "read", "path": "hello.txt"}]},
            {"actions": [{"tool": "finish", "summary": "Built notes"}]},
        ], checker=lambda *_: {"passed": True})
        self.assertEqual(report["status"], "BUILD_AND_STARTUP_PASSED")
        self.assertFalse(report["behavior_verified"])
        self.assertEqual(report["usage"]["total_tokens"], 30)
        self.assertEqual((self.output / "hello.txt").read_text(), "hello")
        self.assertEqual(model.requests[0], model.requests[1][:len(model.requests[0])])
        self.assertIn("hello", model.requests[1][-1]["content"])

    def test_failed_finish_returns_observation_and_can_repair(self):
        checker = Mock(side_effect=[{"passed": False, "error": "build failed"}, {"passed": True}])
        model, report = self.run_agent([
            {"actions": [{"tool": "finish"}]},
            {"actions": [{"tool": "write", "path": "fix.txt", "content": "fixed"}]},
            {"actions": [{"tool": "finish"}]},
        ], checker=checker)
        self.assertEqual(checker.call_count, 2)
        self.assertIn("build failed", model.requests[1][-1]["content"])
        self.assertEqual(report["status"], "BUILD_AND_STARTUP_PASSED")

    def test_format_failure_is_bounded_and_recorded(self):
        _, report = self.run_agent([ValueError("invalid JSON")], max_steps=1)
        self.assertEqual(report["status"], "STEP_LIMIT")
        events = (self.output / ".arc/react-trajectory.jsonl").read_text()
        self.assertIn("invalid JSON", events)

    def test_transport_failure_records_failure_and_propagates(self):
        with self.assertRaisesRegex(RuntimeError, "offline"):
            self.run_agent([RuntimeError("offline")])
        report = json.loads((self.output / ".arc/react-report.json").read_text())
        self.assertEqual(report["status"], "FAILED")

    def test_failed_batch_reports_each_result_and_retains_successful_edits(self):
        model, report = self.run_agent([
            {"actions": [{"tool": "write", "path": "first.txt", "content": "saved"},
                         {"tool": "replace", "path": "first.txt", "old": "absent", "new": "x"}]},
            {"actions": [{"tool": "finish"}]},
        ], checker=lambda *_: {"passed": True})
        self.assertIn("Replacement must match exactly once", model.requests[1][-1]["content"])
        self.assertEqual((self.output / "first.txt").read_text(), "saved")

    def test_finish_cannot_be_mixed_with_edits(self):
        checker = Mock()
        _, report = self.run_agent([{"actions": [{"tool": "finish"},
                                                  {"tool": "write", "path": "later.txt", "content": "yes"}]}],
                                   max_steps=1, checker=checker)
        checker.assert_not_called()
        self.assertEqual(report["status"], "STEP_LIMIT")

    def test_input_output_overlap_is_rejected_before_scaffolding(self):
        with self.assertRaisesRegex(ValueError, "separate"):
            run(self.input, self.input / "output", install=False)
        self.assertFalse((self.input / "output").exists())

    def test_invalid_budgets_are_rejected(self):
        with self.assertRaises(ValueError):
            run(self.input, self.output, max_steps=0)

    def test_invalid_action_is_an_observation(self):
        model, report = self.run_agent([{"actions": [None]}, {"actions": [{"tool": "finish"}]}],
                                       checker=lambda *_: {"passed": True})
        self.assertIn("Each action must be an object", model.requests[1][-1]["content"])

    def workspace(self):
        self.output.mkdir()
        return Workspace(self.output, self.input)

    def test_file_paths_and_input_are_checked(self):
        workspace = self.workspace()
        for path in ("../escape", "input/../escape", ".env", ".arc/private", "input/tests/hidden.ts"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                workspace.path(path)
        with self.assertRaisesRegex(ValueError, "read-only"):
            workspace.path("input/requirements.yaml", write=True)
        self.assertEqual(workspace.path("input/requirements.yaml"), self.input / "requirements.yaml")

    def test_replacement_must_be_unique(self):
        workspace = self.workspace()
        (self.output / "a.txt").write_text("x x")
        with self.assertRaises(ValueError):
            workspace.execute({"tool": "replace", "path": "a.txt", "old": "x", "new": "y"}, timeout=5)
        self.assertEqual((self.output / "a.txt").read_text(), "x x")

    def test_real_process_exit_and_timeout(self):
        workspace = self.workspace()
        result = workspace.execute({"tool": "run", "argv": [sys.executable, "-c", "print('hello')"]}, timeout=5)
        self.assertEqual(result["returncode"], 0)
        self.assertIn("hello", result["output"])
        result = workspace.execute({"tool": "run", "argv": [sys.executable, "-c", "import time; time.sleep(10)"],
                                    "timeout": 1}, timeout=2)
        self.assertEqual(result["returncode"], 124)

    def test_npx_uses_node_cli_without_windows_shell(self):
        workspace = self.workspace()
        with patch("infrastructure.react_agent.tools.npm_command", return_value=["node", "npm/bin/npm-cli.js"]), \
                patch("infrastructure.react_agent.tools.capture_process") as capture:
            capture.return_value = {"returncode": 0, "output": "ok", "elapsed_seconds": .1}
            workspace.execute({"tool": "run", "argv": ["npx", "playwright", "--version"]}, timeout=5)
        self.assertEqual(Path(capture.call_args.args[0][1]).name, "npx-cli.js")
        self.assertEqual(capture.call_args.args[0][-2:], ["playwright", "--version"])

    def test_requirement_compilation_preserves_evidence_metadata_and_sources(self):
        source = {"id": "ROOT", "description": "Parent constraint", "environment": {"locale": "en-US"},
                  "data": [{"entity": "label", "name": "Reminders"}], "children": [
                      {"id": "R1", "description": {"text": "Exact name"}, "dependencies": ["R0"],
                       "scenarios": [{"name": "Create", "steps": [{"Given": "empty", "When": "save", "Then": "persists"}]}]}]}
        import yaml
        (self.input / "requirements.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")
        raw, compiled = compile_requirements(self.input)
        self.assertEqual(raw, source)
        self.assertEqual(compiled["contracts"][0]["data"], source["data"])
        self.assertEqual(compiled["contracts"][1]["scenarios"], source["children"][0]["scenarios"])
        self.assertEqual(compiled["contracts"][1]["source"], "requirements.yaml#/children/0")
        self.assertEqual(compiled["children"]["ROOT"], ["R1"])
        self.assertEqual(compiled["implementation_ids"], ["R1"])

    def test_requirement_duplicate_ids_remain_distinct_with_source_ids(self):
        (self.input / "requirements.yaml").write_text(
            'id: ROOT\nchildren:\n- id: R\n  description: first\n- id: R\n  description: second\n', encoding="utf-8")
        _, compiled = compile_requirements(self.input)
        self.assertEqual(compiled["implementation_ids"], ["R", "R-2"])
        self.assertEqual(compiled["contracts"][2]["source_id"], "R")
        self.assertEqual(compiled["contracts"][2]["description"], "second")

    def acceptance_proposal(self):
        return {"files": {"REQ-1.spec.ts": "import {test,expect} from '@playwright/test';\ntest('notes',async({page})=>{await page.goto('/');await expect(page.getByRole('main')).toBeVisible();});"},
                "cases": [{"requirement_id": "REQ-1", "source": "requirements.yaml#",
                           "file": "REQ-1.spec.ts", "title": "notes"}]}

    def test_acceptance_compiler_uses_one_evidence_only_request_and_records_hashes(self):
        model = Mock()
        model.generate.return_value = (self.acceptance_proposal(), {"total_tokens": 20})
        output = self.root / "acceptance"
        report = generate_tests(self.input, output, model=model)
        model.generate.assert_called_once()
        payload = json.loads(model.generate.call_args.args[0][0]["content"])
        self.assertIn("contracts", payload["requirement_contracts"])
        self.assertNotIn("application_root", payload)
        self.assertEqual(report["uncovered_requirements"], [])
        self.assertEqual(len(report["files"]["REQ-1.spec.ts"]), 64)
        with self.assertRaisesRegex(ValueError, "new acceptance"):
            generate_tests(self.input, output, model=model)
        model.generate.assert_called_once()

    def test_acceptance_proposal_is_validated_before_writing(self):
        for problem in ("path", "evidence", "case"):
            proposal = self.acceptance_proposal()
            if problem == "path":
                proposal["files"]["../escape.ts"] = "bad"
            elif problem == "evidence":
                proposal["cases"][0]["source"] = "application/source.ts"
            else:
                proposal["cases"][0]["requirement_id"] = "unknown"
            model = Mock()
            model.generate.return_value = (proposal, {})
            output = self.root / problem
            with self.subTest(problem=problem), self.assertRaises(ValueError):
                generate_tests(self.input, output, model=model)
            self.assertFalse(output.exists())

    def test_acceptance_cannot_write_inside_original_input(self):
        with self.assertRaisesRegex(ValueError, "separate"):
            generate_tests(self.input, self.input / "tests", model=Mock())

    def test_browser_summary_requires_real_unskipped_cases(self):
        report = {"stats": {"expected": 1}, "suites": [{"specs": [{"title": "case", "file": "REQ-1.spec.ts",
                    "ok": True, "tests": [{"results": [{"status": "passed"}]}]}]}]}
        self.assertTrue(summarize(report, 0)["passed"])
        report["stats"]["skipped"] = 1
        self.assertFalse(summarize(report, 0)["passed"])
        self.assertFalse(summarize({"stats": {"expected": 1}}, 0)["passed"])

    def test_browser_summary_separates_network_failure_from_assertions(self):
        report = {"suites": [{"specs": [{"title": "case", "file": "REQ-1.spec.ts", "ok": False,
                   "tests": [{"results": [{"error": {"message": "ERR_NETWORK_ACCESS_DENIED"}}]}]}]}]}
        self.assertEqual(summarize(report, 1)["kind"], "CHECK_ENVIRONMENT_ERROR")
        report["suites"][0]["specs"][0]["tests"][0]["results"][0]["error"]["message"] = "Expected visible"
        self.assertEqual(summarize(report, 1)["kind"], "ASSERTION_FAILURE")

    def test_browser_suite_detects_changed_sources_and_maps_relative_report_paths(self):
        directory = self.root / "acceptance"
        model = Mock()
        model.generate.return_value = (self.acceptance_proposal(), {})
        generate_tests(self.input, directory, model=model)
        cli = self.root / "node_modules/@playwright/test/cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("// stub")
        suite = BrowserSuite(directory, cli)
        raw = {"stats": {"expected": 1}, "suites": [{"specs": [{"title": "notes", "file": "REQ-1.spec.ts",
               "ok": True, "tests": [{"results": [{"status": "passed"}]}]}]}]}
        with patch("infrastructure.react_agent.verification.capture_process") as capture:
            capture.return_value = {"returncode": 0, "stdout": json.dumps(raw), "stderr": "", "output": ""}
            result = suite("http://localhost:3000", self.root / "results", 5)
        self.assertEqual(result["requirements"]["REQ-1"]["status"], "PASSED")
        (directory / "REQ-1.spec.ts").write_text("changed")
        self.assertEqual(suite("http://localhost:3000", self.root / "results2", 5)["kind"], "TEST_SUITE_CHANGED")

    def test_startup_success_without_acceptance_keeps_requirements_unverified(self):
        _, report = self.run_agent([{"actions": [{"tool": "finish"}]}], checker=lambda *_: {"passed": True})
        self.assertTrue(all(item["status"] == "UNVERIFIED" for item in report["requirements"].values()))

    def test_external_acceptance_failure_is_returned_for_application_repair(self):
        result = {"passed": False, "acceptance": {"kind": "ASSERTION_FAILURE", "requirements": {"REQ-1": {"status": "FAILED"}}}}
        model, report = self.run_agent([{"actions": [{"tool": "finish"}]}],
                                       max_steps=1, checker=lambda *_: result)
        self.assertEqual(report["requirements"]["REQ-1"]["status"], "FAILED")
        self.assertEqual(report["status"], "STEP_LIMIT")

    def test_ui_role_annotations_keep_exact_evidence_and_conditional_name_default(self):
        (self.input / "requirements.yaml").write_text('''id: R
description: 'Show "Saved"(role=status) with "Undo"(role=button).'
''', encoding="utf-8")
        _, compiled = compile_requirements(self.input)
        status, button = compiled["ui_declarations"]
        self.assertEqual(status["evidence"], '"Saved"(role=status)')
        self.assertEqual(status["default_accessible_name"], "Saved")
        self.assertEqual(status["source"], "requirements.yaml#/description")
        self.assertNotIn("default_accessible_name", button)
        self.assertEqual(button["container"], status["id"])
        self.assertEqual(button["container_evidence"], '"Saved"(role=status) with "Undo"(role=button)')
        self.assertIn("Explicit requirements", compiled["website_defaults"]["feedback_names"])

    def test_expected_failure_cannot_count_as_passing_acceptance(self):
        raw = {"stats": {"expected": 1}, "suites": [{"specs": [{"title": "case", "file": "R.spec.ts", "ok": True,
               "tests": [{"expectedStatus": "failed", "results": [{"status": "failed"}]}]}]}]}
        self.assertFalse(summarize(raw, 0)["passed"])

    def test_skipped_cases_remain_unverified(self):
        raw = {"stats": {"skipped": 1}, "suites": [{"specs": [{"title": "case", "file": "R.spec.ts", "ok": True,
               "tests": [{"results": [{"status": "skipped"}]}]}]}]}
        report = summarize(raw, 0)
        self.assertFalse(report["passed"])
        self.assertEqual(report["cases"][0]["status"], "UNVERIFIED")

    def test_case_cannot_claim_unknown_ui_coverage(self):
        proposal = self.acceptance_proposal()
        proposal["cases"][0]["ui_checks"] = ["invented"]
        model = Mock()
        model.generate.return_value = (proposal, {})
        with self.assertRaisesRegex(ValueError, "declaration IDs"):
            generate_tests(self.input, self.root / "invalid-ui", model=model)

    def test_verify_action_runs_the_acceptance_gate(self):
        _, report = self.run_agent([{"actions": [{"tool": "verify"}]}], checker=lambda *_: {"passed": True})
        self.assertEqual(report["status"], "BUILD_AND_STARTUP_PASSED")

    def test_collection_detects_a_case_claim_that_has_no_executable_test(self):
        directory = self.root / "acceptance"
        proposal = self.acceptance_proposal()
        proposal["cases"].append({**proposal["cases"][0], "title": "invented test"})
        model = Mock()
        model.generate.return_value = (proposal, {})
        generate_tests(self.input, directory, model=model)
        cli = self.root / "node_modules/@playwright/test/cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("// stub")
        suite = BrowserSuite(directory, cli)
        raw = {"stats": {}, "suites": [{"specs": [{"title": "notes", "file": "REQ-1.spec.ts",
               "ok": True, "tests": [{"results": []}]}]}]}
        with patch("infrastructure.react_agent.verification.capture_process") as capture:
            capture.return_value = {"returncode": 0, "stdout": json.dumps(raw), "stderr": "", "output": ""}
            result = suite.collect(self.root / "results")
        self.assertFalse(result["passed"])
        self.assertEqual(result["kind"], "TEST_SUITE_ERROR")
        self.assertEqual(result["missing_case_claims"][0]["title"], "invented test")

    def test_collection_normalizes_relative_artifact_paths_before_process_start(self):
        cli = self.root / "node_modules/@playwright/test/cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("// stub")
        directory = self.root / "suite"
        directory.mkdir()
        suite = BrowserSuite(directory, cli)
        with TemporaryDirectory(dir=Path.cwd()) as temporary:
            relative = Path(temporary).relative_to(Path.cwd()) / "results"
            with patch("infrastructure.react_agent.verification.capture_process") as capture:
                capture.return_value = {"returncode": 0, "stdout": '{"suites":[]}', "stderr": "", "output": ""}
                suite.collect(relative)
            self.assertTrue(Path(capture.call_args.kwargs["cwd"]).is_absolute())
            self.assertTrue(Path(capture.call_args.args[0][4]).is_absolute())

    def test_resume_keeps_saved_actions_and_observations(self):
        self.run_agent([{"actions": [{"tool": "write", "path": "saved.txt", "content": "original"}]}], max_steps=1)
        model = ScriptedModel([{"actions": [{"tool": "verify"}]}])
        report = run(self.input, self.output, model=model, install=False, resume=True,
                     checker=lambda *_: {"passed": True})
        self.assertIn("original", json.dumps(model.requests[0]))
        self.assertEqual(report["previous_runs"][0]["status"], "STEP_LIMIT")
        self.assertGreaterEqual(report["total_elapsed_seconds"], report["elapsed_seconds"])
        self.assertEqual((self.output / "saved.txt").read_text(), "original")

    def test_resume_rejects_changed_original_requirements(self):
        self.run_agent([{"actions": [{"tool": "write", "path": "saved.txt", "content": "original"}]}], max_steps=1)
        snapshot = (self.output / ".arc/requirements.json").read_bytes()
        (self.input / "requirements.yaml").write_text('description: changed\n')
        with self.assertRaisesRegex(ValueError, "source changed"):
            run(self.input, self.output, install=False, resume=True, model=Mock())
        self.assertEqual((self.output / ".arc/requirements.json").read_bytes(), snapshot)


if __name__ == "__main__":
    unittest.main()
