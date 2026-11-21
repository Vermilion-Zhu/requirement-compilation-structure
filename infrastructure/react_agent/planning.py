"""Plan implementation batches for the lightweight ReAct engine.

The planner only groups and orders implementation requirements; it never edits tests. The
controller maps every frozen test case to the batch that owns its requirement and validates
that all implementation IDs are covered exactly once. A deterministic fallback keeps the
feature usable when the plan model is unavailable or returns an invalid plan.
"""

from __future__ import annotations

import json
from pathlib import Path

PLAN_INSTRUCTIONS = """Plan the implementation order for a React/Express/SQLite application.

You receive the original requirement contracts and the inventory of frozen browser-test cases.
Return {"batches":[{"id":"B1","requirements":["REQ-..."],"depends_on":[],
"goal":"short implementation goal"}]}.

Rules:
- Group requirements that share entities, routes, authentication or the same user workflow.
- Put foundation work first (application shell, navigation, shared data model, authentication),
  then feature batches, then cross-feature integration.
- Every implementation ID must appear in exactly one batch.
- depends_on lists earlier batch IDs; dependencies must be acyclic and must not refer to a
  later batch.
- Keep each batch small enough to implement and check together. Do not include test code or
  test assertions; tests are frozen and will be mapped by the controller.
- Do not invent requirements, omit requirements, or change requirement IDs.
"""


def _cases(manifest: dict | None) -> list[dict]:
    return list((manifest or {}).get("cases") or [])


def _contracts_by_id(contracts: dict) -> dict:
    return {item["id"]: item for item in contracts.get("contracts", []) if isinstance(item, dict) and item.get("id")}


def _scenario_weight(contracts_by_id: dict, rid: str) -> int:
    return max(1, len(contracts_by_id.get(rid, {}).get("scenarios") or []))


def _group_requirements(contracts: dict, scenario_limit: int) -> list[list[str]]:
    records = _contracts_by_id(contracts)
    groups, current, weight = [], [], 0
    for rid in contracts.get("implementation_ids", []):
        size = _scenario_weight(records, rid)
        if current and weight + size > max(1, scenario_limit):
            groups.append(current)
            current, weight = [], 0
        current.append(rid)
        weight += size
    if current:
        groups.append(current)
    return groups or [[]]


def _map_cases(plan: dict, manifest: dict | None) -> dict:
    """Attach every frozen case to exactly one batch, by requirement ownership."""
    batches = plan["batches"]
    owner = {}
    for batch in batches:
        for rid in batch["requirements"]:
            owner[rid] = batch["id"]
    for case in _cases(manifest):
        rid = case.get("requirement_id")
        batch = owner.get(rid)
        if batch is None:
            raise ValueError(f"Test case {case.get('title')!r} has no implementation batch")
        record = next(item for item in batches if item["id"] == batch)
        record.setdefault("tests", [])
        if case["title"] not in record["tests"]:
            record["tests"].append(case["title"])
    for batch in batches:
        batch.setdefault("tests", [])
    return plan


def _topological(batches: list[dict]) -> list[dict]:
    by_id = {batch["id"]: batch for batch in batches}
    for batch in batches:
        for dependency in batch["depends_on"]:
            if dependency not in by_id:
                raise ValueError(f"Unknown dependency {dependency!r}")
            if dependency == batch["id"]:
                raise ValueError(f"Batch {batch['id']!r} depends on itself")
    ordered, remaining = [], list(batches)
    while remaining:
        ready = [batch for batch in remaining if all(item in {done["id"] for done in ordered}
            for item in batch["depends_on"])]
        if not ready:
            raise ValueError("Implementation plan dependencies contain a cycle")
        for batch in ready:
            ordered.append(batch)
            remaining.remove(batch)
    return ordered


