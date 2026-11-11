"""The UI design IR must carry the accessibility contract the implementation renders.

Roles are derived from behavior in the design prompt, defaulted from the element type
during normalization, and reported when a declared role contradicts its element. These
tests keep that contract generic: nothing here may depend on one application's wording.
"""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from infrastructure.stages.frontend.ui.design import (INSTRUCTIONS, ROLE_BY_TYPE,
    apply_proposal, derived_role, empty_design, normalize_design, page_context,
    semantic_issues)
from infrastructure.stages.frontend.ui.implementation import INSTRUCTIONS as IMPLEMENTATION
from infrastructure.stages.frontend.ui.proposals import EXAMPLE
from infrastructure.stages.frontend.ui.synthesis import repair_semantics, synthesize_ui
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


class DuplicateNavigation(unittest.TestCase):
    def setUp(self):
        self.tree = RequirementTree(deepcopy(TREE_DOCUMENT))
        self.design = {
            "pages": {
                "home": {"name": "Home", "route": "/", "root": "UI-home", "images": []},
                "books": {"name": "Books", "route": "/books", "root": "UI-books", "images": []},
            },
            "elements": {
                "UI-app-header": {"type": "container", "role": "banner", "scope": "global",
                    "parent": None, "prop": {}},
                "UI-app-nav": {"type": "container", "role": "navigation", "name": "Main navigation",
                    "scope": "global", "parent": "UI-app-header", "prop": {}},
                "UI-books-link": {"type": "link", "role": "link", "parent": "UI-app-nav",
                    "prop": {"label": "Books", "href": "/books"}},
                "UI-home": {"type": "page", "parent": None, "prop": {}},
                "UI-books": {"type": "page", "parent": None, "prop": {}},
                "UI-breadcrumb": {"type": "container", "role": "navigation",
                    "name": "Breadcrumb", "parent": "UI-home", "prop": {}},
                "UI-breadcrumb-books": {"type": "link", "role": "link", "parent": "UI-breadcrumb",
                    "prop": {"label": "Books", "href": "/books"}},
            },
            "requirements": {"REQ-1": ["UI-home"]},
            "steps": {"STEP-1": ["UI-home"]},
        }

    def test_a_page_navigation_repeating_a_global_link_is_reported(self):
        design = normalize_design(deepcopy(self.design), self.tree)
        issues = semantic_issues(design)
        self.assertTrue(any("UI-breadcrumb" in issue and "repeats the global link" in issue
            for issue in issues), issues)

    def test_a_page_link_row_with_distinct_links_is_fine(self):
        design = deepcopy(self.design)
        design["elements"]["UI-breadcrumb-books"]["prop"] = {"label": "Home", "href": "/"}
        normalized = normalize_design(design, self.tree)
        self.assertFalse(any("repeats the global link" in issue
            for issue in semantic_issues(normalized)))

    def test_the_shell_itself_is_not_reported(self):
        design = normalize_design(deepcopy(self.design), self.tree)
        issues = semantic_issues(design)
        self.assertFalse(any("UI-app-nav" in issue for issue in issues))

class StateBindings(unittest.TestCase):
    def setUp(self):
        self.tree = RequirementTree(deepcopy(TREE_DOCUMENT))

    def test_a_declared_state_survives_normalization(self):
        design = deepcopy(DESIGN)
        design["elements"]["UI-edit"]["state"] = {"pressed": {"var": "note.pinned", "equals": True}}
        normalized = normalize_design(design, self.tree)
        self.assertEqual(normalized["elements"]["UI-edit"]["state"],
            {"pressed": {"var": "note.pinned", "equals": True}})

    def test_unknown_state_keys_and_malformed_state_are_dropped(self):
        design = deepcopy(DESIGN)
        design["elements"]["UI-edit"]["state"] = {"aria-pressed": True, "sparkle": True, "bad": "x"}
        normalized = normalize_design(design, self.tree)
        self.assertEqual(normalized["elements"]["UI-edit"]["state"], {"pressed": True})
        design["elements"]["UI-edit"]["state"] = "pressed"
        self.assertNotIn("state", normalize_design(design, self.tree)["elements"]["UI-edit"])

    def test_semantic_issues_report_unrenderable_state(self):
        design = normalize_design(deepcopy(DESIGN), self.tree)
        design["elements"]["UI-results"]["name"] = "Results"
        design["elements"]["UI-edit"]["state"] = {"pressed": "note.pinned"}
        self.assertTrue(any("needs a boolean or a variable rule" in issue
            for issue in semantic_issues(design)))

    def test_a_valid_state_produces_no_issue(self):
        design = normalize_design(deepcopy(DESIGN), self.tree)
        design["elements"]["UI-results"]["name"] = "Results"
        design["elements"]["UI-edit"]["state"] = {"pressed": {"var": "note.pinned", "equals": True}}
        self.assertEqual(semantic_issues(design), [])

    def test_dynamic_name_templates_are_kept(self):
        design = deepcopy(DESIGN)
        design["elements"]["UI-results"]["name"] = "{note.title}"
        normalized = normalize_design(design, self.tree)
        self.assertEqual(normalized["elements"]["UI-results"]["name"], "{note.title}")

    def test_the_example_teaches_state_and_status(self):
        filter_node = EXAMPLE["elements"]["UI-archived-filter"]
        self.assertEqual(filter_node["state"]["pressed"], {"var": "search.archived", "equals": True})
        self.assertIn("status", INSTRUCTIONS)
        self.assertIn("role status; errors and interruption warnings are role alert", INSTRUCTIONS)


