"""Step 09: design all leaf requirements' UI/data without implementing pages."""

from pathlib import Path

from infrastructure.stages.frontend.context import load_ui_context
from infrastructure.stages.frontend.ui.design import owners
from infrastructure.stages.frontend.ui.synthesis import synthesize_ui
from infrastructure.shared.project import runtime_events
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole


def design_frontend_ui(input_dir: Path, arc_dir: Path, pause: bool = False, top_k: int = 3,
        max_attempts: int = 10) -> dict:
    if top_k < 1:
        raise ValueError("--top-k must be positive")
    tree, images, contexts = load_ui_context(arc_dir, input_dir)
    console, model = DemoConsole(pause), TextModel(json_mode=False)
    design = synthesize_ui(arc_dir, tree, images, contexts,
        model, console, top_k, max_attempts)
    for page_id, page in design["pages"].items():
        runtime_events.interface(page_id, req_ids=owners(design, page_id), kind="page",
            content=f"{page.get('route', '/')} → {page.get('root', '')}")
    print(f"UI/data design saved: {arc_dir / 'ui_design.json'}\nRun the UI-implementation pass (10) to generate existence tests and implement the pages.", flush=True)
    return design
