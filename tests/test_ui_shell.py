"""The UI design must declare one application shell shared by every page.

The shell is page-independent chrome: global elements have no page parent, they are not part
of any page subtree, and their IDs survive across requirements. These tests keep the rule
generic (no application-specific vocabulary) and check the paths that carry the shell from
the design request into the implementation task.
"""

from copy import deepcopy
import unittest

from infrastructure.stages.frontend.ui.design import (INSTRUCTIONS, apply_proposal,
    empty_design, normalize_design, page_context, page_elements, semantic_issues,
    shell_context, shell_elements)
from infrastructure.stages.frontend.ui.implementation import INSTRUCTIONS as IMPLEMENTATION
from infrastructure.stages.frontend.ui.proposals import EXAMPLE
from infrastructure.stages.frontend.ui.testing import existence_suite
from infrastructure.stages.requirements.tree import RequirementTree


TREE_DOCUMENT = {"id": "ROOT", "name": "Root", "children": [
    {"id": "REQ-1", "name": "Browse", "scenarios": [{"id": "SCE-1", "steps": [
        {"id": "STEP-1", "when": "open", "then": "content is visible"}]}]},
]}

DESIGN = {
    "pages": {
        "home": {"name": "Home", "route": "/", "root": "UI-home", "images": []},
        "books": {"name": "Books", "route": "/books", "root": "UI-books", "images": []},
    },
    "elements": {
        "UI-header": {"type": "container", "role": "banner", "scope": "global", "parent": None, "prop": {}},
        "UI-nav": {"type": "container", "role": "navigation", "name": "Main navigation",
            "scope": "global", "parent": "UI-header", "prop": {}},
        "UI-nav-books": {"type": "link", "role": "link", "parent": "UI-nav",
            "prop": {"label": "Books", "href": "/books"}},
        "UI-home": {"type": "page", "role": "page", "scope": "page", "parent": None, "prop": {}},
        "UI-home-title": {"type": "heading", "role": "heading", "parent": "UI-home",
            "prop": {"text": "Home"}},
        "UI-books": {"type": "page", "role": "page", "scope": "page", "parent": None, "prop": {}},
        "UI-books-list": {"type": "list", "role": "region", "name": "Book list",
            "parent": "UI-books", "prop": {}},
    },
    "requirements": {"REQ-1": ["UI-home", "UI-books"]},
    "steps": {"STEP-1": ["UI-books-list"]},
}


class ScopeNormalization(unittest.TestCase):
    def setUp(self):
        self.tree = RequirementTree(deepcopy(TREE_DOCUMENT))
        self.design = normalize_design(deepcopy(DESIGN), self.tree)

    def test_explicit_scopes_survive(self):
        self.assertEqual(self.design["elements"]["UI-header"]["scope"], "global")
        self.assertEqual(self.design["elements"]["UI-home"]["scope"], "page")

    def test_children_of_global_elements_inherit_the_scope(self):
        self.assertEqual(self.design["elements"]["UI-nav"]["scope"], "global")
        self.assertEqual(self.design["elements"]["UI-nav-books"]["scope"], "global")
        self.assertEqual(self.design["elements"]["UI-home-title"]["scope"], "page")

    def test_missing_scope_defaults_to_page(self):
        design = normalize_design(deepcopy(DESIGN), self.tree)
        self.assertEqual(design["elements"]["UI-books-list"]["scope"], "page")

    def test_global_subtrees_are_atomic(self):
        design = deepcopy(DESIGN)
        design["elements"]["UI-nav-books"]["scope"] = "page"
        normalized = normalize_design(design, self.tree)
        self.assertEqual(normalized["elements"]["UI-nav-books"]["scope"], "global")


