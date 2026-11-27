"""Offline contracts for experimental implementation planning and batch verification."""

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.react_agent.planning import batch_contract_context, fallback_plan, plan_implementation, validate_plan
from infrastructure.react_agent.requirements import compile_requirements
from infrastructure.react_agent.runner import run
from infrastructure.react_agent.verification import BrowserSuite


def requirements_yaml(count=3, scenario_limit=False):
    lines = ["id: ROOT", "name: Root", "children:"]
    for index in range(1, count + 1):
        lines.extend([f"  - id: R{index}", f"    name: Requirement {index}",
            f"    description: Implement feature {index}"])
        if scenario_limit:
            lines.extend(["    scenarios:", f"      - id: S{index}", "        steps:",
                f"          - id: STEP{index}", "            When: do it", "            Then: done"])
    return "\n".join(lines) + "\n"


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def generate(self, messages, timeout, instructions=None):
        self.requests.append(copy.deepcopy(messages))
        reply = next(self.replies)
        return reply, {"total_tokens": 7}


class PlanningTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.input = self.root / "input"
        self.input.mkdir()
        self.output = self.root / "application"

    def contracts(self, count=3):
        (self.input / "requirements.yaml").write_text(requirements_yaml(count), encoding="utf-8")
        return compile_requirements(self.input)[1]

    def manifest(self, *titles):
        return {"cases": [{"requirement_id": title.split(" ")[0], "title": title} for title in titles]}

    def test_fallback_plan_covers_every_requirement_in_dependency_order(self):
        contracts = self.contracts(3)
        plan = fallback_plan(contracts, scenario_limit=1)
        self.assertEqual([batch["requirements"] for batch in plan["batches"]],
            [["R1"], ["R2"], ["R3"]])
        self.assertEqual(plan["batches"][1]["depends_on"], [plan["batches"][0]["id"]])

    def test_frozen_cases_are_mapped_to_their_requirement_batch(self):
        contracts = self.contracts(2)
        manifest = self.manifest("R1 alpha", "R1 beta", "R2 gamma")
        plan = fallback_plan(contracts, manifest, scenario_limit=1)
        self.assertEqual(plan["batches"][0]["tests"], ["R1 alpha", "R1 beta"])
        self.assertEqual(plan["batches"][1]["tests"], ["R2 gamma"])

    def test_plan_rejects_missing_duplicate_and_cyclic_requirements(self):
        contracts = self.contracts(2)
        base = {"batches": [{"id": "B1", "requirements": ["R1"], "depends_on": []}]}
        with self.assertRaisesRegex(ValueError, "missing implementation ids"):
            validate_plan(base, contracts)
        with self.assertRaisesRegex(ValueError, "more than once"):
            validate_plan({"batches": [{"id": "B1", "requirements": ["R1"]},
                {"id": "B2", "requirements": ["R1", "R2"]}]}, contracts)
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_plan({"batches": [
                {"id": "B1", "requirements": ["R1"], "depends_on": ["B2"]},
                {"id": "B2", "requirements": ["R2"], "depends_on": ["B1"]}]}, contracts)

    def test_batch_context_keeps_current_batch_and_summarizes_other_requirements(self):
        contracts = self.contracts(3)
        plan = fallback_plan(contracts, scenario_limit=1)
        context = batch_contract_context(contracts, plan, plan["batches"][1])
        included = {item["id"] for item in context["contracts"]}
        self.assertIn("ROOT", included)
        self.assertIn("R2", included)
        self.assertNotIn("R1", included)
        self.assertEqual(context["ui_declarations"], contracts["ui_declarations"])
        self.assertEqual(context["website_defaults"], contracts["website_defaults"])
        other = {item["id"]: item for item in context["other_requirements"]}
        self.assertIn("R1", other)
        self.assertNotIn("R2", other)
        self.assertLessEqual(len(other["R1"]["summary"]), 201)

    def test_model_plan_is_validated_and_falls_back_on_rejection(self):
        contracts = self.contracts(2)
        model = Mock()
        model.generate.return_value = ({"batches": [
            {"id": "B1", "requirements": ["R1"]},
            {"id": "B2", "requirements": ["R2"], "depends_on": ["B1"]}]}, {"total_tokens": 5})
        plan, meta = plan_implementation(contracts, {"cases": [
            {"requirement_id": "R1", "title": "R1 / first"},
            {"requirement_id": "R2", "title": "R2 / second"}]}, model=model)
        self.assertEqual(plan["source"], "model")
        self.assertEqual(meta["attempts"][0]["status"], "VALIDATED")
        bad = Mock()
        bad.generate.return_value = ({"batches": [{"id": "B1", "requirements": ["missing"]}]}, {})
        fallback, meta = plan_implementation(contracts, None, model=bad)
        self.assertEqual(fallback["source"], "fallback")
        self.assertTrue(fallback["warnings"])


class BatchRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.input = self.root / "input"
        self.input.mkdir()
        (self.input / "requirements.yaml").write_text(requirements_yaml(3), encoding="utf-8")
        self.output = self.root / "application"
        self.contracts = compile_requirements(self.input)[1]
        self.plan = fallback_plan(self.contracts, scenario_limit=1)

    def test_each_batch_verification_advances_before_the_final_full_check(self):
        model = ScriptedModel([{"actions": [{"tool": "verify"}]}] * 3)
        checks = []
        def checker(output, remaining):
            checks.append(remaining)
            return {"passed": True}
        report = run(self.input, self.output, model=model, install=False,
            plan=self.plan, checker=checker)
        self.assertEqual(report["status"], "BUILD_AND_STARTUP_PASSED")
        self.assertEqual(len(checks), 4)
        self.assertEqual([batch["status"] for batch in report["plan"]["batches"]],
            ["PASSED", "PASSED", "PASSED"])
        payloads = [json.loads(request[-1]["content"]) for request in model.requests]
        self.assertTrue(any("batch_transition" in payload for payload in payloads))
        initial = json.loads(model.requests[0][0]["content"])["requirement_contracts"]
        self.assertEqual({item["id"] for item in initial["contracts"]}, {"ROOT", "R1"})
        self.assertEqual({item["id"] for item in initial["other_requirements"]}, {"R2", "R3"})
        second = json.loads(model.requests[1][0]["content"])["requirement_contracts"]
        self.assertEqual({item["id"] for item in second["contracts"]}, {"ROOT", "R2"})
        transition = next(payload["batch_transition"] for payload in payloads if "batch_transition" in payload)
        self.assertTrue(transition["requirement_context_updated"])
        self.assertNotIn("requirement_context", transition)

    def test_batch_failure_does_not_advance(self):
        model = ScriptedModel([{"actions": [{"tool": "verify"}]}])
        report = run(self.input, self.output, model=model, install=False,
            plan=self.plan, checker=lambda *_: {"passed": False},
            max_steps=1)
        self.assertEqual(report["status"], "STEP_LIMIT")
        self.assertEqual(report["plan"]["current_index"], 0)
        self.assertEqual(report["plan"]["batches"][0]["status"], "IN_PROGRESS")


class BrowserSubsetTests(unittest.TestCase):
    def test_browser_suite_passes_selected_cases_to_grep_and_ignores_unselected_claims(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        directory = root / "acceptance"
        directory.mkdir()
        (directory / "acceptance.spec.ts").write_text("// stub")
        manifest = {"cases": [
            {"requirement_id": "R1", "title": "R1 / first", "file": "acceptance.spec.ts"},
            {"requirement_id": "R2", "title": "R2 / second", "file": "acceptance.spec.ts"}]}
        (directory / "acceptance-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        cli = root / "node_modules/@playwright/test/cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("// stub")
        suite = BrowserSuite(directory, cli)
        raw = {"stats": {"expected": 1}, "suites": [{"specs": [{"title": "R1 / first",
            "file": "acceptance.spec.ts", "ok": True, "tests": [{"results": [{"status": "passed"}]}]}]}]}
        with patch("infrastructure.react_agent.verification.capture_process") as capture:
            capture.return_value = {"returncode": 0, "stdout": json.dumps(raw), "stderr": "", "output": ""}
            result = suite("http://localhost:3000", root / "results", 5, cases=["R1 / first"])
        command = capture.call_args.args[0]
        self.assertIn("--grep", command)
        self.assertIn("R1", command[command.index("--grep") + 1])
        self.assertTrue(result["passed"])
        self.assertEqual(result["requirements"]["R1"]["status"], "PASSED")
        self.assertNotIn("R2", result["requirements"])


if __name__ == "__main__":
    unittest.main()
