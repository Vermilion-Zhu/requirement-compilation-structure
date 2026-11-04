"""The thirteen compilation passes as importable modules.

Each pass lives here instead of in a numbered teaching script, so the agent's
deliverable (``main.py`` + ``requirements.txt`` + ``infrastructure/``) is
self-contained: deleting every ``00``-``12`` script at the repository root cannot
break compilation. The numbered scripts are thin command-line wrappers over these
modules and are not imported by the pipeline.

Keys match the labels used in ``.arc/compilation.json`` and in the pass logs.
"""

from importlib import import_module

PASS_MODULES = {
    "00_project_initialization": "infrastructure.stages.passes.project_initialization",
    "01_explore_requirement": "infrastructure.stages.passes.explore_requirement",
    "02_build_db_schema": "infrastructure.stages.passes.build_db_schema",
    "03_infer_db_obligations": "infrastructure.stages.passes.infer_db_obligations",
    "04_check_db_obligations": "infrastructure.stages.passes.check_db_obligations",
    "05_implement_db": "infrastructure.stages.passes.implement_db",
    "06_design_backend_apis": "infrastructure.stages.passes.design_backend_apis",
    "07_check_backend_apis": "infrastructure.stages.passes.check_backend_apis",
    "08_implement_backend_tdd": "infrastructure.stages.passes.implement_backend_tdd",
    "09_design_ui": "infrastructure.stages.passes.design_frontend_ui",
    "10_implement_ui": "infrastructure.stages.passes.implement_frontend_ui",
    "11_design_frontend_triggers": "infrastructure.stages.passes.design_frontend_triggers",
    "12_implement_frontend_tdd": "infrastructure.stages.passes.implement_frontend_triggers",
}


def load_pass(key: str):
    """Import the module that owns one pass function, keeping passes isolated."""
    return import_module(PASS_MODULES[key])
