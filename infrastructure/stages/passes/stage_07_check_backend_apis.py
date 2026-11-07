"""Step 07: display complete backend API definitions and requirement associations."""

import json
from pathlib import Path

from infrastructure.utils.files import read_artifact
from infrastructure.utils.presentation.console import DemoConsole


def check_backend_apis(arc_dir: Path, pause: bool = False) -> dict:
    """Read and print the API artifact without changing it or validating its design."""
    design = read_artifact(arc_dir, "backend_apis.json")
    DemoConsole(pause).show("Step 07 | Backend API design", json.dumps(design, ensure_ascii=False, indent=2))
    return design
