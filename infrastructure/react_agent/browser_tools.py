"""Prepare the independent browser runner when the platform only supplies the agent."""

from pathlib import Path
import shutil
from time import monotonic

from infrastructure.utils.files import save_json
from infrastructure.utils.processes import capture_process, npm_command


def prepare_browser(directory: Path, timeout: float, *, channel=None) -> tuple[Path, str | None]:
    """Install the locally validated test-runner version outside generated application files."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    deadline = monotonic()+timeout
    environment = {"OPENAI_API_KEY": "", "VISUAL_API_KEY": "", "DEEPSEEK_API_KEY": ""}
    commands = [[*npm_command(), "install", "--prefix", str(directory), "@playwright/test@1.55.0",
                 "--include=dev", "--no-audit", "--no-fund"]]
    cli = directory / "node_modules/@playwright/test/cli.js"
    chrome = any(path.is_file() for path in (
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"))) or bool(shutil.which("google-chrome"))
    selected = channel or ("chrome" if chrome else None)
    if selected is None:
        commands.append(["node", str(cli), "install", "chromium"])
    records = []
    for command in commands:
        remaining = deadline-monotonic()
        if remaining <= 0:
            raise TimeoutError("Time budget exhausted while preparing the browser runner")
        result = capture_process(command, cwd=directory, timeout=min(remaining, 120), env=environment)
        records.append({"argv": command, **result})
        save_json(directory / "bootstrap.json", {"commands": records, "channel": selected})
        if result["returncode"]:
            raise RuntimeError("Browser runner preparation failed: " + result["output"][-6000:])
    if not cli.is_file():
        raise RuntimeError("Browser runner installation did not publish its CLI")
    return cli, selected
