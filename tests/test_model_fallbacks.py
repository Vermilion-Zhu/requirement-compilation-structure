"""Model requests must survive the ARC-Bench proxy without inventing limits.

Two failures here cost every pass at once: an output-token budget the endpoint
rejects, and a ``response_format`` the endpoint does not implement. Both must be
optional and degradable, and the JSON parser must accept the object a degraded
provider returns.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openai import OpenAIError

from infrastructure.shared.models.configuration import (
    DEFAULT_MODEL,
    load_environment,
    model_identifier,
    optional_token_budget,
    reasoning_mode,
)
from infrastructure.shared.models.text import (
    PROMPT_ONLY_RULE,
    TextModel,
    parse_json_object,
    response_format_unavailable,
)


class Rejected(OpenAIError):
    """A provider rejection carrying the HTTP status and body used for detection."""

    def __init__(self, message: str, status_code: int = 400, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def bare_model(**attributes) -> TextModel:
    """Build a client-free TextModel so request composition can be asserted."""
    model = TextModel.__new__(TextModel)
    model.name = "test-model"
    model.max_output_tokens = None
    model.reasoning = "provider"
    model._reasoning_supported = True
    model.json_mode = True
    model._response_format = "json_object"
    model._token_parameter = "max_completion_tokens"
    model.client = None
    for key, value in attributes.items():
        setattr(model, key, value)
    return model


def response(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(content=content, refusal=None))])


class OutputBudget(unittest.TestCase):
    def test_absent_budget_lets_the_provider_decide(self):
        with patch.dict(os.environ, {"MAX_OUTPUT_TOKENS": ""}):
            self.assertIsNone(optional_token_budget())

    def test_explicit_budget_is_kept(self):
        with patch.dict(os.environ, {"MAX_OUTPUT_TOKENS": "4096"}):
            self.assertEqual(optional_token_budget(), 4096)

    def test_invalid_budget_is_rejected_instead_of_sent(self):
        for value in ("0", "-1", "many"):
            with self.subTest(value=value), patch.dict(os.environ, {"MAX_OUTPUT_TOKENS": value}):
                with self.assertRaises(ValueError):
                    optional_token_budget()

    def test_no_token_field_is_sent_without_a_configured_budget(self):
        captured = {}

        def fake_invoke(client, arguments):
            captured.update(arguments)
            return response('{"ok": true}')

        model = bare_model()
        with patch("infrastructure.shared.models.text.invoke", side_effect=fake_invoke):
            self.assertEqual(model.generate_json("Design", {}), {"ok": True})
        self.assertNotIn("max_completion_tokens", captured)
        self.assertNotIn("max_tokens", captured)

    def test_a_configured_budget_is_sent(self):
        captured = {}

        def fake_invoke(client, arguments):
            captured.update(arguments)
            return response('{"ok": true}')

        model = bare_model(max_output_tokens=2048)
        with patch("infrastructure.shared.models.text.invoke", side_effect=fake_invoke):
            model.generate_json("Design", {})
        self.assertEqual(captured["max_completion_tokens"], 2048)


class ResponseFormatFallback(unittest.TestCase):
    def test_rejection_is_recognized_only_for_format_errors(self):
        self.assertTrue(response_format_unavailable(
            Rejected("Unsupported parameter: response_format", body={"error": {"message": "response_format unsupported"}})))
        self.assertFalse(response_format_unavailable(Rejected("rate limited")))
        self.assertFalse(response_format_unavailable(Rejected("response_format unsupported", status_code=429)))

    def test_json_object_mode_degrades_to_prompt_only_and_retries(self):
        calls = []

        def fake_invoke(client, arguments):
            calls.append(arguments)
            if len(calls) == 1:
                raise Rejected("Unsupported value: response_format",
                    body={"error": {"message": "response_format is not supported"}})
            return response('{"ok": true}')

        model = bare_model()
        with patch("infrastructure.shared.models.text.invoke", side_effect=fake_invoke):
            self.assertEqual(model.generate_json("Design", {}), {"ok": True})
        self.assertEqual(len(calls), 2)
        self.assertIn("response_format", calls[0])
        self.assertNotIn("response_format", calls[1])
        self.assertIn(PROMPT_ONLY_RULE.splitlines()[0], calls[1]["messages"][0]["content"])
        self.assertEqual(model._response_format, "prompt_only")

    def test_unrelated_provider_errors_are_not_hidden(self):
        def fake_invoke(client, arguments):
            raise Rejected("invalid api key", status_code=401)

        model = bare_model()
        with patch("infrastructure.shared.models.text.invoke", side_effect=fake_invoke):
            with self.assertRaises(RuntimeError):
                model.generate_json("Design", {})


class JsonParsing(unittest.TestCase):
    def test_plain_and_fenced_objects_are_both_accepted(self):
        self.assertEqual(parse_json_object('{"ok": true}'), {"ok": True})
        self.assertEqual(parse_json_object('\ufeff```json\n{"ok": true}\n```'), {"ok": True})

    def test_non_objects_and_prose_are_rejected(self):
        for value in ("[1, 2]", "Here you go: {}", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_json_object(value)


class ConnectionSettings(unittest.TestCase):
    def test_model_name_falls_back_to_the_documented_default(self):
        with patch.dict(os.environ, {"MODEL": ""}):
            self.assertEqual(model_identifier("MODEL"), DEFAULT_MODEL)
        with patch.dict(os.environ, {"MODEL": "custom-model"}):
            self.assertEqual(model_identifier("MODEL"), "custom-model")

    def test_visual_settings_fall_back_to_the_main_model(self):
        with patch.dict(os.environ, {"VISUAL_MODEL": "", "MODEL": "main-model"}):
            self.assertEqual(model_identifier("VISUAL_MODEL", "MODEL"), "main-model")

    def test_platform_run_never_reads_a_local_dotenv(self):
        with TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env"
            env_file.write_text("OPENAI_API_KEY=local-secret\nMODEL=local-model\n")
            with patch.dict(os.environ, {"ARCBENCH_OUTPUT_DIR": temporary, "OPENAI_API_KEY": ""}):
                self.assertFalse(load_environment(env_file))
                self.assertEqual(os.environ["OPENAI_API_KEY"], "")

    def test_local_run_reads_the_dotenv_without_overriding_injected_values(self):
        with TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env"
            env_file.write_text("ARC_TEST_ONLY_KEY=local\nARC_TEST_ONLY_KEPT=local\n")
            try:
                with patch.dict(os.environ, {"ARC_TEST_ONLY_KEPT": "injected"}, clear=False):
                    for name in ("ARCBENCH_OUTPUT_DIR", "ARCBENCH_SUBMISSION_DIR",
                            "ARCBENCH_TASK_DIR", "ARCBENCH_RUNNER_EVENTS_PATH", "ARC_TEST_ONLY_KEY"):
                        os.environ.pop(name, None)
                    self.assertTrue(load_environment(env_file))
                    self.assertEqual(os.environ["ARC_TEST_ONLY_KEY"], "local")
                    self.assertEqual(os.environ["ARC_TEST_ONLY_KEPT"], "injected")
            finally:
                os.environ.pop("ARC_TEST_ONLY_KEY", None)
                os.environ.pop("ARC_TEST_ONLY_KEPT", None)

    def test_reasoning_mode_accepts_documented_values_only(self):
        with patch.dict(os.environ, {"MODEL_REASONING": "provider"}):
            self.assertEqual(reasoning_mode("MODEL_REASONING"), "provider")
        with patch.dict(os.environ, {"MODEL_REASONING": "loud"}):
            with self.assertRaises(ValueError):
                reasoning_mode("MODEL_REASONING")


if __name__ == "__main__":
    unittest.main()
