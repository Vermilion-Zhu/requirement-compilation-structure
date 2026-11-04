"""Step 09: design all leaf requirements' UI/data without implementing pages."""

from contextlib import ExitStack
from infrastructure.stages.passes.design_frontend_ui import design_frontend_ui

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log


def main() -> None:
    parser = create_parser("Step 09: UI/data Design with Page RAG")
    parser.add_argument("--top-k", type=int, default=3, help="Number of coarse page RAG candidates")
    parser.add_argument("--max-attempts", type=int, default=10, help="Maximum proposals per requirement; including the first proposal (default: 10)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            design_frontend_ui(input_dir, output_dir / ".arc", args.pause, args.top_k, args.max_attempts)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
