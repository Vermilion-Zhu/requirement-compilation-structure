"""Step 10: implement the saved UI/data design through UI existence TDD."""

from contextlib import ExitStack
from infrastructure.stages.passes.implement_frontend_ui import implement_frontend_ui

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log


def main() -> None:
    parser = create_parser("Step 10: Playwright UI Existence Tests and UI Implementation TDD")
    parser.add_argument("--max-turns", type=int, default=10, help="Maximum edit/check turns per page implementation")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            result = implement_frontend_ui(input_dir, output_dir / ".arc", args.pause, args.max_turns)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")

    if result["status"] == "COMPLETED_WITH_FAILURES":
        parser.exit(1, "All implementation tasks were attempted; some acceptance checks failed. See the .arc report.\n")


if __name__ == "__main__":
    main()
