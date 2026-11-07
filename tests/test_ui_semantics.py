"""The UI design IR must carry the accessibility contract the implementation renders.

Roles are derived from behavior in the design prompt, defaulted from the element type
during normalization, and reported when a declared role contradicts its element. These
tests keep that contract generic: nothing here may depend on one application's wording.
"""

from copy import deepcopy
import unittest

from infrastructure.stages.frontend.ui.design import (INSTRUCTIONS, ROLE_BY_TYPE,
    apply_proposal, derived_role, empty_design, normalize_design, page_context,
    semantic_issues)
from infrastructure.stages.frontend.ui.proposals import EXAMPLE
from infrastructure.stages.requirements.tree import RequirementTree


TREE_DOCUMENT = {"id": "ROOT", "name": "Root", "children": [
    {"id": "REQ-1", "name": "Search", "scenarios": [{"id": "SCE-1", "steps": [
        {"id": "STEP-1", "when": "open", "then": "results are visible"}]}]},
]}

DESIGN = {
    "pages": {"home": {"name": "Home", "route": "/", "root": "UI-home", "images": []}},
    "elements": {
        "UI-home": {"type": "page", "parent": None, "prop": {}},
        "UI-form": {"type": "form", "parent": "UI-home", "prop": {}},
        "UI-name": {"type": "input", "parent": "UI-form", "prop": {"label": "Name"}},
        "UI-active": {"type": "input", "parent": "UI-form",
            "prop": {"label": "Active", "input_type": "checkbox"}},
        "UI-save": {"type": "button", "parent": "UI-form", "name": "  Save  ",
            "prop": {"label": "Save"}},
        "UI-edit": {"type": "button", "role": "button", "parent": "UI-home",
            "prop": {"label": "Edit"}},
        "UI-results": {"type": "list", "role": "region", "parent": "UI-home", "prop": {}},
        "UI-nav": {"type": "container", "role": "navigation", "parent": "UI-home",
            "name": "Main navigation", "prop": {}},
    },
    "requirements": {"REQ-1": ["UI-home"]},
    "steps": {"STEP-1": ["UI-home"]},
}


class RoleDerivation(unittest.TestCase):
    def test_every_type_has_a_role(self):
        for kind, role in ROLE_BY_TYPE.items():
            with self.subTest(kind=kind):
                self.assertEqual(derived_role({"type": kind}), role)

    def test_input_roles_follow_the_input_type(self):
        self.assertEqual(derived_role({"type": "input", "prop": {"input_type": "checkbox"}}), "checkbox")
        self.assertEqual(derived_role({"type": "input", "prop": {"input_type": "number"}}), "spinbutton")
        self.assertEqual(derived_role({"type": "input"}), "textbox")

    def test_unknown_types_fall_back_to_a_container(self):
        self.assertEqual(derived_role({"type": "mystery"}), "container")
        self.assertEqual(derived_role({}), "container")


class Normalization(unittest.TestCase):
    def setUp(self):
        self.tree = RequirementTree(deepcopy(TREE_DOCUMENT))
        self.design = normalize_design(deepcopy(DESIGN), self.tree)

    def test_explicit_status_type_defaults_without_inventing_a_name(self):
        design = deepcopy(DESIGN)
        design["elements"]["UI-feedback"] = {
            "type": "status", "parent": "UI-home", "prop": {"text": "Operation complete"},
        }
        feedback = normalize_design(design, self.tree)["elements"]["UI-feedback"]
        self.assertEqual(feedback["role"], "status")
        self.assertNotIn("name", feedback)

    def test_explicit_role_wins_over_type_default(self):
        for role in ("status", "alert", "button", "link"):
            with self.subTest(role=role):
                design = deepcopy(DESIGN)
                design["elements"]["UI-feedback"] = {
                    "type": "container", "role": role, "name": "Operation complete",
                    "parent": "UI-home", "prop": {"text": "Operation complete"},
                }
                normalized = normalize_design(design, self.tree)
                feedback = normalized["elements"]["UI-feedback"]
                self.assertEqual(feedback["role"], role)
                self.assertEqual(feedback["name"], "Operation complete")

    def test_missing_roles_are_derived_from_the_element_type(self):
        self.assertEqual(self.design["elements"]["UI-home"]["role"], "page")
        self.assertEqual(self.design["elements"]["UI-name"]["role"], "textbox")
        self.assertEqual(self.design["elements"]["UI-active"]["role"], "checkbox")

    def test_declared_roles_survive_normalization(self):
        self.assertEqual(self.design["elements"]["UI-edit"]["role"], "button")
        self.assertEqual(self.design["elements"]["UI-results"]["role"], "region")

    def test_names_are_trimmed_and_empty_names_removed(self):
        self.assertEqual(self.design["elements"]["UI-save"]["name"], "Save")
        self.assertNotIn("name", self.design["elements"]["UI-name"])

    def test_an_explicit_action_role_corrects_a_link_type(self):
        design = deepcopy(DESIGN)
        design["elements"]["UI-edit"]["type"] = "link"
        normalized = normalize_design(design, self.tree)
        self.assertEqual(normalized["elements"]["UI-edit"]["type"], "button")
        self.assertEqual(normalized["elements"]["UI-edit"]["role"], "button")

    def test_every_element_carries_a_role_for_the_implementer(self):
        for uid, node in self.design["elements"].items():
            with self.subTest(uid=uid):
                self.assertIsInstance(node["role"], str)
                self.assertTrue(node["role"])


