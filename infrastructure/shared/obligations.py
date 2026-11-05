"""One ledger for every dataflow obligation, assembled from the pass artifacts.

Before this module the read/write obligations lived in four places that each knew a
different half of the story:

* ``db_obligations.json`` (pass 03) knows which fields each requirement and step
  must read or write,
* ``backend_apis.json`` (pass 06) knows which APIs declare those fields,
* ``frontend_triggers.json`` (pass 11) knows which API call implements a step,
* ``backend_tdd.json`` / ``frontend_e2e.json`` / ``independent_acceptance.json``
  know whether the implementing code was actually accepted.

The ledger joins them into ``.arc/obligations.json`` and derives a lifecycle from
the evidence instead of trusting a declaration:

    Inferred -> Allocated -> Verified -> Implemented

* ``Inferred``: pass 03 declared the field for a requirement or step.
* ``Allocated``: some API (for a requirement) or some trigger-routed API (for a
  step) declares the field in its own read/write set.
* ``Verified``: every allocating API belongs to a requirement whose backend
  acceptance is GREEN, with the backend test path as evidence.
* ``Implemented``: additionally the requirement's independent acceptance (or its
  process E2E when no acceptance suite exists) is GREEN. A requirement with no
  frontend behaviour is ``Implemented`` as soon as it is ``Verified``.

Nothing here changes a gate, a prompt or a pass result: ``refresh()`` is a
read-only projection plus one artifact write, and every failure degrades to a
warning so the compilation keeps its previous behaviour.
"""

from hashlib import sha1
import json
from pathlib import Path

from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import save_json


LEDGER = "obligations.json"
KIND_READ = "DB_READ"
KIND_WRITE = "DB_WRITE"
STATUSES = ("Inferred", "Allocated", "Verified", "Implemented")
GREEN = "GREEN"


def _load(arc_dir: Path, name: str) -> dict:
    """Read one optional artifact, treating a missing or malformed file as absent."""
    path = arc_dir / name
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _fields(record) -> list[str]:
    """Return the field list of one read/write record, ignoring malformed entries."""
    if not isinstance(record, list):
        return []
    return sorted({str(field) for field in record if isinstance(field, str) and field})


def obligation_id(origin: str, kind: str, field: str) -> str:
    """Build a stable identifier so reruns produce the same ledger rows."""
    return "OBL-" + sha1(f"{origin}|{kind}|{field}".encode("utf-8")).hexdigest()[:8]


