"""Step 04: display requirement/database field relations and read/write obligations."""

from pathlib import Path

from infrastructure.stages.database.obligations.records import normalize_obligations, check_symbols
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import read_artifact
from infrastructure.utils.presentation.formatting import format_obligations, format_requirement_schema_relations


def check_db_obligations(arc_dir: Path, pause: bool = False) -> dict:
    """Print the schema ER graph and requirement-to-field/read-write relations."""
    tree = RequirementTree(read_artifact(arc_dir, "requirements.json"))
    schema = read_artifact(arc_dir, "db_schema.json")
    result = normalize_obligations(read_artifact(arc_dir, "db_obligations.json"), tree)
    check_symbols([*result["requirements"].values(), *result["steps"].values()], schema)
    DemoConsole(pause).show("Step 04 | Requirement DB obligations", (
        format_requirement_schema_relations(schema) + "\n\nOBLIGATIONS\n" +
        format_obligations(result["requirements"]) + "\nSTEPS\n" + format_obligations(result["steps"])
    ))
    return result
