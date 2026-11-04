"""Import the vendored ARC-Bench agent runtime, installed or from the bundle.

``requirements.txt`` installs ``./arcbench-agent-runtime``, so a platform run
imports an installed package. A local checkout without that install still works:
the bundle's ``src`` directory is added to ``sys.path`` on first use.
"""

from __future__ import annotations

from pathlib import Path
import sys


BUNDLE = Path(__file__).resolve().parents[3] / "arcbench-agent-runtime"


def load_agent_runtime():
    """Return ``arcbench_agent_runtime.AgentRuntime`` or ``None`` when unavailable."""
    try:
        from arcbench_agent_runtime import AgentRuntime
    except ImportError:
        source = BUNDLE / "src"
        if not source.is_dir():
            return None
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        try:
            from arcbench_agent_runtime import AgentRuntime
        except ImportError:
            return None
    return AgentRuntime
