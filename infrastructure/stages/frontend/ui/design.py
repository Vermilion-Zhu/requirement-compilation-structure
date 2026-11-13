"""Canonical UI/data records and incremental design updates."""

from copy import deepcopy
import re



INSTRUCTIONS = """Design the UI elements and frontend data declarations for the current requirement.
Use requirement scenarios and visual references; reuse supplied UI elements where appropriate.
This stage declares the interface only. Return no code, tests, API definitions, triggers,
production initial values, example runtime objects or display fixtures.

OUTPUT CONTRACT
Return one JSON object with four sibling keys: elements, pages, requirement_ui, step_ui.
elements maps ELEMENT IDs to {type, role, name, state, scope, parent, mode, data, prop}. A page
root has type "page" and parent=null. Other elements reference a parent ELEMENT ID. Use
ordinary types: container, form, input, checkbox, select, button, text, heading, link, list,
item, image, alert, status or table. role is required (see ACCESSIBILITY CONTRACT); name is
optional; state maps ARIA states to their data binding; scope is "global" for application
chrome and "page" otherwise. mode is an array containing user_read and/or user_write, or [].

data is an array of variable declarations: {var, dtype, constraints}.
var is the frontend variable name; dtype is string, integer, number, boolean, array,
object or null. constraints describes requirement-based rules and any array/object shape.
Declare all dynamic data consumed by the element, including visibility dependencies.
Repeat the same declaration consistently when several elements share a variable.
Do not produce a separate bindings registry or initial/source fields.
Fixed headings, labels, hints and button captions belong in prop, not dynamic data.
prop contains static text, label, placeholder, input_type, options, style, href, alt
or heading level. Optional prop.visible is a boolean or {var:VARIABLE_NAME, equals:VALUE}.
A status dependency controls visibility without requiring its raw value as display text.

Treat explicit UI names and roles in the original requirement as interface contracts.
Preserve required labels, action names, region names and placeholders verbatim, including
language, spelling and case. Do not paraphrase, add object-type prefixes, translate or
concatenate aliases: a required "Name" field must not become "Shelf name". Record the
wording in the existing element.prop; do not create a separate naming registry.
Explicit requirement wording takes precedence over visual-reference examples. Only choose
wording freely when it is unspecified or alternatives are explicitly allowed. Business
record names and user-entered values remain dynamic; example data is not fixed UI wording.

APPLICATION SHELL
The application has one shell: the header, primary navigation, footer and other chrome that
every page shares. Design it once, not once per page.
- Declare each shell element with scope "global" and no page parent (parent=null); its
  children inherit the global scope. Shell elements are page-independent, so they are not
  part of any page subtree.
- Read the existing pages and the existing shell before proposing. Reuse the shell element
  IDs instead of declaring another header or navigation for a new page; extend the shell
  only when the requirement adds a genuinely new global entry.
- A page root and its content use scope "page". Do not copy shell elements into a page and
  do not give a page its own duplicate primary navigation.
- A page-level link row such as a breadcrumb or a section switcher is page content: model it
  as a container of links, not as a second navigation landmark. Only the shell declares the
  primary navigation landmark, unless the original requirement explicitly requires a
  breadcrumb navigation landmark.
- The application entry route "/" is a page like any other. When the requirement describes a
  homepage or landing page, or says the primary collection appears there, model that page
  with route "/" and its real content. Never leave the entry route to a placeholder page.
- When the requirement names a landmark (for example "Main navigation"), use that exact
  accessible name; do not paraphrase it as "Primary navigation".
The request lists the current shell; keep it consistent across requirements.

ACCESSIBILITY CONTRACT
Declare role for every element. role states what the control is, independently of styling:
page, main, region, navigation, heading, button, link, textbox, checkbox, combobox, list,
listitem, form, img, alert, status, table, dialog, text or container.
For unspecified roles, choose by behavior:
- A control that changes data or the current record/form, opens an editor or dialog, submits,
  saves, cancels, confirms, deletes, adds or removes is role button. This holds even when
  activating it changes the route: an action is never modelled as a link.
- A control that only reveals another content view inside the reading flow (primary
  navigation, breadcrumbs, links inside a list of records) is role link. The container that
  groups the links is role navigation only for the shell's primary navigation; page-level
  breadcrumbs and section switchers stay role container so the application exposes exactly
  one primary navigation landmark per page.
- A primary-navigation entry is role link only when the requirement calls it a link (for
  example "a named link in navigation"); an entry the requirement says to follow or click in
  the navigation is role button, even though it switches the view.
- A group of records or items is role region with an explicit name. Success and
  informational notices are role status; errors and interruption warnings are role alert.
  A form is role form, and every input declares textbox, checkbox or combobox and is
  labelled by its visible label.
- A page root is role page; use container for ungrouped layout boxes.
A requirement that states a role verbatim wins over the heuristics above: use exactly that
role even when the visual reference or another rule suggests otherwise. A requirement that
states an ARIA state (for example pressed, current, expanded, selected, checked) must be
recorded in element.state even when the styling does not show it; do not leave a stated
state to the implementation's discretion.
Preserve explicitly required accessible names. Visible wording and accessible names are
separate properties. Landmark names are contracts too: if the requirement names a navigation,
banner or region (for example "Main navigation"), use that exact accessible name; never
paraphrase it. For status/alert feedback identified by specific message text, default
name to that message unless the requirement specifies another name or leaves it unnamed.
For different messages, use separate elements with their own name, text and visibility.
Exclude child action captions from feedback names. Other names are chosen where needed.
name and prop.label are templates: use {var} for a current-record value, for example
{note.title}. Preserve the exact required template without adding object-type prefixes.
The implementation substitutes the actual value on every render. Data-driven names (profile
display names, record titles) use the same template form; a concrete example
from the requirement is not a literal element name.

pages maps PAGE IDs to {name, route, root, images}. route is a URL path, root is an
ELEMENT ID and images lists supplied image IDs. Preserve explicit image.page hints.
Do not add fixtures or sample objects. Reference images describe appearance, not actual
loaded records. Requirement-defined defaults remain requirement evidence for implementation;
do not turn them into a separate initialization model in this design.
requirement_ui lists element IDs used by the current requirement. step_ui maps every
current scenario step ID to element IDs, using [] when no UI is needed.

UPDATES AND REUSE
Return complete records for new or changed elements/pages, preserving unrelated behavior.
Unchanged records may be omitted from their maps; include all four root keys even when empty.
Reuse canonical variable names and element IDs. Query relevant elements/pages when needed.
mode declares how the user interacts with the element; implementation chooses framework
bindings and routing. No fixed host synchronizes inputs or interprets this design. Additional
interaction behavior belongs to step 11; real data loading and updates belong to step 12.
Preserve visible labels in their original language. UI has no DB field-mapping model.
"""