class ShellProjection(unittest.TestCase):
    def setUp(self):
        self.tree = RequirementTree(deepcopy(TREE_DOCUMENT))
        self.design = normalize_design(deepcopy(DESIGN), self.tree)

    def test_shell_contains_global_elements_only(self):
        shell = shell_elements(self.design)
        self.assertEqual(sorted(shell), ["UI-header", "UI-nav", "UI-nav-books"])

    def test_pages_exclude_the_shell(self):
        home = page_elements(self.design, "home")
        self.assertEqual(sorted(home), ["UI-home", "UI-home-title"])

    def test_shell_context_reports_its_roots(self):
        context = shell_context(self.design)
        self.assertEqual(context["roots"], ["UI-header"])

    def test_page_context_carries_the_shell_separately(self):
        context = page_context(self.design, "books")
        self.assertIn("UI-books", context["elements"])
        self.assertNotIn("UI-nav", context["elements"])
        self.assertIn("UI-nav", context["shell"]["elements"])

    def test_the_shell_is_not_duplicated_into_page_existence_tests(self):
        suite = existence_suite(self.design, "books")
        self.assertIn("UI-books-list", suite)
        self.assertNotIn("UI-nav", suite)


class ShellIssues(unittest.TestCase):
    def setUp(self):
        self.tree = RequirementTree(deepcopy(TREE_DOCUMENT))
        self.design = normalize_design(deepcopy(DESIGN), self.tree)

    def test_a_consistent_shell_reports_nothing(self):
        self.assertEqual(semantic_issues(self.design), [])

    def test_a_global_element_inside_a_page_is_reported(self):
        design = deepcopy(DESIGN)
        design["elements"]["UI-nav"]["parent"] = "UI-home"
        normalized = normalize_design(design, self.tree)
        issues = semantic_issues(normalized)
        self.assertTrue(any("UI-nav" in issue and "nested in a page" in issue for issue in issues))

    def test_pages_without_any_shell_are_reported(self):
        design = deepcopy(DESIGN)
        for uid in ("UI-header", "UI-nav", "UI-nav-books"):
            design["elements"].pop(uid)
        normalized = normalize_design(design, self.tree)
        self.assertTrue(any("share no global shell" in issue for issue in semantic_issues(normalized)))

    def test_a_single_page_needs_no_shell(self):
        design = deepcopy(DESIGN)
        for uid in ("UI-header", "UI-nav", "UI-nav-books"):
            design["elements"].pop(uid)
        design["pages"] = {"home": design["pages"]["home"]}
        normalized = normalize_design(design, self.tree)
        self.assertEqual(semantic_issues(normalized), [])


class ProposalAndPrompt(unittest.TestCase):
    def test_the_example_declares_a_page_independent_shell(self):
        nav = EXAMPLE["elements"]["UI-app-nav"]
        self.assertEqual(nav["scope"], "global")
        self.assertIsNone(nav["parent"])
        self.assertEqual(nav["role"], "navigation")

    def test_applying_the_example_keeps_the_shell_out_of_pages(self):
        tree = RequirementTree(deepcopy(TREE_DOCUMENT))
        design = apply_proposal(empty_design(), deepcopy(EXAMPLE), "REQ-1", tree)
        self.assertIn("UI-app-nav", shell_elements(design))
        context = page_context(design, "home")
        self.assertNotIn("UI-app-nav", context["elements"])
        self.assertIn("UI-app-nav", context["shell"]["elements"])

    def test_design_prompt_states_the_shell_rules(self):
        section = INSTRUCTIONS[INSTRUCTIONS.index("APPLICATION SHELL"):]
        section = section[:section.index("ACCESSIBILITY CONTRACT")]
        for phrase in ("scope", "not once per page", "primary navigation", "Reuse the shell"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section.lower() if phrase == "reuse the shell" else section)

    def test_shell_rule_is_generic_not_application_specific(self):
        section = INSTRUCTIONS[INSTRUCTIONS.index("APPLICATION SHELL"):]
        section = section[:section.index("ACCESSIBILITY CONTRACT")].lower()
        for word in ("book", "shelf", "stack", "page title"):
            with self.subTest(word=word):
                self.assertNotIn(word, section)

    def test_implementation_prompt_renders_the_shell_once(self):
        self.assertIn("task.page.shell", IMPLEMENTATION)
        self.assertIn("APPLICATION SHELL", IMPLEMENTATION)
        self.assertIn("Never declare a second header", IMPLEMENTATION)


if __name__ == "__main__":
    unittest.main()