class RepairRound(unittest.TestCase):
    def test_reported_issues_get_one_repair_call(self):
        tree = RequirementTree(deepcopy(TREE_DOCUMENT))
        contexts = {"REQ-1": {"id": "REQ-1", "name": "Search", "description": "search",
            "steps": [tree.steps["STEP-1"]], "images": {}}}
        requests = []

        def generate(instructions, request):
            requests.append(request)
            if len(requests) == 1:
                return {"elements": {
                    "UI-home": {"type": "page", "role": "page", "parent": None,
                        "mode": [], "data": [], "prop": {}},
                    "UI-results": {"type": "list", "role": "region", "parent": "UI-home",
                        "mode": [], "data": [], "prop": {}},
                }, "pages": {"home": {"name": "Home", "route": "/", "root": "UI-home", "images": []}},
                    "requirement_ui": ["UI-home", "UI-results"],
                    "step_ui": {"STEP-1": ["UI-results"]}}
            return {"elements": {"UI-results": {"type": "list", "role": "region",
                "name": "Results", "parent": "UI-home", "mode": [], "data": [], "prop": {}}}}

        with TemporaryDirectory() as temporary:
            design = synthesize_ui(Path(temporary), tree, {}, contexts,
                Mock(generate_json=generate), Mock(), max_attempts=2)
        self.assertEqual(len(requests), 2)
        self.assertIn("issues", requests[1])
        self.assertEqual(design["elements"]["UI-results"]["name"], "Results")
        self.assertEqual(semantic_issues(design), [])

    def test_the_repair_round_can_drop_a_duplicate_navigation_landmark(self):
        tree = RequirementTree(deepcopy(TREE_DOCUMENT))
        design = normalize_design({
            "pages": {
                "home": {"name": "Home", "route": "/", "root": "UI-home", "images": []},
                "books": {"name": "Books", "route": "/books", "root": "UI-books", "images": []},
            },
            "elements": {
                "UI-app-nav": {"type": "container", "role": "navigation", "name": "Main navigation",
                    "scope": "global", "parent": None, "prop": {}},
                "UI-books-link": {"type": "link", "role": "link", "parent": "UI-app-nav",
                    "prop": {"label": "Books"}},
                "UI-home": {"type": "page", "parent": None, "prop": {}},
                "UI-books": {"type": "page", "parent": None, "prop": {}},
                "UI-breadcrumb": {"type": "container", "role": "navigation", "name": "Breadcrumb",
                    "parent": "UI-home", "prop": {}},
                "UI-breadcrumb-books": {"type": "link", "role": "link", "parent": "UI-breadcrumb",
                    "prop": {"label": "Books"}},
            },
            "requirements": {"REQ-1": ["UI-home"]}, "steps": {},
        }, tree)
        self.assertTrue(any("repeats the global link" in issue for issue in semantic_issues(design)))

        def repair(instructions, request):
            self.assertTrue(any("repeats the global link" in issue for issue in request["issues"]))
            return {"elements": {"UI-breadcrumb": {"type": "container", "role": "container",
                "parent": "UI-home", "mode": [], "data": [], "prop": {}}}}

        updated = repair_semantics(design, tree, Mock(generate_json=repair), Mock())
        self.assertFalse(any("repeats the global link" in issue
            for issue in semantic_issues(updated)))
        self.assertIn("UI-breadcrumb-books", updated["elements"])


class PromptRules(unittest.TestCase):
    def test_prompt_states_the_accessibility_contract(self):
        for phrase in ("ACCESSIBILITY CONTRACT", "role button", "role navigation",
                "accessible name", "never modelled as a link"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, INSTRUCTIONS)

    def test_the_design_prompt_forbids_a_second_navigation_landmark(self):
        for phrase in ("not as a second navigation landmark", "breadcrumb",
                "Only the shell declares the", "primary navigation"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, INSTRUCTIONS)

    def test_the_implementation_prompt_has_the_same_exception(self):
        self.assertIn("must not become a second", IMPLEMENTATION)
        self.assertIn("breadcrumb", IMPLEMENTATION)

    def test_prompt_rule_is_generic_not_application_specific(self):
        start = INSTRUCTIONS.index("ACCESSIBILITY CONTRACT" + chr(10) + "Declare role")
        end = INSTRUCTIONS.index("pages maps PAGE IDs")
        section = INSTRUCTIONS[start:end].lower()
        for word in ("book", "shelf", "stack", "page title"):
            with self.subTest(word=word):
                self.assertNotIn(word, section)


if __name__ == "__main__":
    unittest.main()