OUTPUT_TEMPLATE = {"elements": {}, "pages": {}, "requirement_ui": [], "step_ui": {}}

# Semantic vocabulary. `role` is where the design states the accessibility contract; the
# implementation renders it, so the mapping stays independent of any single application.
ROLE_BY_TYPE = {
    "page": "page", "container": "container", "form": "form", "input": "textbox",
    "checkbox": "checkbox", "select": "combobox", "button": "button", "link": "link",
    "text": "text", "heading": "heading", "list": "list", "item": "listitem",
    "image": "img", "alert": "alert", "status": "status", "table": "table",
}
ROLE_BY_INPUT_TYPE = {"checkbox": "checkbox", "radio": "radio", "number": "spinbutton"}
# Only roles whose element implementation is unambiguous are constrained. Structural
# containers (container, list, item, text) may legitimately carry a richer role.
ROLE_FAMILIES = {
    "page": {"page", "main"}, "form": {"form"},
    "input": {"textbox", "checkbox", "combobox", "spinbutton", "radio", "searchbox"},
    "checkbox": {"checkbox"}, "select": {"combobox"}, "button": {"button"},
    "link": {"link"}, "heading": {"heading"}, "image": {"img"}, "alert": {"alert"},
    "status": {"status"}, "table": {"table"},
}
# Roles whose meaning depends on an accessible name the markup cannot derive from its text.
NAMED_ROLES = {"region", "navigation"}
SCOPES = {"page", "global"}
# ARIA states a design may bind to data; the implementation renders them as aria-* attributes.
ARIA_STATES = {"pressed", "current", "expanded", "selected", "checked", "disabled", "busy", "invalid"}


def derived_role(node: dict) -> str:
    """Return the role implied by an element's type and input type."""
    kind = str(node.get("type") or "").strip().lower()
    if kind == "input":
        input_type = str((node.get("prop") or {}).get("input_type") or "").strip().lower()
        return ROLE_BY_INPUT_TYPE.get(input_type, "textbox")
    return ROLE_BY_TYPE.get(kind, "container")


