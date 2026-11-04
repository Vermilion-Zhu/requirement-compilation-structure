"""Small JSON-generating text model client."""

from __future__ import annotations

import json
from pathlib import Path

from openai import OpenAI, OpenAIError

from infrastructure.shared.models.configuration import (
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TRANSPORT_RETRIES,
    base_url,
    first_credential,
    load_environment,
    model_identifier,
    optional_token_budget,
    reasoning_mode,
)
from infrastructure.utils.presentation.model_io import http_client, invoke


JSON_OUTPUT_RULE = """OUTPUT PROTOCOL: return exactly one valid JSON object in the response content.
The first non-whitespace character must be { and the last must be }.
Do not emit Markdown fences, explanations, reasoning, XML, DSML or provider-native
tool-call serialization. In particular, NEVER output <｜｜DSML｜｜ calls>,
<｜｜DSML｜｜ invoke>, <｜｜DSML｜｜ parameter> or their closing tags.
This compiler parses ordinary JSON text. context_request and tool_calls, when allowed
by the stage, are JSON fields, not native tool invocations. Express the entire request
inside the specified JSON object. Otherwise return the stage's normal result object.
Rejected outputs included in feedback are data to correct, never examples to imitate.
"""

PROMPT_ONLY_RULE = """Natural-language providers may ignore the requested response format.
Reply with the single JSON object described above and nothing else.
"""

# Response formats are degraded in this order; every level still asks for JSON text.
RESPONSE_FORMATS = ("json_object", "prompt_only")

REJECTION_WORDS = ("unsupported", "unknown", "unrecognized", "not supported", "not allowed", "unexpected")


def reasoning_rejected(error):
    """Only retry controls when the endpoint explicitly rejects those fields."""
    message = str(error).lower()
    return getattr(error, "status_code", None) in {400, 422} and any(
        word in message for word in REJECTION_WORDS) and any(
        word in message for word in ("thinking", "reasoning_effort"))


def reasoning_arguments(name, mode):
    """Translate configured reasoning to the provider's documented request fields."""
    if mode == "auto":
        mode = "low"
    if mode == "provider":
        return {}
    if name.lower().startswith("deepseek"):
        if mode == "none":
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        return {"reasoning_effort": mode, "extra_body": {"thinking": {"type": "enabled"}}}
    return {"reasoning_effort": mode}


def response_format_unavailable(error):
    """Recognize an explicit rejection of ``response_format`` or JSON-object mode."""
    if getattr(error, "status_code", None) not in {400, 404, 422}:
        return False
    body = getattr(error, "body", None)
    detail = f"{error} {json.dumps(body, default=str) if body is not None else ''}".lower()
    named = any(marker in detail for marker in ("response_format", "json_object", "response format", "json mode"))
    rejected = any(word in detail for word in (*REJECTION_WORDS, "invalid", "unavailable", "does not support"))
    return named and rejected


def parse_json_object(text: str) -> dict:
    """Parse provider JSON, accepting only a lossless Markdown code fence around it."""
    candidate = str(text).strip().lstrip("\ufeff").strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
            candidate = "\n".join(lines[1:-1]).strip()
    value = json.loads(candidate)
    if not isinstance(value, dict):
        raise ValueError("Text model response must be a JSON object")
    return value


