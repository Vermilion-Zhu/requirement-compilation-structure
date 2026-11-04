"""Input discovery for one requirement directory.

ARC-Bench hands the agent a directory, not a fixed document: besides
``requirements.yaml`` it may contain ``requirements.md``, ``prerequisites.md``,
``assets/`` or ``reference/``. Nothing here may abort a run on a missing optional
file, and the requirement snapshot must be published even when a visual reference
cannot be resolved, because every later pass reads that snapshot.
"""

from pathlib import Path

from infrastructure.utils.files import save_json, save_text

TEXT_SUFFIXES = {".md", ".txt", ".rst", ".json", ".yaml", ".yml"}
TEXT_MATERIAL_LIMIT = 20000
MATERIALS_ARTIFACT = "input_materials.json"
WARNINGS_ARTIFACT = "input_warnings.json"


def material_files(input_dir: Path):
    """Yield the optional material files ARC-Bench may place beside the YAML."""
    for name in ("requirements.md", "prerequisites.md"):
        path = input_dir / name
        if path.is_file():
            yield path
    for directory in ("assets", "reference"):
        root = input_dir / directory
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                yield path


def collect_materials(input_dir: Path) -> dict:
    """Describe every optional input file without ever failing on an unreadable one."""
    materials, warnings = [], []
    for path in material_files(input_dir):
        try:
            size = path.stat().st_size
        except OSError as error:
            warnings.append({"path": path.name, "reason": f"unreadable: {error}"})
            continue
        record = {"path": path.relative_to(input_dir).as_posix(), "bytes": size}
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError) as error:
                record["kind"] = "attachment"
                warnings.append({"path": record["path"], "reason": f"not UTF-8 text: {error}"})
            else:
                record.update(kind="text", chars=len(text), truncated=len(text) > TEXT_MATERIAL_LIMIT,
                    text=text[:TEXT_MATERIAL_LIMIT])
        else:
            record["kind"] = "attachment"
        materials.append(record)
    return {"files": materials, "warnings": warnings}


def resolve_images(input_dir: Path, references: list[str]) -> tuple[dict[str, Path], list[dict]]:
    """Resolve referenced images, reporting unusable ones instead of raising."""
    root = input_dir.resolve()
    resolved, warnings = {}, []
    for reference in references:
        image = (input_dir / reference).resolve()
        if not image.is_relative_to(root):
            warnings.append({"reference": reference, "reason": "outside the requirement directory"})
            continue
        if not image.is_file():
            warnings.append({"reference": reference, "reason": "referenced image does not exist"})
            continue
        resolved[reference] = image
    return resolved, warnings


def publish_input_snapshot(arc_dir: Path, requirements_text: str, references: list[str], *,
        materials: dict, warnings: list[dict]) -> None:
    """Publish the requirement snapshot and every discovery warning together."""
    arc_dir.mkdir(parents=True, exist_ok=True)
    save_text(arc_dir / "requirements.json", requirements_text + "\n")
    save_json(arc_dir / MATERIALS_ARTIFACT, materials)
    save_json(arc_dir / WARNINGS_ARTIFACT, {"image_references": references, "warnings": warnings})
    for warning in warnings:
        print(f"[INPUT WARNING] {warning}", flush=True)