def validate_plan(plan: dict, contracts: dict, manifest: dict | None = None) -> dict:
    """Normalise a model plan and enforce coverage/order before any implementation starts."""
    if not isinstance(plan, dict) or not isinstance(plan.get("batches"), list) or not plan["batches"]:
        raise ValueError("A plan needs a non-empty batches list")
    expected = list(contracts.get("implementation_ids") or [])
    batches, seen = [], set()
    for index, raw in enumerate(plan["batches"], 1):
        if not isinstance(raw, dict):
            raise ValueError("Each batch must be an object")
        batch_id = str(raw.get("id") or f"B{index}")
        if batch_id in {batch["id"] for batch in batches}:
            raise ValueError(f"Duplicate batch id {batch_id!r}")
        requirements = raw.get("requirements")
        if not isinstance(requirements, list) or not all(isinstance(rid, str) for rid in requirements):
            raise ValueError(f"Batch {batch_id!r} needs a requirements list")
        for rid in requirements:
            if rid not in expected:
                raise ValueError(f"Unknown implementation id {rid!r} in batch {batch_id!r}")
            if rid in seen:
                raise ValueError(f"Implementation id {rid!r} appears more than once")
            seen.add(rid)
        depends_on = raw.get("depends_on") or []
        if not isinstance(depends_on, list) or not all(isinstance(item, str) for item in depends_on):
            raise ValueError(f"Batch {batch_id!r} needs a depends_on list")
        batches.append({"id": batch_id, "requirements": list(requirements),
            "depends_on": list(depends_on), "goal": str(raw.get("goal") or "")})
    missing = [rid for rid in expected if rid not in seen]
    if missing:
        raise ValueError("Plan is missing implementation ids: " + ", ".join(missing))
    result = {"batches": _topological(batches), "source": str(plan.get("source") or "model"),
        "warnings": list(plan.get("warnings") or [])}
    return _map_cases(result, manifest)


def fallback_plan(contracts: dict, manifest: dict | None = None, scenario_limit: int = 12) -> dict:
    """Deterministic plan used when no plan model is available or its output is invalid."""
    groups = _group_requirements(contracts, scenario_limit)
    batches = []
    previous = None
    for index, requirements in enumerate(groups, 1):
        batch = {"id": f"B{index}", "requirements": requirements,
            "depends_on": [previous] if previous else [],
            "goal": "Implement " + ", ".join(requirements) if requirements else "Foundation check"}
        batches.append(batch)
        previous = batch["id"]
    return validate_plan({"batches": batches, "source": "fallback"}, contracts, manifest)


def plan_implementation(contracts: dict, manifest: dict | None = None, *, model=None,
                        timeout: float = 120, scenario_limit: int = 12) -> tuple[dict, dict]:
    """Ask the model for a plan, then fall back to deterministic grouping on any error."""
    cases = [{"requirement_id": case.get("requirement_id"), "title": case.get("title"),
              "step_count": case.get("step_count", 0)} for case in _cases(manifest)]
    request = {"contracts": contracts, "test_inventory": cases}
    name = getattr(model, "name", None) if isinstance(getattr(model, "name", None), str) else None
    reasoning = getattr(model, "reasoning", None) if isinstance(getattr(model, "reasoning", None), str) else None
    meta = {"model": name, "reasoning": reasoning, "attempts": []}
    if model is not None and cases:
        try:
            proposal, usage = model.generate(
                [{"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
                timeout, instructions=PLAN_INSTRUCTIONS)
            meta["usage"] = usage
            meta["attempts"].append({"status": "PROPOSED"})
            plan = validate_plan({**proposal, "source": "model"}, contracts, manifest)
            meta["attempts"][-1]["status"] = "VALIDATED"
            return plan, meta
        except Exception as error:
            meta["attempts"].append({"status": "REJECTED", "error": str(error)})
    plan = fallback_plan(contracts, manifest, scenario_limit=scenario_limit)
    plan["warnings"] = [*plan.get("warnings", []), "plan model unavailable or invalid; used deterministic grouping"]
    return plan, meta


def save_plan(output: Path, plan: dict) -> Path:
    path = Path(output) / ".arc" / "implementation-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
