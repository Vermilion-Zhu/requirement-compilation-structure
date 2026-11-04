"""Step 12: connect frontend triggers to backend APIs through functional smoke tests."""

from contextlib import ExitStack
from infrastructure.stages.passes.implement_frontend_triggers import implement_frontend_triggers

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log


def main() -> None:
    parser = create_parser("Step 12: Frontend/Backend Integration with Playwright Functional Smoke Tests")
    parser.add_argument("--max-turns", type=int, default=20, help="Maximum edit rounds per requirement's test/implementation agent")
    parser.add_argument("--max-tests", type=int, default=2, help="Maximum functional smoke cases per requirement (default: 2)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            result = implement_frontend_triggers(input_dir, output_dir / ".arc", args.pause, args.max_turns, args.max_tests)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")

    if result["status"] == "COMPLETED_WITH_FAILURES":
        parser.exit(1, "All implementation tasks were attempted; some acceptance checks failed. See the .arc report.\n")


if __name__ == "__main__":
    main()