def _evidence_test_paths(artifacts: dict, requirement_id: str) -> list[str]:
    """Collect backend and acceptance test paths that accepted this requirement."""
    paths = []
    tests = artifacts.get("backend_tdd", {}).get("tests", {})
    for api_id, path in sorted((tests.get(requirement_id) or {}).items()):
        if isinstance(path, str) and path:
            paths.append(path)
    for name in ("independent_acceptance", "frontend_e2e"):
        entry = (artifacts.get(name, {}).get("requirements") or {}).get(requirement_id) or {}
        for key in ("test_path", "tests"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                paths.append(value)
            elif isinstance(value, list):
                paths.extend(item for item in value if isinstance(item, str) and item)
            elif isinstance(value, dict):
                paths.extend(item for item in value.values() if isinstance(item, str) and item)
    return list(dict.fromkeys(paths))


def _requirement_status(artifacts: dict, requirement_id: str) -> tuple[bool, bool, bool]:
    """Report (backend_green, frontend_green, frontend_required) for one requirement."""
    backend = (artifacts.get("backend_tdd", {}).get("requirements") or {}).get(requirement_id) or {}
    backend_green = backend.get("status") == GREEN

    acceptance = ((artifacts.get("independent_acceptance", {}).get("requirements") or {})
        .get(requirement_id))
    process = ((artifacts.get("frontend_e2e", {}).get("requirements") or {})
        .get(requirement_id))
    frontend_required = acceptance is not None or process is not None
    frontend_green = bool(
        (acceptance and acceptance.get("status") == GREEN)
        or (process and process.get("status") in {GREEN, "NO_TRIGGERS", "NO_DIRECT_TRIGGERS"}))
    return backend_green, frontend_green, frontend_required


def _step_owners(tree_document: dict) -> dict[str, str]:
    """Map every step id to its owning requirement using the canonical tree."""
    if not tree_document:
        return {}
    try:
        tree = RequirementTree(tree_document)
    except (ValueError, KeyError, TypeError):
        return {}
    return {step_id: rid for rid, steps in tree.own_steps.items() for step_id in steps}


def _api_index(api_design: dict) -> dict[str, set[str]]:
    """Map every API id to the fields it declares it reads or writes."""
    index = {}
    for api_id, api in (api_design.get("apis") or {}).items():
        if not isinstance(api, dict):
            continue
        index[api_id] = set(_fields(api.get("read"))) | set(_fields(api.get("write")))
    return index


def _step_api_ids(interactions: dict) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    """Map steps to their triggers, triggers to called APIs, and steps to those APIs."""
    triggers = interactions.get("triggers") or {}
    trigger_apis = {}
    for trigger_id, trigger in triggers.items():
        apis = set()
        if isinstance(trigger, dict):
            for action in trigger.get("action") or []:
                if isinstance(action, dict) and isinstance(action.get("api"), str):
                    apis.add(action["api"])
        trigger_apis[trigger_id] = apis
    step_triggers, step_apis = {}, {}
    for step_id, trigger_ids in (interactions.get("steps") or {}).items():
        ids = {trigger_id for trigger_id in trigger_ids if isinstance(trigger_id, str)} \
            if isinstance(trigger_ids, list) else set()
        step_triggers[step_id] = ids
        step_apis[step_id] = set().union(*(trigger_apis.get(trigger_id, set()) for trigger_id in ids)) if ids else set()
    return step_apis, step_triggers, trigger_apis


def build(arc_dir: Path) -> dict:
    """Assemble the obligation ledger from the artifacts currently on disk."""
    arc_dir = Path(arc_dir)
    artifacts = {
        name: _load(arc_dir, name + ".json")
        for name in ("db_obligations", "backend_apis", "frontend_triggers",
            "backend_tdd", "frontend_e2e", "independent_acceptance")
    }
    obligations = artifacts["db_obligations"]
    step_owner = _step_owners(_load(arc_dir, "requirements.json"))
    api_fields = _api_index(artifacts["backend_apis"])
    requirement_apis = {
        rid: [api for api in apis if isinstance(api, str)]
        for rid, apis in (artifacts["backend_apis"].get("requirements") or {}).items()
        if isinstance(apis, list)
    }
    step_apis, step_triggers, trigger_apis = _step_api_ids(artifacts["frontend_triggers"])

    records = {}

    def add(origin: str, origin_kind: str, requirement: str, kind: str, field: str) -> None:
        identity = obligation_id(origin, kind, field)
        records[identity] = {
            "id": identity, "origin": origin, "origin_kind": origin_kind,
            "requirement": requirement, "kind": kind, "field": field,
            "allocated_to": [], "status": "Inferred", "evidence": [],
        }

    for requirement_id, record in (obligations.get("requirements") or {}).items():
        if not isinstance(record, dict):
            continue
        for field in _fields(record.get("read")):
            add(requirement_id, "requirement", requirement_id, KIND_READ, field)
        for field in _fields(record.get("write")):
            add(requirement_id, "requirement", requirement_id, KIND_WRITE, field)
    for step_id, record in (obligations.get("steps") or {}).items():
        if not isinstance(record, dict):
            continue
        requirement = step_owner.get(step_id, step_id)
        for field in _fields(record.get("read")):
            add(step_id, "step", requirement, KIND_READ, field)
        for field in _fields(record.get("write")):
            add(step_id, "step", requirement, KIND_WRITE, field)

    for record in records.values():
        requirement_id = record["requirement"]
        allocators = [{"type": "api", "id": api_id} for api_id in sorted(requirement_apis.get(requirement_id, []))
            if record["field"] in api_fields.get(api_id, set())]
        if record["origin_kind"] == "step":
            for trigger_id in sorted(step_triggers.get(record["origin"], set())):
                for api_id in sorted(step_apis.get(record["origin"], set())):
                    if api_id in trigger_apis.get(trigger_id, set()) and record["field"] in api_fields.get(api_id, set()):
                        allocators.append({"type": "trigger", "id": trigger_id})
        record["allocated_to"] = [{"type": kind, "id": identity} for kind, identity in sorted(
            {(item["type"], item["id"]) for item in allocators})]
        if not allocators:
            continue
        record["status"] = "Allocated"
        backend_green, frontend_green, frontend_required = _requirement_status(artifacts, requirement_id)
        if not backend_green:
            continue
        record["status"] = "Verified"
        record["evidence"] = _evidence_test_paths(artifacts, requirement_id)
        if not frontend_required or frontend_green:
            record["status"] = "Implemented"

    coverage = {}
    unresolved = []
    for record in records.values():
        entry = coverage.setdefault(record["requirement"], {
            "total": 0, "allocated": 0, "verified": 0, "implemented": 0, "missing": []})
        entry["total"] += 1
        index = STATUSES.index(record["status"])
        for name, position in (("allocated", 1), ("verified", 2), ("implemented", 3)):
            if index >= position:
                entry[name] += 1
        if record["status"] == "Inferred":
            entry["missing"].append(record["field"])
            unresolved.append(record["id"])
        elif record["status"] in {"Allocated", "Verified"}:
            unresolved.append(record["id"])
    for entry in coverage.values():
        entry["missing"] = sorted(set(entry["missing"]))
    totals = {name: sum(entry[name] for entry in coverage.values())
        for name in ("total", "allocated", "verified", "implemented")}
    return {
        "status": "BUILDING" if not records else "PARTIAL",
        "sources": {**{name: bool(value) for name, value in artifacts.items()},
            "requirements": bool(step_owner) or bool(obligations.get("requirements"))},
        "requirements": len(coverage),
        "totals": totals,
        "resolved": totals["implemented"] == totals["total"],
        "unresolved": sorted(unresolved),
        "coverage": {rid: coverage[rid] for rid in sorted(coverage)},
        "records": {identity: records[identity] for identity in sorted(records)},
    }


def refresh(arc_dir: Path) -> dict | None:
    """Rebuild and publish the ledger; never fail the pass that triggered it."""
    try:
        ledger = build(arc_dir)
        if not ledger["sources"]["db_obligations"]:
            ledger["status"] = "BUILDING"
        elif ledger["resolved"]:
            ledger["status"] = "RESOLVED"
        elif ledger["totals"]["allocated"]:
            ledger["status"] = "PARTIAL"
        else:
            ledger["status"] = "BUILDING"
        save_json(Path(arc_dir) / LEDGER, ledger)
        return ledger
    except Exception as error:  # A projection must never break compilation.
        print(f"[OBLIGATIONS] ledger refresh skipped: {type(error).__name__}: {error}", flush=True)
        return None


def summary(ledger: dict) -> str:
    """Render one compact line for the final pipeline panel."""
    totals = ledger.get("totals") or {}
    return (f"obligations {totals.get('implemented', 0)}/{totals.get('total', 0)} implemented, "
        f"{totals.get('verified', 0)} verified, {totals.get('allocated', 0)} allocated; "
        f"resolved={ledger.get('resolved', False)}")
