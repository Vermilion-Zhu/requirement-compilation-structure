"""Compile a requirement directory into an executable application.

ARC-Bench launches this entrypoint as::

    python3 /workspace/submission/main.py <requirements-directory> --output-dir <app-root>

The runner also exposes the same locations and the task type as ``ARCBENCH_*``
environment variables. Command-line arguments win; the environment only supplies
defaults, so the documented invocation keeps working unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from infrastructure.compiler import Compiler
from infrastructure.utils.cli import resolve_directories
from infrastructure.utils.presentation.logging import configure_console


SUPPORTED_TASK_TYPES = {"web"}


def _first_env(*names: str) -> str | None:
    """Return the first non-empty environment value, so one location has one source."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read public options and validate paths, port and task type before compilation."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("requirement_path", type=Path, nargs="?",
        default=None,
        help="Requirement directory containing requirements.yaml and reference assets "
             "(default: $ARCBENCH_TASK_DIR)")
    parser.add_argument("-o", "--output-dir", type=Path, default=None,
        help="Directory for the generated application and .arc artifacts "
             "(default: $ARCBENCH_OUTPUT_DIR)")
    parser.add_argument("--model-log", "--debug-model-io", dest="model_log", action="store_true",
        help="Show detailed model I/O and save per-call prompt/response logs; usage and timing are always shown")
    parser.add_argument("--port", type=int, default=3000,
        help="Default generated backend port and frontend API proxy target (default: 3000)")
    default_engine = "staged"
    release = Path(__file__).with_name("agent-release.json")
    if release.is_file():
        try:
            default_engine = json.loads(release.read_text(encoding="utf-8"))["engine"]
            if default_engine not in {"staged", "react"}:
                raise ValueError("Unknown release engine")
        except (OSError, ValueError, KeyError, TypeError) as error:
            parser.error(f"Invalid agent-release.json: {error}")
    parser.add_argument("--engine", choices=("staged", "react"), default=default_engine,
        help="Execution engine (default from agent-release.json, otherwise staged)")
    parser.add_argument("--type", dest="task_type",
        default=os.environ.get("ARCBENCH_TASK_TYPE", "").strip() or "web",
        help="ARC-Bench task type; only 'web' is implemented (default: $ARCBENCH_TASK_TYPE or web)")
    args = parser.parse_args(argv)

    # The runner may supply locations only through the environment.
    if args.requirement_path is None:
        fallback = _first_env("ARCBENCH_TASK_DIR", "ARCBENCH_REQUIREMENT_DIR")
        if fallback:
            args.requirement_path = Path(fallback)
    if args.output_dir is None:
        fallback = _first_env("ARCBENCH_OUTPUT_DIR", "ARCBENCH_PROJECT_DIR")
        if fallback:
            args.output_dir = Path(fallback)

    try:
        if args.requirement_path is None:
            raise ValueError("a requirements directory is required")
        if args.output_dir is None:
            raise ValueError("--output-dir is required (or set ARCBENCH_OUTPUT_DIR)")
        if not 1 <= args.port <= 65535:
            raise ValueError("--port must be between 1 and 65535")
        args.requirement_path, args.output_dir = resolve_directories(
            argparse.Namespace(input=args.requirement_path, output=args.output_dir))
        if not args.requirement_path.is_dir():
            raise ValueError(f"Input directory does not exist: {args.requirement_path}")
        if not (args.requirement_path / "requirements.yaml").is_file():
            raise ValueError(f"Missing requirement document: {args.requirement_path / 'requirements.yaml'}")
        if args.output_dir.exists() and not args.output_dir.is_dir():
            raise ValueError(f"Output must be a directory: {args.output_dir}")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return args


def has_runnable_application(output_dir: Path) -> bool:
    """Report whether the runner can build and start something from the output."""
    return (output_dir / "deploy.sh").is_file() and (output_dir / "package.json").is_file()


def main(argv: list[str] | None = None) -> None:
    configure_console()
    args = parse_args(argv)
    if args.task_type not in SUPPORTED_TASK_TYPES:
        print(f"Unsupported ARC-Bench task type: {args.task_type!r}. "
            f"This agent implements Web tasks ({', '.join(sorted(SUPPORTED_TASK_TYPES))}) only.",
            file=sys.stderr)
        raise SystemExit(1)
    if args.engine == "react":
        from infrastructure.react_agent.submission import compile_application
        try:
            cli = os.environ.get("REACT_PLAYWRIGHT_CLI", "").strip()
            report = compile_application(args.requirement_path, args.output_dir,
                playwright_cli=Path(cli) if cli else None, channel=os.environ.get("REACT_BROWSER_CHANNEL") or None,
                time_budget=float(os.environ.get("REACT_TIME_BUDGET", "900")),
                max_steps=int(os.environ.get("REACT_MAX_STEPS", "40")))
        except KeyboardInterrupt:
            raise SystemExit(130)
        except Exception as error:
            print(f"Experimental ReAct compilation failed: {error}", file=sys.stderr)
            raise SystemExit(1)
        print(f"ReAct result {report['status']}. Report saved to {args.output_dir / '.arc/react-submission.json'}")
        raise SystemExit(0 if report["status"] == "ACCEPTANCE_PASSED" else 1)
    compiler = Compiler(args.requirement_path, args.output_dir, model_log=args.model_log, port=args.port)
    try:
        compiler.compile()
    except KeyboardInterrupt:
        print(f"Compilation interrupted at {compiler.current_stage or 'startup'}.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        # Keep a partially built application scoreable, but never report success
        # when the runner has nothing it can start.
        print(f"Compilation failed at {compiler.current_stage or 'startup'}: {error}", file=sys.stderr)
        raise SystemExit(0 if has_runnable_application(args.output_dir) else 1)
    if compiler.report["status"] == "COMPLETED_WITH_FAILURES":
        print(f"All passes completed. Report: {compiler.arc_dir / 'compilation.json'}", file=sys.stderr)
        raise SystemExit(0)


if __name__ == "__main__":
    main()
