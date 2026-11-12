"""UI design examples with variable declarations inside elements."""

import json


EXAMPLE = {
    "elements": {
        "UI-app-nav": {"type": "container", "role": "navigation", "name": "Main navigation",
            "scope": "global", "parent": None, "mode": [], "data": [], "prop": {}},
        "UI-app-home-link": {"type": "link", "role": "link", "scope": "global",
            "parent": "UI-app-nav", "mode": ["user_read"], "data": [],
            "prop": {"label": "Home", "href": "/"}},
        "UI-home": {"type": "page", "role": "page", "scope": "page", "parent": None,
            "mode": [], "data": [], "prop": {}},
        "UI-search": {"type": "input", "role": "textbox", "parent": "UI-home",
            "mode": ["user_write"],
            "data": [{"var": "search.query", "dtype": "string", "constraints": []}],
            "prop": {"label": "Search"}},
        "UI-archived-filter": {"type": "button", "role": "button", "parent": "UI-home",
            "mode": ["user_write"],
            "data": [{"var": "search.archived", "dtype": "boolean",
                "constraints": ["True while archived results are shown"]}],
            "state": {"pressed": {"var": "search.archived", "equals": True}},
            "prop": {"label": "Show archived"}},
        "UI-results": {"type": "list", "role": "region", "name": "Search results", "parent": "UI-home",
            "mode": ["user_read"],
            "data": [{"var": "search.results", "dtype": "array",
                "constraints": ["Entries contain id and title strings and match the submitted query"]}], "prop": {}},
    },
    "pages": {"home": {"name": "Home", "route": "/", "root": "UI-home", "images": []}},
    "requirement_ui": ["UI-home", "UI-search", "UI-results", "UI-archived-filter"],
    "step_ui": {"STEP-search": ["UI-search", "UI-results"]},
}
REUSE_EXAMPLE = {"elements": {}, "pages": {}, "requirement_ui": ["UI-search"],
    "step_ui": {"STEP-reuse": ["UI-search"]}}
INSTRUCTIONS = (
    "COMPLETE UI DECLARATION EXAMPLE:\n" + json.dumps(EXAMPLE, ensure_ascii=False, indent=2)
    + "\nREUSE WITHOUT CHANGES:\n" + json.dumps(REUSE_EXAMPLE, indent=2)
    + "\nReturn all four sections. Variables belong in element.data; do not add runtime values."
)