class SemanticIssues(unittest.TestCase):
    def setUp(self):
        self.tree = RequirementTree(deepcopy(TREE_DOCUMENT))

    def test_a_clean_design_reports_nothing(self):
        design = normalize_design(deepcopy(DESIGN), self.tree)
        design["elements"]["UI-results"]["name"] = "Results"
        self.assertEqual(semantic_issues(design), [])

    def test_an_action_that_stays_a_link_is_reported(self):
        design = normalize_design(deepcopy(DESIGN), self.tree)
        design["elements"]["UI-results"]["name"] = "Results"
        design["elements"]["UI-edit"]["type"] = "link"
        issues = semantic_issues(design)
        self.assertTrue(any("UI-edit" in issue and "conflicts" in issue for issue in issues))

    def test_an_unnamed_region_is_reported(self):
        design = normalize_design(deepcopy(DESIGN), self.tree)
        issues = semantic_issues(design)
        self.assertTrue(any("UI-results" in issue and "accessible name" in issue for issue in issues))

    def test_a_button_role_on_a_link_type_is_reported(self):
        design = normalize_design(deepcopy(DESIGN), self.tree)
        design["elements"]["UI-edit"]["type"] = "link"
        design["elements"]["UI-edit"]["role"] = "button"
        issues = semantic_issues(design)
        self.assertTrue(any("UI-edit" in issue and "conflicts" in issue for issue in issues))

    def test_a_visible_label_satisfies_a_named_role(self):
        design = normalize_design(deepcopy(DESIGN), self.tree)
        design["elements"]["UI-results"]["name"] = "Results"
        design["elements"]["UI-nav"]["prop"] = {"label": "Main navigation"}
        design["elements"]["UI-nav"].pop("name")
        issues = semantic_issues(design)
        self.assertFalse(any("UI-nav" in issue for issue in issues))


class Proposals(unittest.TestCase):
    def test_the_example_teaches_the_semantic_fields(self):
        for uid, node in EXAMPLE["elements"].items():
            with self.subTest(uid=uid):
                self.assertIn("role", node)
        self.assertEqual(EXAMPLE["elements"]["UI-results"]["role"], "region")
        self.assertTrue(EXAMPLE["elements"]["UI-results"]["name"])

    def test_apply_proposal_publishes_roles_to_the_page_context(self):
        tree = RequirementTree(deepcopy(TREE_DOCUMENT))
        design = apply_proposal(empty_design(), deepcopy(EXAMPLE), "REQ-1", tree)
        context = page_context(design, "home")
        self.assertEqual(context["elements"]["UI-home"]["role"], "page")
        self.assertEqual(context["elements"]["UI-results"]["name"], "Search results")

    def test_normalization_never_invents_labels(self):
        tree = RequirementTree(deepcopy(TREE_DOCUMENT))
        design = apply_proposal(empty_design(), deepcopy(EXAMPLE), "REQ-1", tree)
        self.assertNotIn("name", design["elements"]["UI-search"])
        self.assertEqual(design["elements"]["UI-search"]["prop"]["label"], "Search")


class PromptRules(unittest.TestCase):
    def test_prompt_states_the_accessibility_contract(self):
        for phrase in ("ACCESSIBILITY CONTRACT", "role button", "role navigation",
                "accessible name", "never modelled as a link"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, INSTRUCTIONS)

    def test_prompt_rule_is_generic_not_application_specific(self):
        start = INSTRUCTIONS.index("ACCESSIBILITY CONTRACT" + chr(10) + "Declare role")
        end = INSTRUCTIONS.index("pages maps PAGE IDs")
        section = INSTRUCTIONS[start:end].lower()
        for word in ("book", "shelf", "stack", "page title"):
            with self.subTest(word=word):
                self.assertNotIn(word, section)


if __name__ == "__main__":
    unittest.main()
