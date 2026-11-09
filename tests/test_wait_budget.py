"""M2: generated browser tests bound their own waits so failures surface in seconds.

The E2E runner keeps a 30 second test timeout as a backstop, but a failing spec used to
consume the whole budget per case. The generation prompts now require an explicit 5-8 second
timeout on request, navigation and route waits.
"""

import unittest

from infrastructure.stages.frontend.triggers.acceptance import INSTRUCTIONS as ACCEPTANCE
from infrastructure.stages.frontend.triggers.implementation import TEST_INSTRUCTIONS


class FunctionalSpecs(unittest.TestCase):
    def test_request_and_navigation_waits_are_bounded(self):
        for phrase in ("5-8 second timeout", "waitForResponse", "Do not rely on the"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, TEST_INSTRUCTIONS)

    def test_the_rule_explains_fast_failure(self):
        self.assertIn("fail fast", TEST_INSTRUCTIONS)


class AcceptanceSpecs(unittest.TestCase):
    def test_acceptance_waits_are_bounded(self):
        self.assertIn("5-8 second timeout", ACCEPTANCE)
        self.assertIn("test timeout", ACCEPTANCE)


if __name__ == "__main__":
    unittest.main()
