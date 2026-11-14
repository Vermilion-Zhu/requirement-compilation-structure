"""Compile supplied requirement structure into source-linked execution contracts."""

from hashlib import sha256
import json
from pathlib import Path
import re

import yaml

from infrastructure.stages.requirements.input_materials import collect_materials
from infrastructure.stages.requirements.tree import RequirementTree


DECLARED_ROLE = re.compile(r'["“`]([^"”`\n]+)["”`]\s*\(\s*role\s*=\s*([\w-]+)\s*\)', re.I)


def resolve_source(root: dict, source: str):
    """Resolve the exact JSON pointer used by a compiled requirement citation."""
    prefix = "requirements.yaml#"
    if not isinstance(source, str) or not source.startswith(prefix):
        raise ValueError("Evidence must reference requirements.yaml")
    pointer = source[len(prefix):]
    if pointer and not pointer.startswith("/"):
        raise ValueError("Invalid requirement evidence pointer")
    value = root
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        try:
            value = value[int(token)] if isinstance(value, list) and token.isdigit() else value[token]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError(f"Requirement evidence does not exist: {source}") from error
    return value


def ui_declarations(contracts: list[dict]) -> list[dict]:
    """Index literal quoted role annotations; retain evidence for other prose to resolve."""
    declarations = []
    seen = set()
    identities = {}

    def strings(value, pointer):
        if isinstance(value, str):
            yield value, pointer
        elif isinstance(value, dict):
            for key, child in value.items():
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                yield from strings(child, pointer + "/" + escaped)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from strings(child, pointer + f"/{index}")

    for contract in contracts:
        for key, value in contract.items():
            if key in {"id", "source", "source_id"}:
                continue
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            for text, pointer in strings(value, contract["source"] + "/" + escaped):
                previous = None
                for match in DECLARED_ROLE.finditer(text):
                    label, role = match.group(1), match.group(2).lower()
                    identity = (contract["id"], role, label)
                    if identity in seen:
                        previous = (match, identities[identity])
                        continue
                    seen.add(identity)
                    declaration = {"id": f"UI-{len(declarations)+1}", "requirement_id": contract["id"],
                                   "source": pointer, "evidence": match.group(0), "role": role,
                                   "label": label, "template": bool(re.search(r"\{[^{}]+\}", label))}
                    if role in {"status", "alert"}:
                        declaration["default_accessible_name"] = label
                        declaration["default_source"] = "website_defaults.feedback_names"
                    if previous:
                        previous_match, parent = previous
                        connector = text[previous_match.end():match.start()]
                        if (parent["role"] in {"status", "alert", "dialog", "form", "navigation", "menu", "region"}
                                and re.fullmatch(r"\s+(?:with|containing)\s+", connector, re.I)):
                            declaration["container"] = parent["id"]
                            declaration["container_evidence"] = text[previous_match.start():match.end()]
                    declarations.append(declaration)
                    identities[identity] = declaration
                    previous = (match, declaration)
    return declarations


def compile_requirements(directory: Path) -> tuple[dict, dict]:
    """Preserve original clauses and metadata while indexing their requirement owners."""
    original = (directory / "requirements.yaml").read_text(encoding="utf-8-sig")
    raw = yaml.safe_load(original)
    tree = RequirementTree(raw)

    def nodes(node, pointer):
        yield node, pointer
        children = node.get("children")
        if isinstance(children, list):
            for index, child in enumerate(children):
                if isinstance(child, dict):
                    yield from nodes(child, f"{pointer}/children/{index}")

    contracts = []
    for rid, (node, pointer) in zip(tree.requirements, nodes(raw, "")):
        # Keep every source field other than containment, which has its own index.
        contract = {key: value for key, value in node.items() if key != "children"}
        if node.get("id") != rid:
            contract["source_id"] = node.get("id")
        contract.update(id=rid, source=f"requirements.yaml#{pointer}")
        contracts.append(contract)
    materials = collect_materials(directory)
    canonical = json.loads(json.dumps(raw, ensure_ascii=False, default=str))
    compiled = {
        "source_sha256": sha256(original.encode("utf-8")).hexdigest(),
        "requirement_sha256": sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "contracts": contracts,
        "ui_declarations": ui_declarations(contracts),
        "children": tree.children,
        "implementation_ids": [rid for rid in tree.requirements
                               if tree.own_steps[rid] or not tree.children[rid]],
        "materials": [{key: value for key, value in record.items() if key != "text"}
                      for record in materials["files"]],
        "warnings": [*materials["warnings"], *({"generated_id": rid} for rid in tree.generated_ids)],
        "website_defaults": {
            "feedback_names": "When a requirement identifies status/alert feedback by a specific message, "
                "default its accessible name to that message. Exclude child action captions. "
                "Explicit requirements for another name or an unnamed element take precedence.",
            "landmark_names": "A navigation, region or dialog identified by name uses that accessible name. "
                "Its name alone does not require a separate visible heading or text node. "
                "Explicit original role, name and visible-text requirements take precedence.",
        },
    }
    return raw, compiled
