"""Create a minimal React/Express/SQLite workspace without replacing user files.

ARC-Bench injects an authoritative application baseline into ``--output-dir`` before
the agent starts, so the output directory is usually *not* empty. The compiled
application uses a different scaffold (TypeScript workspaces + ``deploy.sh``), and
mixing the two produces a tree that cannot build: the injected ``backend``/
``frontend`` packages keep their own names, so ``npm run build -w @arc/frontend``
fails before anything starts.

This module therefore classifies the output directory first and takes over a
foreign baseline explicitly: conflicting directories and root files are *moved*
into ``.arc/baseline_backup/<timestamp>/`` (never deleted) and the action is
recorded in ``.arc/baseline_handling.json``. An output directory that already
holds this scaffold keeps its existing files, so reruns and evolution baselines
are preserved.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil

from infrastructure.utils.files import save_json


DEFAULT_STACK = "react-express-sqlite"

# Root package name written by this scaffold; a different name means another app.
SCAFFOLD_MARKER = "arc-application"
# Workspace package names owned by this scaffold.
WORKSPACE_NAMES = {"backend": "@arc/backend", "frontend": "@arc/frontend"}

# Entries the injected baseline owns and the compiler must replace to build.
BASELINE_DIRECTORIES = ("backend", "frontend")
BASELINE_FILES = ("package.json", "package-lock.json", "deploy.sh")

# Escape hatch for evolution tasks: keep the injected application untouched.
KEEP_BASELINE_ENV = "ARC_KEEP_BASELINE"

HANDLING_REPORT = Path(".arc") / "baseline_handling.json"
BACKUP_ROOT = Path(".arc") / "baseline_backup"


# --- Extension point: technology stacks --------------------------------------
# Register another template directory and its empty directories here. New
# database/backend stacks also need matching lowering adapters in steps 05/08.
STACKS = {
    DEFAULT_STACK: {
        "templates": Path(__file__).with_name("templates"),
        "directories": ("backend/src/db/tables", "backend/src/db/seeds"),
    },
}


def _package_name(path: Path) -> str | None:
    """Read a package.json name without failing on malformed injected files."""
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    name = value.get("name") if isinstance(value, dict) else None
    return name if isinstance(name, str) else None


def _owned_by_scaffold(output_dir: Path) -> dict[str, bool]:
    """Report which baseline entries already belong to this scaffold."""
    return {
        name: _package_name(output_dir / name / "package.json") == workspace
        for name, workspace in WORKSPACE_NAMES.items()
    }


def classify_output_dir(output_dir: Path) -> str:
    """Return ``empty``, ``scaffold`` or ``foreign`` for an application root."""
    output_dir = output_dir.resolve()
    owned = _owned_by_scaffold(output_dir)
    root = output_dir / "package.json"
    if root.is_file() and _package_name(root) == SCAFFOLD_MARKER and all(owned.values()):
        return "scaffold"
    present = [name for name in (*BASELINE_DIRECTORIES, *BASELINE_FILES) if (output_dir / name).exists()]
    if not present:
        return "empty"
    # Anything else that occupies a scaffold-owned path is another application.
    return "foreign"


def _describe(path: Path) -> dict:
    """Summarize a moved entry with a size and a content fingerprint."""
    if path.is_file():
        data = path.read_bytes()
        return {"kind": "file", "bytes": len(data), "sha256": sha256(data).hexdigest()}
    files = [item for item in path.rglob("*") if item.is_file()]
    return {"kind": "directory", "files": len(files), "bytes": sum(item.stat().st_size for item in files)}


def take_over_foreign_baseline(output_dir: Path) -> dict:
    """Replace a foreign application baseline with this scaffold, keeping a backup.

    Returns a record suitable for ``.arc/baseline_handling.json``. Nothing is
    deleted: every conflicting entry is moved under ``.arc/baseline_backup``.
    """
    output_dir = output_dir.resolve()
    detected = classify_output_dir(output_dir)
    record: dict[str, object] = {
        "detected": detected,
        "workspace_packages": WORKSPACE_NAMES,
        "kept_env": KEEP_BASELINE_ENV,
    }
    if detected != "foreign":
        record["action"] = "reused_scaffold" if detected == "scaffold" else "initialized_empty"
        return record
    if os.getenv(KEEP_BASELINE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        record["action"] = "kept_by_request"
        record["reason"] = (
            f"{KEEP_BASELINE_ENV}=1 keeps the injected application and skips this "
            "compiler's scaffold, so later passes report missing files instead of "
            "silently mixing two applications.")
        save_json(output_dir / HANDLING_REPORT, record)
        return record

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = output_dir / BACKUP_ROOT / stamp
    backup.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in (*BASELINE_DIRECTORIES, *BASELINE_FILES):
        source = output_dir / name
        if not source.exists():
            continue
        destination = backup / name
        shutil.move(str(source), str(destination))
        moved.append({"path": name, **_describe(destination)})
    record.update({
        "action": "taken_over",
        "backup": (BACKUP_ROOT / stamp).as_posix(),
        "moved": moved,
        "reason": (
            "The injected baseline owns backend/, frontend/ or the root package files with "
            "different workspace names; this agent builds a TypeScript workspace and deploy.sh "
            "application, so the conflicting tree is moved aside instead of being mixed in."),
    })
    save_json(output_dir / HANDLING_REPORT, record)
    print(f"[BASELINE] Moved {len(moved)} injected entr"
        f"{'y' if len(moved) == 1 else 'ies'} to {backup}. See {HANDLING_REPORT}.", flush=True)
    return record


def enable_import_case_checks(output_dir: Path, workspace: str) -> str:
    """Upgrade existing TypeScript projects to detect case-dependent module imports."""
    relative = f"{workspace}/tsconfig.json"
    path = output_dir / relative
    configuration = json.loads(path.read_text(encoding="utf-8-sig"))
    options = configuration.setdefault("compilerOptions", {})
    if options.get("forceConsistentCasingInFileNames") is not True:
        options["forceConsistentCasingInFileNames"] = True
        save_json(path, configuration)
    return relative


def initialize_project(output_dir: Path, stack: str = DEFAULT_STACK, port: int = 3000) -> list[str]:
    # Templates contain infrastructure only. Existing application sources and
    # data are preserved; dependencies are installed separately by the TDD step.
    """Take over a foreign baseline, copy missing stack files, and return their paths."""
    if stack not in STACKS:
        raise ValueError(f"Unknown technology stack: {stack}. Available: {', '.join(STACKS)}")
    if not 1 <= port <= 65535:
        raise ValueError("Backend port must be between 1 and 65535")
    configuration = STACKS[stack]
    output_dir = output_dir.resolve()
    templates = configuration["templates"]
    if not templates.is_dir():
        raise ValueError(f"Stack templates do not exist: {templates}")
    handling = take_over_foreign_baseline(output_dir)
    if handling.get("action") == "kept_by_request":
        print(f"[BASELINE] {KEEP_BASELINE_ENV}=1: keeping the injected application and "
            "skipping this compiler's scaffold.", flush=True)
        return []
    created = []
    for source in sorted(templates.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(templates)
        content = source.read_text(encoding="utf-8-sig")
        if relative.as_posix() == "backend/src/server.ts":
            content = content.replace('process.env.PORT ?? "3000"', f'process.env.PORT ?? "{port}"')
        elif relative.as_posix() == "frontend/vite.config.ts":
            content = content.replace("http://127.0.0.1:3000", f"http://127.0.0.1:{port}")
        target = output_dir / relative
        if not target.resolve().is_relative_to(output_dir):
            raise ValueError(f"Project path escapes the output directory: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        except FileExistsError:
            if not target.is_file():
                raise ValueError(f"Expected a project file: {target}")
            continue
        created.append(relative.as_posix())
    for relative in configuration["directories"]:
        target = output_dir / relative
        if not target.resolve().is_relative_to(output_dir):
            raise ValueError(f"Project directory escapes the output directory: {relative}")
        target.mkdir(parents=True, exist_ok=True)
    return created
