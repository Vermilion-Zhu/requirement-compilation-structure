"""Local prototype tools. Commands execute with the runner's OS permissions."""

from pathlib import Path
import subprocess

from infrastructure.utils.processes import capture_process, npm_command
from infrastructure.utils.files import normalize_newlines, read_source, save_text


EXCLUDED = {"node_modules", ".git", ".arc", "dist", "__pycache__", ".venv"}


class Workspace:
    def __init__(self, output: Path, requirements: Path):
        self.output = output.resolve()
        self.requirements = requirements.resolve()
        self.revision = 0

    def path(self, name: str, *, write=False) -> Path:
        relative = Path(name)
        is_input = relative.parts and relative.parts[0] == "input"
        root = self.requirements if is_input else self.output
        target = (root / Path(*relative.parts[1:]) if is_input else root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Path escapes its workspace")
        parts = target.relative_to(root).parts
        if any(part in EXCLUDED or part.startswith(".env") for part in parts):
            raise ValueError("Use application sources and requirement materials")
        if is_input and any(part.lower() in {"tests", "test", "evaluator"} for part in parts):
            raise ValueError("Read original requirements and reference assets")
        if write and is_input:
            raise ValueError("Requirement materials are read-only")
        return target

    def execute(self, action: dict, *, timeout: float) -> dict:
        tool = action.get("tool")
        if tool == "list":
            directory = self.path(action.get("path", "."))
            entries = sorted(p.name + ("/" if p.is_dir() else "") for p in directory.iterdir()
                             if p.name not in EXCLUDED and not p.name.startswith(".env"))
            return {"entries": entries[:200], "truncated": len(entries) > 200}
        if tool == "read":
            path = self.path(action["path"])
            lines = read_source(path).splitlines()
            start = int(action.get("start", 1))
            count = min(int(action.get("lines", 200)), 400)
            if start < 1 or count < 1:
                raise ValueError("start and lines must be positive")
            text = "\n".join(f"{i+1}: {line}" for i, line in
                             enumerate(lines[start-1:start-1+count], start-1))
            return {"text": text[:24000], "total_lines": len(lines),
                    "truncated": len(text) > 24000 or start - 1 + count < len(lines)}
        if tool in {"write", "replace"}:
            path = self.path(action["path"], write=True)
            content = action.get("content")
            if tool == "replace":
                content = read_source(path)
                old = normalize_newlines(action["old"])
                if not old or content.count(old) != 1:
                    raise ValueError("Replacement must match exactly once")
                content = content.replace(old, action["new"], 1)
            if not isinstance(content, str):
                raise ValueError("content must be a string")
            save_text(path, content)
            self.revision += 1
            return {"written": action["path"], "revision": self.revision}
        if tool == "run":
            argv = action.get("argv")
            if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
                raise ValueError("argv must be a nonempty list of strings")
            if argv[0] in {"npm", "npx"}:
                command = npm_command()
                if argv[0] == "npx":
                    command = [*command[:-1], str(Path(command[-1]).with_name("npx-cli.js"))]
                argv = [*command, *argv[1:]]
            seconds = min(max(float(action.get("timeout", 90)), 1), 120, timeout)
            try:
                result = capture_process(argv, cwd=self.output, timeout=seconds)
            except subprocess.TimeoutExpired:
                return {"returncode": 124, "error": f"Command timed out after {seconds:.1f}s"}
            return {key: result[key] for key in ("returncode", "output", "elapsed_seconds")}
        raise ValueError(f"Unknown tool: {tool}")
