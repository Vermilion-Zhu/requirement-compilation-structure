"""Best-effort ARC-Bench visualization events and traceability snapshots.

The platform reads ``ARCBENCH_RUNNER_EVENTS_PATH`` (JSONL) and
``ARCBENCH_TRACEABILITY_DIR`` (per-table JSON) to draw per-requirement progress and
commit history. Both are optional: a local run, a missing SDK or a read-only
artifact directory must never fail the compilation, so every call here degrades to
a no-op and warns at most once.
"""

from __future__ import annotations

import sys
from pathlib import Path

from infrastructure.shared.project.runtime_sdk import load_agent_runtime


_RUNTIME = None
_ENABLED = False
_WARNED = False


def _warn(message: str) -> None:
    """Report the first disabled-state reason without flooding the pass logs."""
    global _WARNED
    if _WARNED:
        return
    _WARNED = True
    print(f"[RUNTIME] {message}", flush=True)


def initialize(project_dir) -> bool:
    """Attach the ARC-Bench runtime to one application root; report whether it is live."""
    global _RUNTIME, _ENABLED
    if _RUNTIME is not None:
        return _ENABLED
    AgentRuntime = load_agent_runtime()
    if AgentRuntime is None:
        _warn("arcbench-agent-runtime is not installed; visualization events stay disabled")
        return False
    try:
        runtime = AgentRuntime.from_env(project_dir=str(project_dir))
        runtime.traceability.init_store()
    except Exception as error:  # A broken artifact directory must not stop compilation.
        _warn(f"visualization events disabled: {type(error).__name__}: {error}")
        _RUNTIME, _ENABLED = None, False
        return False
    _RUNTIME, _ENABLED = runtime, True
    return _ENABLED


def enabled() -> bool:
    """Report whether events are being recorded for this run."""
    return _ENABLED and _RUNTIME is not None


def _emit(method: str, *arguments, **options) -> None:
    """Call one runtime method when it is available; never propagate failures."""
    if not enabled():
        return
    try:
        getattr(_RUNTIME, method)(*arguments, **options)
    except Exception as error:
        _warn(f"{method} failed: {type(error).__name__}: {error}")


def _emit_events(method: str, *arguments, **options) -> None:
    """Call one event-client method when it is available; never propagate failures."""
    if not enabled():
        return
    try:
        getattr(_RUNTIME.events, method)(*arguments, **options)
    except Exception as error:
        _warn(f"events.{method} failed: {type(error).__name__}: {error}")


def start(message: str | None = None) -> None:
    """Mark the run as started."""
    _emit_events("mark_run_started", message)


def finish(ok: bool, message: str | None = None) -> None:
    """Mark the run as completed or failed."""
    _emit_events("mark_run_completed" if ok else "mark_run_failed", message)


def store_requirement_tree(tree: dict) -> None:
    """Publish the requirement/scenario tables the website renders."""
    if not enabled() or not isinstance(tree, dict):
        return
    try:
        _RUNTIME.traceability.store_requirement_tree(tree)
    except Exception as error:
        _warn(f"traceability requirement tree failed: {type(error).__name__}: {error}")


def design_started(requirement_id: str) -> None:
    _emit_events("mark_design_started", requirement_id)


def design_done(requirement_id: str) -> None:
    _emit_events("mark_design_done", requirement_id)


def design_failed(requirement_id: str, message: str | None = None) -> None:
    _emit_events("mark_design_failed", requirement_id, message)


def implementation_started(requirement_id: str) -> None:
    _emit_events("mark_implementation_started", requirement_id)


def implementation_done(requirement_id: str) -> None:
    _emit_events("mark_implementation_done", requirement_id)


def implementation_failed(requirement_id: str, message: str | None = None) -> None:
    _emit_events("mark_implementation_failed", requirement_id, message)


def test_result(requirement_id: str, passed: bool, message: str | None = None) -> None:
    """Record one requirement's acceptance outcome."""
    _emit_events("mark_test_passed" if passed else "mark_test_failed", requirement_id, message)


def commit(revision: str, message: str | None = None) -> None:
    """Ask the website to refresh its commit history after a checkpoint."""
    _emit_events("notify_commit_history_changed", message or f"checkpoint {revision[:8]}")
