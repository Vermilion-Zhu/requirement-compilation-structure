"""The thirteen compilation passes as importable modules.

Pass filenames use stage_00 through stage_12 prefixes to expose execution order.
The compiler imports them through this registry. Each pass reads the persisted
artifacts it needs from the shared .arc directory. Execution order alone does
not imply that a pass consumes the immediately preceding pass's output.

Keys match the labels used in ``.arc/compilation.json`` and in the pass logs.
"""

from importlib import import_module

PASS_MODULES = {
    "00_project_initialization": "infrastructure.stages.passes.stage_00_project_initialization",
    "01_explore_requirement": "infrastructure.stages.passes.stage_01_explore_requirement",
    "02_build_db_schema": "infrastructure.stages.passes.stage_02_build_db_schema",
    "03_infer_db_obligations": "infrastructure.stages.passes.stage_03_infer_db_obligations",
    "04_check_db_obligations": "infrastructure.stages.passes.stage_04_check_db_obligations",
    "05_implement_db": "infrastructure.stages.passes.stage_05_implement_db",
    "06_design_backend_apis": "infrastructure.stages.passes.stage_06_design_backend_apis",
    "07_check_backend_apis": "infrastructure.stages.passes.stage_07_check_backend_apis",
    "08_implement_backend_tdd": "infrastructure.stages.passes.stage_08_implement_backend_tdd",
    "09_design_ui": "infrastructure.stages.passes.stage_09_design_frontend_ui",
    "10_implement_ui": "infrastructure.stages.passes.stage_10_implement_frontend_ui",
    "11_design_frontend_triggers": "infrastructure.stages.passes.stage_11_design_frontend_triggers",
    "12_implement_frontend_tdd": "infrastructure.stages.passes.stage_12_implement_frontend_triggers",
}


def load_pass(key: str):
    """Import the module that owns one pass function, keeping passes isolated."""
    return import_module(PASS_MODULES[key])
