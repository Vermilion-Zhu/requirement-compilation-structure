"""Best-effort ARC-Bench visualization events and traceability snapshots.

The platform reads ``ARCBENCH_RUNNER_EVENTS_PATH`` (JSONL) and
``ARCBENCH_TRACEABILITY_DIR`` (per-table JSON) to draw per-requirement progress and
commit history. Both are optional: a local run, a missing SDK or a read-only
artifact directory must never fail the compilation, so every call here degrades to
a no-op and warns at most once.
"""

from __future__ import annotations

import sys
import json
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


def _store():
    """Return the traceability store when events are live."""
    return _RUNTIME.traceability if enabled() else None


def interface(interface_id: str, *, req_ids, kind: str, content: str,
        file_path: str | None = None, callers=(), callees=()) -> None:
    """Publish one API, page or trigger contract for the traceability graph."""
    store = _store()
    if store is None or not str(interface_id or "").strip():
        return
    try:
        store.upsert_interface(interface_id=interface_id, req_ids=list(req_ids),
            type={"page": "ui", "trigger": "func"}.get(kind, kind),
            content=content, file_path=file_path, implemented=False,
            callers=list(callers), callees=list(callees))
    except Exception as error:
        _warn(f"traceability interface failed: {type(error).__name__}: {error}")


def interface_implemented(interface_id: str, file_path: str | None = None,
        message: str | None = None) -> None:
    """Mark a published contract as implemented, optionally recording its file."""
    store = _store()
    if store is None:
        return
    try:
        if store.get_interface(interface_id) is None:
            return
        fields = {"implemented": True}
        if file_path:
            fields["file_path"] = file_path
        store.update_interface_fields(interface_id, **fields)
    except Exception as error:
        _warn(f"traceability interface status failed: {type(error).__name__}: {error}")


def link(interface_id: str, *, callers=(), callees=()) -> None:
    """Merge caller/callee relationships without dropping the rest of a contract row."""
    store = _store()
    if store is None:
        return
    try:
        current = store.get_interface(interface_id)
        if current is None:
            return
        def merged(key, additions):
            return sorted(set(current.get(key) or []) | {str(item) for item in additions if str(item)})
        store.upsert_interface(interface_id=interface_id, req_ids=current.get("req_ids") or [],
            type=current.get("type") or "", content=current.get("content") or "",
            file_path=current.get("file_path"), first_line=current.get("first_line"),
            implemented=bool(current.get("implemented")),
            callers=merged("callers", callers), callees=merged("callees", callees), emit_event=False)
    except Exception as error:
        _warn(f"traceability link failed: {type(error).__name__}: {error}")


def test_case(test_id: str, *, requirement_id: str, kind: str, file_path: str | None = None,
        passed: bool | None = None, scenario_id: str | None = None, interface_ids=()) -> None:
    """Publish one generated test case and its current pass status."""
    store = _store()
    if store is None or not str(test_id or "").strip() or not str(requirement_id or "").strip():
        return
    try:
        # Publish test levels understood by the graph, preserving semantic test IDs.
        level = {"api": "integration", "ui": "unit", "acceptance": "e2e"}.get(kind, kind)
        store.upsert_test(test_id=test_id, req_id=requirement_id, type=level, file_path=file_path,
            passed=passed, scenario_id=scenario_id, interface_ids=list(interface_ids))
    except Exception as error:
        _warn(f"traceability test failed: {type(error).__name__}: {error}")


def test_passed(test_id: str, passed: bool) -> None:
    """Update one published test's status after a re-run."""
    store = _store()
    if store is None:
        return
    try:
        if store.get_test(test_id) is not None:
            store.set_test_pass_status(test_id, passed)
    except Exception as error:
        _warn(f"traceability test status failed: {type(error).__name__}: {error}")


def commit(revision: str, message: str | None = None) -> None:
    """Ask the website to refresh its commit history after a checkpoint."""
    _emit_events("notify_commit_history_changed", message or f"checkpoint {revision[:8]}")


def database_schema(schema: dict) -> None:
    """Project accepted table definitions and their requirement ownership into DB nodes."""
    if not enabled():
        return
    for name, entity in schema.get("entities", {}).items():
        owners = [rid for rid, fields in schema.get("requirements", {}).items()
                  if any(field.split(".", 1)[0] == name for field in fields)]
        interface("DB-" + name, req_ids=owners, kind="db",
            content=json.dumps(entity, ensure_ascii=False),
            file_path=f"backend/src/db/tables/{name}.sql")
