"""Pre-submission semantic probe: requirements and the accepted design against the built app.

Usage:
  uv run python scripts/preflight.py --app output/demo
  uv run python scripts/preflight.py --app output/demo --json preflight.json --strict
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.shared.project.preflight import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
