"""Step 09 orchestration: retrieve pages, propose UI/data, parse, and publish.

All leaf requirements are designed before step 10 implements any UI. Reuse is
page-first: retrieval returns the corresponding UI/data subtree, not disconnected
components. Prompts and design records live in ui/design.py."""

import json
from copy import deepcopy

from infrastructure.stages.frontend.ui.design import INSTRUCTIONS, apply_proposal, empty_design, page_elements, normalize_design, page_context, requirement_text_of, shell_context, UIResponseError, data_symbols, semantic_issues
from infrastructure.stages.frontend.ui.proposals import INSTRUCTIONS as EXAMPLE_INSTRUCTIONS
from infrastructure.shared.rag.pages import PageRetriever
from infrastructure.utils.files import save_json
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.shared.agent.discovery import ContextIndex


def bind_requirement_image_pages(design, requirement, rid):
    """Bind image-backed pages to the current requirement when the page hint is unambiguous."""
    owned = list(design["requirements"].get(rid, []))
    images = requirement.get("images", {})
    image_records = images.values() if isinstance(images, dict) else images
    for image in image_records:
        if not isinstance(image, dict):
            continue
        image_id, page_hint = image.get("id"), image.get("page")
        # The requirement's explicit page hint is authoritative. The model may
        # omit the redundant page.images entry when creating a new page.
        if page_hint in design["pages"]:
            page = design["pages"][page_hint]
            page.setdefault("images", [])
            if image_id not in page["images"]:
                page["images"].append(image_id)
            candidates = [page_hint]
        else:
            candidates = [pid for pid, page in design["pages"].items() if image_id in page.get("images", [])]
        if len(candidates) != 1:
            continue
        root = design["pages"][candidates[0]]["root"]
        if root in design["elements"]:
            if root not in owned:
                owned.append(root)
    design["requirements"][rid] = owned


REPAIR_INSTRUCTIONS = """The accepted UI design still violates the accessibility contract.
Repair ONLY the listed elements and return {"elements": {ELEMENT_ID: complete record}}.
Keep every element ID, parent, data declaration and visible label unchanged. Add the missing
role, name or state that each issue describes. Do not return the whole design, do not create
new elements and do not rename existing records.
"""


def repair_semantics(design, tree, model, console, requirement_text=""):
    """Give the model one chance to repair design warnings the implementation would inherit."""
    issues = semantic_issues(design, requirement_text)
    if not issues:
        return design
    # Design-level warnings (for example a missing shell) name no element to repair.
    affected = sorted({issue.split(":", 1)[0] for issue in issues} & set(design["elements"]))
    if not affected:
        print("[UI SEMANTICS] design-level issues need no element repair", flush=True)
        return design
    print(f"[UI SEMANTICS] {len(issues)} issue(s) need repair", flush=True)
    request = {"issues": issues, "elements": {
        uid: deepcopy(design["elements"][uid]) for uid in affected}}

    def accept(proposal):
        elements = proposal.get("elements") if isinstance(proposal, dict) else None
        if not isinstance(elements, dict) or not elements:
            raise UIResponseError(ValueError("elements"), proposal)
        updated = deepcopy(design)
        for uid, node in elements.items():
            if uid in updated["elements"] and isinstance(node, dict):
                updated["elements"][uid] = deepcopy(node)
        normalize_design(updated, tree)
        return updated

    try:
        updated, _ = propose_json(model, REPAIR_INSTRUCTIONS, request, accept, console,
            "UI semantics repair", 2)
    except (RuntimeError, ValueError) as error:
        print(f"[UI SEMANTICS] repair round skipped: {error}", flush=True)
        return design
    remaining = semantic_issues(updated, requirement_text)
    print(f"[UI SEMANTICS] repaired {len(issues) - len(remaining)} of {len(issues)} issue(s)", flush=True)
    return updated


def synthesize_ui(arc_dir, tree, images, contexts, model, console, top_k=3, max_attempts=10):
    """Design UI/data for all leaf requirements using page-first retrieval.

    Show existing/retrieved pages, ask for an incremental proposal, and feed
    response-consumption errors back for repair. Save accepted ui_design.json
    updates; implementation and browser tests belong to step 10."""
    design, retriever = empty_design(), PageRetriever()
    for rid in tree.requirements:
        if tree.children[rid]:
            design["requirements"][rid] = []
            for sid in tree.own_steps[rid]:
                design["steps"][sid] = []
            console.show(f"{rid} | Skip non-leaf UI/data analysis", "Only leaf requirements are analyzed. Organizational parents do not generate or inherit UI nodes.")
    failures = TaskFailures(arc_dir, "09_design_ui", console)
    save_json(arc_dir / "ui_design.json", design)
    for number, rid in enumerate(tree.leaves, 1):
        with failures.task(rid):
            requirement = contexts[rid]
            label = f"UI/data design {number}/{len(tree.leaves)} {rid}"
            console.show(label + " | 1. Requirement and steps", json.dumps(requirement, ensure_ascii=False, indent=2))
            console.show(label + " | 2. All Existing Pages", json.dumps(design["pages"], ensure_ascii=False, indent=2))
            retrieved = retriever.retrieve(requirement, design, top_k)
            console.show(label + " | 3. Retrieved page subtrees (RAG)", json.dumps(retrieved, ensure_ascii=False, indent=2))
            request = {
                "requirement": requirement, "retrieved_pages": retrieved["pages"],
                "all_pages": {pid: {key: page[key] for key in ("name", "route", "root", "images")}
                    for pid, page in design["pages"].items() if pid in retrieved["pages"]},
                "shell": shell_context(design),
            }
            def accept(proposal):
                try:
                    updated = apply_proposal(design, proposal, rid, tree)
                except (KeyError, TypeError, AttributeError) as error:
                    raise UIResponseError(error, proposal) from error
                bind_requirement_image_pages(updated, requirement, rid)
                for pid in proposal["pages"]:
                    console.show(label + f" | Page context {pid}", json.dumps(page_context(updated, pid), ensure_ascii=False, indent=2))
                return updated

            updated, proposal = propose_json(model, INSTRUCTIONS + "\n\n" + EXAMPLE_INSTRUCTIONS,
                request, accept, console, label, max_attempts, context_index=ContextIndex(lambda: {"page": design["pages"], "ui_element": design["elements"], "ui_data": data_symbols(design["elements"])}))
            console.show(label + " | 4. Incremental UI/data changes", json.dumps(proposal, ensure_ascii=False, indent=2))
            design = updated
            save_json(arc_dir / "ui_design.json", design)
            console.artifact("ui_design", design, label + " | Accepted UI")
    failures.finish()
    requirement_text = requirement_text_of(tree)
    design = repair_semantics(design, tree, model, console, requirement_text)
    normalize_design(design, tree)
    roles = {}
    for node in design["elements"].values():
        roles[node["role"]] = roles.get(node["role"], 0) + 1
    print("UI semantics: " + ", ".join(f"{role}={count}" for role, count in sorted(roles.items())), flush=True)
    shell = shell_context(design)
    print(f"UI shell: {len(shell['elements'])} global elements, roots={shell['roots']}", flush=True)
    issues = semantic_issues(design, requirement_text)
    if issues:
        print("UI semantics warnings:" + chr(10) + "  "
            + (chr(10) + "  ").join(issues[:8]), flush=True)
    console.show("UI/data design complete for ALL requirements", f"Saved {arc_dir / 'ui_design.json'}\nRun the UI-implementation pass (10) for existence tests and page implementation. Interactions belong to step 11.")
    return design
