"""Step 05: implement tables, per-table prerequisite inserts and real initialization."""

from contextlib import ExitStack
from infrastructure.stages.passes.implement_db import implement_db

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log


def main() -> None:
    parser = create_parser("Step 05: Implement DB Tables and Required Startup Data")
    parser.add_argument("--max-attempts", type=int, default=10, help="Maximum proposals per table or startup-data requirement (default: 10)")
    parser.add_argument("--max-turns", type=int, default=20, help="Maximum real database/startup repair rounds")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            implement_db(output_dir / ".arc", args.pause, args.max_attempts, args.max_turns)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