class UIResponseError(ValueError):
    """Attach the concrete output layout after a model record cannot be consumed."""
    def __init__(self, error, proposal):
        super().__init__(f"Cannot read UI/data response: {error}")
        self.feedback = {"response_template": OUTPUT_TEMPLATE,
            "missing_sections": [key for key in OUTPUT_TEMPLATE if not isinstance(proposal, dict) or key not in proposal],
            "repair": "Write the missing variable and element records in the FINAL JSON, not just in reasoning. Return elements, pages, requirement_ui and step_ui as four sibling root keys. Declare variables inside element.data. A new page needs its root, controls and actual scenario associations. Do not repeat the rejected pages-only answer or merely add empty maps for a new page."}


def empty_design() -> dict:
    """Keep UI elements, pages and requirement associations."""
    return {"pages": {}, "elements": {}, "requirements": {}, "steps": {}}


def page_elements(design: dict, pid: str) -> dict:
    """Return the IDs in one page's UI subtree, including its root."""
    root = design["pages"][pid]["root"]
    selected = {root}
    while True:
        expanded = selected | {uid for uid, node in design["elements"].items() if node.get("parent") in selected}
        if expanded == selected:
            return {uid: deepcopy(node) for uid, node in design["elements"].items() if uid in selected}
        selected = expanded


def data_symbols(elements: dict) -> dict:
    """Derive a variable lookup from element declarations without storing another registry."""
    symbols = {}
    for element in elements.values():
        for declaration in element.get("data", []):
            symbols[declaration["var"]] = deepcopy(declaration)
    return symbols


def page_context(design: dict, pid: str) -> dict:
    """Return a page, its UI subtree and the page-independent application shell."""
    return {"id": pid, **deepcopy(design["pages"][pid]), "elements": page_elements(design, pid),
        "shell": shell_context(design)}


def owners(design: dict, pid: str) -> list[str]:
    """Return requirements that directly reference elements on this page."""
    ids = set(page_elements(design, pid))
    return [rid for rid, bound in design["requirements"].items() if ids.intersection(bound)]


def visible(design: dict, uid: str, values: dict) -> bool:
    """Evaluate the supported static/variable-equality visibility rule using the supplied display values."""
    visited = set()
    while uid is not None and uid not in visited and uid in design["elements"]:
        visited.add(uid)
        node = design["elements"][uid]
        rule = node.get("prop", {}).get("visible", True)
        if rule is False or (isinstance(rule, dict) and values.get(rule.get("var")) != rule.get("equals")):
            return False
        uid = node.get("parent")
    return True


def normalize_design(design, tree):
    """Fill optional page metadata and semantic defaults without rejecting model decisions."""
    for pid, page in design["pages"].items():
        page.setdefault("name", pid)
        page.setdefault("images", [])
    for node in design["elements"].values():
        node.setdefault("mode", [])
        node.setdefault("data", [])
        node.setdefault("prop", {})
        declared = str(node.get("role") or "").strip().lower()
        node["role"] = declared or derived_role(node)
        # The declared role is authoritative when it describes the same axis as the type:
        # an action declared as a button must not be implemented as an anchor and vice versa.
        kind = str(node.get("type") or "").strip().lower()
        if declared in {"button", "link"} and kind in {"button", "link"} and declared != kind:
            node["type"] = declared
        elif declared in {"alert", "status"} and kind in {"alert", "status"} and declared != kind:
            node["type"] = declared
        name = node.get("name")
        if isinstance(name, str) and name.strip():
            node["name"] = name.strip()
        else:
            node.pop("name", None)
        scope = str(node.get("scope") or "").strip().lower()
        node["scope"] = scope if scope in SCOPES else "page"
        state = node.get("state")
        if isinstance(state, dict):
            cleaned = {}
            for key, value in state.items():
                if not isinstance(key, str):
                    continue
                attribute = key.strip().lower().removeprefix("aria-")
                if attribute in ARIA_STATES:
                    cleaned[attribute] = value
            if cleaned:
                node["state"] = cleaned
            else:
                node.pop("state", None)
        else:
            node.pop("state", None)
    inherit_global_scope(design)
    for kind, expected in (("requirements", tree.requirements), ("steps", tree.steps)):
        for identity in expected:
            design[kind].setdefault(identity, [])
    return design