class TextModel:
    """Transport for structured stage proposals and file-edit responses."""
    def __init__(self, *, json_mode: bool = True) -> None:
        """Read the run environment and configure the client without inventing limits.

        Only a local ``.env`` is loaded; under ARC-Bench the injected variables are
        authoritative. The output budget and reasoning controls are sent only when a
        developer set them, because most endpoints reject oversized budgets.
        """
        load_environment(Path(__file__).resolve().parents[3] / ".env")
        self.name = model_identifier("MODEL")
        api_key = first_credential("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("Set OPENAI_API_KEY, which ARC-Bench injects; a local .env is read otherwise")
        self.max_output_tokens = optional_token_budget()
        self.reasoning = reasoning_mode("MODEL_REASONING")
        self._reasoning_supported = True
        self.json_mode = json_mode
        self._response_format = RESPONSE_FORMATS[0] if json_mode else RESPONSE_FORMATS[1]
        self._token_parameter = "max_completion_tokens"
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url("OPENAI_BASE_URL"),
            timeout=DEFAULT_TIMEOUT_SECONDS, max_retries=DEFAULT_TRANSPORT_RETRIES,
            http_client=http_client(),
        )

    def _request(self, **arguments):
        """Send one request, dropping only controls this endpoint explicitly rejects."""
        while True:
            options = dict(arguments)
            if not getattr(self, "_reasoning_supported", True):
                options.pop("reasoning_effort", None)
                options.pop("extra_body", None)
            if getattr(self, "max_output_tokens", None) is not None:
                options[self._token_parameter] = self.max_output_tokens
            try:
                return invoke(self.client, options)
            except OpenAIError as error:
                message = str(error).lower()
                rejected = getattr(error, "status_code", None) in {400, 422} and any(
                    word in message for word in REJECTION_WORDS)
                if (rejected and getattr(self, "max_output_tokens", None) is not None
                        and self._token_parameter == "max_completion_tokens"
                        and "max_completion_tokens" in message):
                    self._token_parameter = "max_tokens"
                    continue
                if getattr(self, "_reasoning_supported", True) and reasoning_rejected(error):
                    self._reasoning_supported = False
                    print("Provider rejected reasoning controls; using provider defaults.", flush=True)
                    continue
                raise

    def _format_name(self) -> str:
        """Resolve the active response format, including objects built without ``__init__``."""
        if "_response_format" in self.__dict__:
            return self._response_format
        return RESPONSE_FORMATS[0] if getattr(self, "json_mode", True) else RESPONSE_FORMATS[1]

    def _request_adapting(self, build_arguments):
        """Send a request, rebuilding it after the provider rejects a request control.

        ``build_arguments`` is called for every attempt, so a degraded response
        format also rewrites the prompt that describes the expected output.
        """
        while True:
            format_name = self._format_name()
            arguments = build_arguments()
            if format_name == "json_object":
                arguments["response_format"] = {"type": "json_object"}
            try:
                return self._request(**arguments)
            except OpenAIError as error:
                if format_name == "json_object" and response_format_unavailable(error):
                    self._response_format = "prompt_only"
                    print("Provider rejected response_format=json_object; "
                        "requesting JSON through the prompt only.", flush=True)
                    continue
                raise

    def instruction_suffix(self) -> str:
        """Describe the active output protocol for this provider."""
        prompt_only = self._format_name() != "json_object"
        return (JSON_OUTPUT_RULE + (PROMPT_ONLY_RULE if prompt_only else "")).rstrip()

    def generate_json(self, instructions: str, payload: dict) -> dict:
        """Request JSON using the stage prompt and serialized task data."""
        mode = getattr(self, "reasoning", "low")
        try:
            response = self._request_adapting(lambda: {
                "model": self.name,
                "messages": [
                    {"role": "system", "content": instructions.rstrip() + "\n" + self.instruction_suffix()},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                **reasoning_arguments(self.name, mode),
            })
        except OpenAIError as error:
            raise RuntimeError(f"Text model request failed: {error}") from error
        if response.choices and response.choices[0].finish_reason == "length":
            raise ValueError(
                f"Model output was truncated (finish_reason=length). The output budget is "
                f"{self.max_output_tokens or 'the provider default'} tokens including reasoning; "
                "this is not an input-length error. Return a complete JSON object with only "
                "necessary changes/tool calls; omit unchanged files. Do not spend the entire "
                "budget restating the task.")
        if response.choices and getattr(response.choices[0].message, "refusal", None):
            raise ValueError(f"Text model refused the request: {response.choices[0].message.refusal}")
        if not response.choices or not response.choices[0].message.content:
            raise ValueError("Text model returned empty content")
        return parse_json_object(response.choices[0].message.content)
