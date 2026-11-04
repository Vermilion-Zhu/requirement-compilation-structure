"""Minimal visual model client using the existing model environment variables."""

from __future__ import annotations

import base64
import json
from io import BytesIO
import mimetypes
from pathlib import Path

from openai import OpenAI, OpenAIError
from PIL import Image, ImageOps

from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.models.configuration import (
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TRANSPORT_RETRIES,
    base_url,
    first_credential,
    load_environment,
    model_identifier,
    reasoning_mode,
)
from infrastructure.shared.models.text import (
    JSON_OUTPUT_RULE,
    PROMPT_ONLY_RULE,
    parse_json_object,
    reasoning_arguments,
    reasoning_rejected,
    response_format_unavailable,
)
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.model_io import http_client, invoke


VISION_INSTRUCTIONS = """Describe the supplied UI reference using visible evidence only.
Return {"layout":"...", "elements":["..."], "style":"..."}.
layout describes regions, alignment and relative positions; elements lists visible
controls, labels, options and states; style describes colors, typography and spacing.
Write descriptions in English while quoting visible labels in their original language.
Identify illegible or uncertain details instead of inventing them. Do not infer hidden
business behavior, APIs, database fields or interactions from appearance alone.
"""

VISUAL_REPAIR_PREFIX = "Correct the previous response:\n"


def compress_image(data: bytes, mime: str) -> tuple[bytes, str]:
    """Resize static references to 2048px and encode JPEG, retaining smaller originals."""
    with Image.open(BytesIO(data)) as source:
        if getattr(source, "is_animated", False):
            return data, mime
        image = ImageOps.exif_transpose(source)
        original_size = image.size
        image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        # Composite transparency against white so transparent UI text stays readable.
        rgba = image.convert("RGBA")
        rgb = Image.new("RGB", rgba.size, "white")
        rgb.paste(rgba, mask=rgba.getchannel("A"))
        buffer = BytesIO()
        rgb.save(buffer, format="JPEG", quality=85, subsampling=0)
        compressed = buffer.getvalue()
        if len(compressed) < len(data) or image.size != original_size:
            return compressed, "image/jpeg"
    return data, mime


class VisualModel:
    """Extract visible image evidence without inferring hidden business behavior."""
    def __init__(self) -> None:
        """Read the run environment and configure the image-capable model.

        Visual settings fall back to the main model settings, and a local ``.env``
        is read only when ARC-Bench did not inject its own connection.
        """
        load_environment(Path(__file__).resolve().parents[3] / ".env")
        self.name = model_identifier("VISUAL_MODEL", "MODEL")
        api_key = first_credential("VISUAL_API_KEY", "OPENAI_API_KEY")
        if not api_key:
            raise ValueError("Set OPENAI_API_KEY, which ARC-Bench injects; the model must accept images")
        self.reasoning = reasoning_mode("VISUAL_REASONING", "MODEL_REASONING")
        self._reasoning_supported = True
        self._response_format = "json_object"
        self.client = OpenAI(api_key=api_key,
            base_url=base_url("VISUAL_BASE_URL", "OPENAI_BASE_URL"),
            timeout=DEFAULT_TIMEOUT_SECONDS, max_retries=DEFAULT_TRANSPORT_RETRIES,
            http_client=http_client())

    def analyze(self, image: Path, max_attempts: int = 10) -> dict:
        """Send one supported reference image and parse the returned layout, elements, and style evidence."""
        mime = mimetypes.guess_type(image.name)[0]
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ValueError(f"Unsupported image format: {image.name}")
        original = image.read_bytes()
        compressed, mime = compress_image(original, mime)
        print(f"Image compression: {image.name} | {len(original) / 1024:.1f} -> {len(compressed) / 1024:.1f} KiB", flush=True)
        encoded = base64.b64encode(compressed).decode("ascii")
        result, _ = propose_json(self, VISION_INSTRUCTIONS, {"image_url": f"data:{mime};base64,{encoded}"},
            lambda value: value, DemoConsole(), f"Visual analysis {image.name}", max_attempts)
        return result

    def _protocol_text(self, instructions: str, payload: dict) -> str:
        """Compose the prompt with the JSON rule matching the negotiated format."""
        text = instructions.rstrip() + "\n" + JSON_OUTPUT_RULE
        if getattr(self, "_response_format", "json_object") != "json_object":
            text += PROMPT_ONLY_RULE
        if "correction" in payload:
            text += "\n" + VISUAL_REPAIR_PREFIX + json.dumps(payload["correction"], ensure_ascii=False)
        return text

    def generate_json(self, instructions: str, payload: dict) -> dict:
        """Request visual JSON and include prior response errors when repairing it."""
        mode = getattr(self, "reasoning", "low")
        while True:
            options = {
                "model": self.name,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": self._protocol_text(instructions, payload)},
                    {"type": "image_url", "image_url": {"url": payload["image_url"], "detail": "high"}},
                ]}],
            }
            if getattr(self, "_response_format", "json_object") == "json_object":
                options["response_format"] = {"type": "json_object"}
            if getattr(self, "_reasoning_supported", True):
                options.update(reasoning_arguments(self.name, mode))
            try:
                response = invoke(self.client, options)
                break
            except OpenAIError as error:
                if (getattr(self, "_response_format", "json_object") == "json_object"
                        and response_format_unavailable(error)):
                    self._response_format = "prompt_only"
                    print("Provider rejected response_format=json_object; "
                        "requesting JSON through the prompt only.", flush=True)
                    continue
                if getattr(self, "_reasoning_supported", True) and reasoning_rejected(error):
                    self._reasoning_supported = False
                    print("Provider rejected reasoning controls; using provider defaults.", flush=True)
                    continue
                raise RuntimeError(f"Visual model request failed: {error}") from error
        if not response.choices or not response.choices[0].message.content:
            raise ValueError("Visual model returned empty content")
        return parse_json_object(response.choices[0].message.content)
