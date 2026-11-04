"""Model connection settings shared by the text and visual clients.

ARC-Bench injects ``OPENAI_BASE_URL`` and ``OPENAI_API_KEY`` for every run and may
inject ``MODEL``. The course guide only asks for a base URL and a key ("无需填写模型
名"), so a model identifier is optional and a documented default is used when the
runner does not provide one. A local ``.env`` is loaded only for local runs: the
platform's injected values must never be shadowed by a developer file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# Used when neither the runner nor the developer selects a model explicitly.
DEFAULT_MODEL = "deepseek-flash"

# Any of these means ARC-Bench is running this process.
PLATFORM_MARKERS = (
    "ARCBENCH_OUTPUT_DIR",
    "ARCBENCH_SUBMISSION_DIR",
    "ARCBENCH_TASK_DIR",
    "ARCBENCH_RUNNER_EVENTS_PATH",
)

DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_TRANSPORT_RETRIES = 2


def is_platform_run() -> bool:
    """Report whether ARC-Bench injected its own run environment."""
    return any(os.environ.get(name, "").strip() for name in PLATFORM_MARKERS)


def load_environment(env_file: Path) -> bool:
    """Load a developer ``.env`` for local runs only; return whether one was read.

    Existing environment variables always win (``override=False``), and no file is
    read at all under ARC-Bench, where the injected credentials are authoritative.
    """
    if is_platform_run() or not env_file.is_file():
        return False
    load_dotenv(env_file, encoding="utf-8-sig", override=False)
    return True


def model_identifier(*names: str) -> str:
    """Return the first configured model name, falling back to the documented default."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return DEFAULT_MODEL


def first_credential(*names: str) -> str | None:
    """Return the first non-empty credential without echoing it anywhere."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def base_url(*names: str) -> str:
    """Return the first configured base URL, defaulting to the public OpenAI endpoint."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return "https://api.openai.com/v1"


def optional_token_budget(name: str = "MAX_OUTPUT_TOKENS") -> int | None:
    """Return an explicit output budget, or ``None`` to let the provider decide.

    Sending a large ``max_completion_tokens`` unconditionally is rejected by most
    endpoints, which fails every pass, so the field is omitted unless a developer
    sets it deliberately.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def reasoning_mode(*names: str) -> str:
    """Read one reasoning mode from the first configured variable."""
    allowed = {"auto", "provider", "none", "low", "high", "max"}
    for name in names:
        value = os.environ.get(name, "").strip().lower()
        if value:
            if value not in allowed:
                raise ValueError(f"{name} must be one of {', '.join(sorted(allowed))}")
            return value
    return "low"
