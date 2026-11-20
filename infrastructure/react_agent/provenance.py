"""Identify framework sources and base instructions used by an experimental run."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def fingerprint(instructions: str, *, root: Path = ROOT) -> dict:
    """Retain content identities even in an exported submission without Git metadata."""
    sources = {}
    for path in sorted((root / "infrastructure").rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or "__pycache__" in relative.parts:
            continue
        if path.suffix in {".py", ".ts"} or "templates" in relative.parts:
            sources[relative.as_posix()] = sha256(path.read_bytes()).hexdigest()
    for name in ("main.py", "requirements.txt", "agent-release.json"):
        path = root / name
        if path.is_file():
            sources[name] = sha256(path.read_bytes()).hexdigest()
    identity = json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()
    version = {"source_sha256": sha256(identity).hexdigest(), "files": sources,
               "instructions_sha256": sha256(instructions.encode("utf-8")).hexdigest(),
               "git_commit": None, "git_branch": None, "git_dirty_paths": None}
    if not (root / ".git").exists():
        return version
    try:
        for key, args in (("git_commit", ["rev-parse", "HEAD"]),
                          ("git_branch", ["branch", "--show-current"]),
                          ("git_dirty_paths", ["status", "--porcelain", "--untracked-files=all", "--",
                                               "infrastructure", "main.py", "requirements.txt"])):
            result = subprocess.run(["git", *args], cwd=root, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=5)
            if result.returncode == 0:
                value = result.stdout.strip()
                version[key] = value.splitlines() if key == "git_dirty_paths" else value
    except (OSError, subprocess.TimeoutExpired):
        pass
    return version
