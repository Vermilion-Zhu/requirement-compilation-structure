"""Input robustness and ARC-Bench observability.

Real tasks are directories, not the teaching example: attachments may be missing or
malformed, scenario/step IDs may be absent, ``description`` may be a string, a
mapping or a list, and a referenced image may not exist. None of that may abort a
run, because a published requirement snapshot is what every later pass reads.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest
from unittest.mock import patch

from infrastructure.shared.project import runtime_events
from infrastructure.stages.passes.explore_requirement import collect_images, explore_requirement
from infrastructure.stages.requirements.input_materials import (
    collect_materials, publish_input_snapshot, resolve_images)
from infrastructure.stages.requirements.tree import RequirementTree


MINIMAL = "id: ROOT\nname: Minimal\nchildren: []\n"


def publish(root: Path, text: str):
    source = root / "input"
    source.mkdir(parents=True, exist_ok=True)
    (source / "requirements.yaml").write_text(text, encoding="utf-8")
    return source


class RequirementTreeTolerance(unittest.TestCase):
    def test_missing_scenario_and_step_ids_are_generated_deterministically(self):
        tree = RequirementTree({"id": "ROOT", "children": [
            {"id": "REQ-1", "name": "Page", "scenarios": [
                {"name": "open", "steps": [{"when": "open", "then": "visible"}]}]}]})
        self.assertEqual(sorted(tree.steps), ["STEP-REQ-1-1-1"])
        self.assertEqual(len(tree.leaves), 1)
        self.assertIn("Scenario SCE-REQ-1-1: open", tree.concatenated_steps("REQ-1"))
        self.assertEqual(tree.generated_ids, ["SCE-REQ-1-1", "STEP-REQ-1-1-1"])

    def test_duplicate_supplied_ids_are_disambiguated_and_reported(self):
        tree = RequirementTree({"id": "ROOT", "children": [
            {"id": "REQ-1"}, {"id": "REQ-1"}]})
        self.assertEqual(sorted(tree.requirements), ["REQ-1", "REQ-1-2", "ROOT"])
        self.assertIn("REQ-1-2", tree.generated_ids)

    def test_description_shapes_and_malformed_children_do_not_break_indexing(self):
        tree = RequirementTree({"id": "ROOT", "description": ["line one", {"text": "line two"}],
            "children": [{"id": "REQ-1", "description": {"text": "mapped"}, "scenarios": None},
                "not a node", {"id": "REQ-2", "children": {"id": "nested"}}]})
        self.assertEqual(tree.requirements["ROOT"]["description"], "line one\nline two")
        self.assertEqual(tree.requirements["REQ-1"]["description"], "mapped")
        self.assertEqual(tree.children["REQ-2"], [])
        self.assertEqual(tree.leaves, ["REQ-1", "REQ-2"])

    def test_a_root_without_requirements_is_rejected_clearly(self):
        with self.assertRaisesRegex(ValueError, "root must be an object"):
            RequirementTree(["not", "a", "mapping"])
        # A root without an id still becomes one node; generated ids keep it addressable.
        tree = RequirementTree({"name": "only a name"})
        self.assertEqual(sorted(tree.requirements), ["REQ-1"])
        self.assertEqual(tree.generated_ids, ["REQ-1"])


class InputMaterials(unittest.TestCase):
    def test_materials_are_described_and_text_is_bounded(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "requirements.md").write_text("# Docs\nExtra detail.\n", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "mock.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
            (root / "reference").mkdir()
            (root / "reference" / "notes.txt").write_text("reference note", encoding="utf-8")
            materials = collect_materials(root)
            by_path = {item["path"]: item for item in materials["files"]}
            self.assertEqual(set(by_path), {"requirements.md", "assets/mock.png", "reference/notes.txt"})
            self.assertEqual(by_path["requirements.md"]["kind"], "text")
            self.assertIn("Extra detail", by_path["requirements.md"]["text"])
            self.assertEqual(by_path["assets/mock.png"]["kind"], "attachment")
            self.assertEqual(materials["warnings"], [])

    def test_an_unreadable_text_material_becomes_a_warning(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "prerequisites.md").write_bytes(b"\xff\xfe\x00broken")
            materials = collect_materials(root)
            self.assertEqual(materials["files"][0]["kind"], "attachment")
            self.assertIn("not UTF-8 text", materials["warnings"][0]["reason"])

    def test_image_references_outside_or_missing_are_reported_not_raised(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "assets").mkdir()
            (root / "assets" / "ok.png").write_bytes(b"png")
            resolved, warnings = resolve_images(root, ["assets/ok.png", "assets/missing.png", "../outside.png"])
            self.assertEqual(list(resolved), ["assets/ok.png"])
            reasons = sorted(warning["reason"] for warning in warnings)
            self.assertEqual(reasons, ["outside the requirement directory", "referenced image does not exist"])

    def test_malformed_image_entries_are_collected_as_warnings(self):
        warnings = []
        references = collect_images({"description": {"image": [
            {"reference": "assets/a.png"}, {"id": "no-reference"}, {"reference": "  "}, "not a mapping"]}},
            warnings)
        self.assertEqual(references, ["assets/a.png"])
        self.assertEqual(len(warnings), 3)


class ExplorePassTolerance(unittest.TestCase):
    def test_a_missing_image_and_markdown_material_still_publish_the_snapshot(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = publish(root, "id: ROOT\nname: With image\nchildren:\n"
                "  - id: REQ-1\n    name: Page\n    description:\n"
                "      text: Show the page.\n      image:\n"
                "        - id: IMG-1\n          reference: assets/gone.png\n")
            (source / "requirements.md").write_text("Additional notes.\n", encoding="utf-8")
            arc = root / "application" / ".arc"
            with patch("infrastructure.stages.passes.explore_requirement.VisualModel") as model:
                requirements = explore_requirement(source, arc)
            model.assert_not_called()
            self.assertEqual(requirements["id"], "ROOT")
            self.assertTrue((arc / "requirements.json").is_file())
            warnings = json.loads((arc / "input_warnings.json").read_text(encoding="utf-8"))
            self.assertEqual(warnings["warnings"][0]["reason"], "referenced image does not exist")
            materials = json.loads((arc / "input_materials.json").read_text(encoding="utf-8"))
            self.assertEqual([item["path"] for item in materials["files"]], ["requirements.md"])

    def test_a_resolvable_image_is_analyzed_with_its_resolved_path(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = publish(root, "id: ROOT\nchildren:\n  - id: REQ-1\n    description:\n"
                "      image:\n        - reference: assets/ok.png\n")
            (source / "assets").mkdir()
            (source / "assets" / "ok.png").write_bytes(b"png")
            arc = root / "application" / ".arc"
            with patch("infrastructure.stages.passes.explore_requirement.VisualModel") as model:
                model.return_value.analyze.return_value = {"layout": "single page"}
                explore_requirement(source, arc)
            _, argument = model.return_value.analyze.call_args
            self.assertEqual(argument, {})
            analyzed = model.return_value.analyze.call_args.args[0]
            self.assertEqual(analyzed, (source / "assets" / "ok.png").resolve())
            analysis = json.loads((arc / "visual_analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(analysis, {"assets/ok.png": {"layout": "single page"}})

    def test_publish_input_snapshot_writes_every_artifact(self):
        with TemporaryDirectory() as temporary:
            arc = Path(temporary) / ".arc"
            publish_input_snapshot(arc, "{}", ["assets/a.png"], materials={"files": [], "warnings": []},
                warnings=[{"reference": "assets/a.png", "reason": "gone"}])
            self.assertTrue((arc / "requirements.json").is_file())
            self.assertTrue((arc / "input_materials.json").is_file())
            warnings = json.loads((arc / "input_warnings.json").read_text(encoding="utf-8"))
            self.assertEqual(warnings["image_references"], ["assets/a.png"])
            self.assertEqual(warnings["warnings"][0]["reason"], "gone")


class RuntimeEvents(unittest.TestCase):
    def setUp(self):
        # The adapter caches its runtime; each test starts from a clean process-level state.
        runtime_events._RUNTIME = None
        runtime_events._ENABLED = False
        runtime_events._WARNED = False
        self.addCleanup(setattr, runtime_events, "_RUNTIME", None)
        self.addCleanup(setattr, runtime_events, "_ENABLED", False)
        self.addCleanup(setattr, runtime_events, "_WARNED", False)

    def test_events_and_traceability_are_recorded_for_a_local_run(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertTrue(runtime_events.initialize(root))
            runtime_events.start("check")
            runtime_events.store_requirement_tree({"id": "ROOT", "children": [{"id": "REQ-1"}]})
            runtime_events.design_done("REQ-1")
            runtime_events.implementation_done("REQ-1")
            runtime_events.test_result("REQ-1", True)
            runtime_events.finish(True, "done")
            events = [json.loads(line) for line in
                (root / ".arc" / "runner-events.jsonl").read_text(encoding="utf-8").splitlines()]
            kinds = [event["type"] for event in events]
            self.assertIn("runner_state", kinds)
            self.assertEqual(kinds.count("requirement_state"), 3)
            states = (root / ".arc" / "traceability" / "requirements.json").read_text(encoding="utf-8")
            self.assertIn("REQ-1", states)
            node_states = (root / ".arc" / "traceability" / "node_states.json").read_text(encoding="utf-8")
            self.assertIn("PASSED", node_states)

    def test_a_missing_sdk_disables_events_without_failing_the_run(self):
        with TemporaryDirectory() as temporary, patch(
                "infrastructure.shared.project.runtime_events.load_agent_runtime", return_value=None):
            self.assertFalse(runtime_events.initialize(Path(temporary)))
            self.assertFalse(runtime_events.enabled())
            runtime_events.start("ignored")
            runtime_events.test_result("REQ-1", True)
            self.assertFalse((Path(temporary) / ".arc" / "runner-events.jsonl").exists())

    def test_a_broken_artifact_directory_does_not_raise(self):
        with TemporaryDirectory() as temporary:
            blocked = Path(temporary) / "blocked"
            blocked.write_text("not a directory", encoding="utf-8")
            self.assertFalse(runtime_events.initialize(blocked))
            runtime_events.finish(True)


if __name__ == "__main__":
    unittest.main()