def inherit_global_scope(design: dict) -> None:
    """Give every child of a global element the global scope as well."""
    elements = design["elements"]
    changed = True
    while changed:
        changed = False
        for node in elements.values():
            if node.get("scope") == "global":
                continue
            parent = elements.get(node.get("parent")) if isinstance(node.get("parent"), str) else None
            if parent is not None and parent.get("scope") == "global":
                node["scope"] = "global"
                changed = True


def shell_elements(design: dict) -> dict:
    """Return the page-independent shell subtree: global elements and their children."""
    return {uid: deepcopy(node) for uid, node in design["elements"].items()
        if node.get("scope") == "global"}


def shell_context(design: dict) -> dict:
    """Return the shell as an ordered element map for the request."""
    shell = shell_elements(design)
    roots = [uid for uid, node in shell.items() if node.get("parent") not in shell]
    return {"roots": roots, "elements": shell}


def _accessible_name(node: dict) -> str:
    """Return the declared accessible name of one element."""
    prop = node.get("prop") or {}
    for value in (node.get("name"), prop.get("label"), prop.get("text")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _subtree(elements: dict, uid: str) -> set[str]:
    """Return one element and every descendant below it."""
    selected = {uid}
    changed = True
    while changed:
        changed = False
        for child_id, child in elements.items():
            if child_id not in selected and child.get("parent") in selected:
                selected.add(child_id)
                changed = True
    return selected


QUOTED_ROLE = re.compile(r'"([^"\n]{1,80})"\s*\(role=([a-z][a-z-]*)\)')
NAMED_NAVIGATION = re.compile(
    r"(?:\bin\b|\bvisible\b|\bnamed\b|\blabeled\b|\blabelled\b|\bon\b)\s+"
    r"(?:the\s+)?([A-Z][A-Za-z]{1,20})\s+navigation\b")
FOLLOW_NAVIGATION = re.compile(
    r'Follow\s+"?([A-Z][A-Za-z0-9 {}\-]{1,60}?)"?\s+in\s+(?:the\s+)?([A-Z][A-Za-z]{1,20})\s+navigation')
# "Main navigation" is a compound landmark name; "Sidebar navigation" names the sidebar.
GENERIC_NAVIGATION_WORDS = {"main", "primary", "global", "application", "app", "site",
    "top", "bottom", "left", "right"}
ROLE_ALIASES = {"textbox": {"textbox", "searchbox"}, "searchbox": {"searchbox", "textbox"}}


def requirement_text_of(tree) -> str:
    """Flatten requirement names, descriptions and steps for contract checks."""
    parts = []
    for record in tree.requirements.values():
        parts.append(str(record.get("name") or ""))
        parts.append(str(record.get("description") or ""))
    for record in tree.steps.values():
        for key in ("Given", "When", "Then"):
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)
    return "\n".join(parts)


def _navigation_name(phrase: str) -> str:
    """Use the full compound name for generic words, otherwise the noun before "navigation"."""
    phrase = phrase.strip()
    return phrase + " navigation" if phrase.lower() in GENERIC_NAVIGATION_WORDS else phrase


def _elements_named(design: dict, name: str) -> list[tuple[str, str]]:
    """Return (element id, role) for every element exposing the accessible name."""
    return [(uid, str(node.get("role") or "")) for uid, node in design["elements"].items()
        if _accessible_name(node) == name]


