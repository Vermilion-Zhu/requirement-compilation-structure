"""Index requirement containment while retaining each scenario's step context.

ARC-Bench tasks are not guaranteed to reuse the teaching example's exact shape:
scenarios and steps may omit identifiers, ``description`` may be a string, a
mapping or a list, and ``children`` may be absent or null. The index therefore
normalizes what it can and only rejects a tree that cannot be traversed at all;
later passes depend on stable IDs, so missing ones are generated deterministically
and reported instead of aborting the compilation.
"""

import json


# --- Extension point: requirement representation and traversal ----------------
# Extend normalization or reference handling here. Stable IDs, explicit step
# ownership, and correct postorder are shared contracts of steps 02 through 04.
class RequirementTree:
    """Normalized requirement and scenario indexes with explicit step ownership and traversal order."""
    def __init__(self, root: dict) -> None:
        """Index requirements and scenario steps while validating IDs and ownership.

        Build children, own_steps, leaf order, and child-before-parent postorder
        once so later stages share the same containment semantics.
        """
        if not isinstance(root, dict):
            raise ValueError("The requirement tree root must be an object")
        self.requirements = {}
        self.steps = {}
        self.children = {}
        self.own_steps = {}
        self.postorder = []
        self.generated_ids = []

        def items(node, key):
            """Read an optional list field, tolerating a missing or null value."""
            value = node.get(key, [])
            return value if isinstance(value, list) else []

        def text(value):
            """Normalize a requirement text field that may be a string, list or mapping."""
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                return text(value.get("text", ""))
            if isinstance(value, list):
                return "\n".join(part for part in (text(item) for item in value) if part)
            return "" if value is None else str(value)

        def generated(value, fallback):
            """Keep a supplied identifier or derive a stable one and record it."""
            name = str(value or "").strip()
            if name:
                return name
            self.generated_ids.append(fallback)
            return fallback

        def unique(name, used):
            """Disambiguate a duplicated supplied identifier without dropping a node."""
            if name not in used:
                return name
            index = 2
            while f"{name}-{index}" in used:
                index += 1
            self.generated_ids.append(f"{name}-{index}")
            return f"{name}-{index}"

        def visit(node):
            """Index one requirement and its own steps, recurse into children, then append postorder."""
            if not isinstance(node, dict):
                return None
            rid = unique(generated(node.get("id"), f"REQ-{len(self.requirements) + 1}"), self.requirements)
            self.requirements[rid] = {"id": rid, "name": text(node.get("name")), "description": text(node.get("description"))}
            self.own_steps[rid] = []
            for scenario_index, scenario in enumerate(items(node, "scenarios"), 1):
                if not isinstance(scenario, dict):
                    continue
                sid = generated(scenario.get("id"), f"SCE-{rid}-{scenario_index}")
                for step_index, step in enumerate(items(scenario, "steps"), 1):
                    if not isinstance(step, dict):
                        continue
                    step_id = unique(generated(step.get("id"), f"STEP-{rid}-{scenario_index}-{step_index}"), self.steps)
                    record = {"id": step_id, "scenario": {"id": sid, "name": text(scenario.get("name"))}}
                    for key in ("Given", "When", "Then"):
                        record[key] = text(step.get(key, step.get(key.lower(), "")))
                    record["references"] = items(step, "references")
                    self.steps[step_id] = record
                    self.own_steps[rid].append(step_id)
            self.children[rid] = [child for child in (visit(child) for child in items(node, "children")) if child]
            self.postorder.append(rid)
            return rid

        visit(root)
        if not self.requirements:
            raise ValueError("The requirement tree has no requirement nodes")
        # Only leaves own business analysis; parents organize the requirement tree.
        self.leaves = [rid for rid in self.requirements if not self.children[rid]]
        if self.generated_ids:
            print(f"[INPUT WARNING] Generated {len(self.generated_ids)} missing or duplicate identifier(s): "
                + ", ".join(sorted(set(self.generated_ids))[:20]), flush=True)

    def concatenated_steps(self, requirement_id: str) -> str:
        """Render only this requirement's own steps, preserving scenario labels, Given/When/Then, and references."""
        lines = []
        previous_scenario = None
        for step_id in self.own_steps[requirement_id]:
            step = self.steps[step_id]
            scenario = step["scenario"]
            if scenario["id"] != previous_scenario:
                lines.append(f"Scenario {scenario['id']}: {scenario['name']}")
                previous_scenario = scenario["id"]
            lines.append(f"Step {step_id}")
            lines.extend(f"{key}: {step[key]}" for key in ("Given", "When", "Then"))
            if step["references"]:
                lines.append("References: " + json.dumps(step["references"], ensure_ascii=False))
        return "\n".join(lines)