def requirement_contract_issues(design: dict, requirement_text: str) -> list[str]:
    """Report requirement-stated names, roles, landmarks and the entry route missing from design."""
    if not requirement_text:
        return []
    issues = []
    elements = design["elements"]
    def role_matches(actual: str, expected: str) -> bool:
        return actual == expected or actual in ROLE_ALIASES.get(expected, set())

    def templated(role: str) -> bool:
        return any(role_matches(str(node.get("role") or ""), role)
            and any(marker in _accessible_name(node) for marker in ("{", "<"))
            for node in elements.values())

    for match in QUOTED_ROLE.finditer(requirement_text):
        name, role = match.group(1).strip(), match.group(2)
        if any(marker in name for marker in ("<", ">")):
            continue  # the requirement uses a placeholder example, not a literal name
        candidates = _elements_named(design, name)
        if not candidates:
            # A requirement example ("Stack User") may stand for a record-driven name.
            if templated(role):
                continue
            issues.append(f"design: requirement names {name!r} (role={role}) but no element exposes it")
            continue
        if not any(role_matches(actual, role) for _, actual in candidates):
            uid, actual = candidates[0]
            issues.append(f"{uid}: requirement names {name!r} as role {role!r} but this element is {actual!r}")
    navigations = {_accessible_name(node): uid for uid, node in elements.items()
        if node.get("role") == "navigation" and _accessible_name(node)}
    for match in NAMED_NAVIGATION.finditer(requirement_text):
        required = _navigation_name(match.group(1))
        if required in navigations:
            continue
        if len(navigations) == 1:
            name, uid = next(iter(navigations.items()))
            issues.append(f"{uid}: requirement names the navigation {required!r} "
                f"but this element is named {name!r}")
        elif navigations:
            issues.append(f"design: requirement names a navigation {required!r} "
                "but no navigation uses that name")
        else:
            issues.append(f"design: requirement names a navigation {required!r} "
                "but the design has none")
    for match in FOLLOW_NAVIGATION.finditer(requirement_text):
        item = match.group(1).strip().rstrip('"')
        required = _navigation_name(match.group(2))
        candidates = _elements_named(design, item)
        if not candidates:
            issues.append(f"design: requirement follows {item!r} in {required!r} "
                "but no element exposes it")
            continue
        if any(role == "button" for _, role in candidates):
            continue
        uid, actual = candidates[0]
        issues.append(f"{uid}: requirement follows {item!r} in {required!r}, "
            f"so it must be role button (this element is {actual!r})")
    if re.search(r"\b(homepage|home page|landing page|entry route|entry page)\b",
            requirement_text, re.I):
        routes = {str(page.get("route") or "").split("?")[0] for page in design["pages"].values()}
        if not routes.intersection({"/", ""}):
            issues.append("design: requirements describe a homepage but no page uses route '/'")
    return list(dict.fromkeys(issues))


def semantic_issues(design: dict, requirement_text: str = "") -> list[str]:
    """Report roles, names or states that cannot be rendered as declared."""
    issues = []
    for uid, node in design["elements"].items():
        kind = str(node.get("type") or "").strip().lower()
        role = str(node.get("role") or "").strip().lower()
        family = ROLE_FAMILIES.get(kind)
        if kind not in ROLE_BY_TYPE:
            issues.append(f"{uid}: unknown type {kind!r}")
        elif family is not None and role not in family:
            issues.append(f"{uid}: role {role!r} conflicts with type {kind!r}")
        label = (node.get("prop") or {}).get("label")
        if role in NAMED_ROLES and not (node.get("name") or label):
            issues.append(f"{uid}: {role} needs an accessible name")
        state = node.get("state")
        if state is not None and not isinstance(state, dict):
            issues.append(f"{uid}: state must map ARIA states to data bindings")
        elif isinstance(state, dict):
            for key, value in state.items():
                if str(key).strip().lower() not in ARIA_STATES:
                    issues.append(f"{uid}: unknown ARIA state {key!r}")
                elif not (isinstance(value, bool)
                        or (isinstance(value, dict) and isinstance(value.get("var"), str))):
                    issues.append(f"{uid}: state {key!r} needs a boolean or a variable rule")
        if node.get("scope") == "global":
            parent = design["elements"].get(node.get("parent")) if isinstance(node.get("parent"), str) else None
            if parent is not None and parent.get("scope") != "global":
                issues.append(f"{uid}: global element must not be nested in a page")
    if len(design["pages"]) > 1 and not shell_elements(design):
        issues.append("design: several pages share no global shell")
    global_links = set()
    page_navigations = []
    for uid, node in design["elements"].items():
        if node.get("role") != "navigation":
            continue
        links = {_accessible_name(design["elements"][child_id])
            for child_id in _subtree(design["elements"], uid)
            if design["elements"][child_id].get("role") == "link"}
        links.discard("")
        if node.get("scope") == "global":
            global_links |= links
        else:
            page_navigations.append((uid, links))
    for uid, links in page_navigations:
        duplicates = sorted(links & global_links)
        if duplicates:
            issues.append(f"{uid}: navigation repeats the global link(s) {duplicates!r}; "
                "model breadcrumbs as page content instead of a second navigation landmark")
    issues.extend(requirement_contract_issues(design, requirement_text))
    return list(dict.fromkeys(issues))


def apply_proposal(design, proposal, rid, tree):
    """Replace supplied JSON records without retrieval, immutable-identity or UI-policy gates."""
    updated = deepcopy(design)
    for kind in ("pages", "elements"):
        updated[kind].update(deepcopy(proposal[kind]))
    updated["requirements"][rid] = proposal["requirement_ui"]
    updated["steps"].update(deepcopy(proposal["step_ui"]))
    normalize_design(updated, tree)
    return updated
