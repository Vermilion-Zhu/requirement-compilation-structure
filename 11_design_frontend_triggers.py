"""Step 11: Frontend trigger design."""

from contextlib import ExitStack
from infrastructure.stages.passes.design_frontend_triggers import design_frontend_triggers

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log


def main() -> None:
    parser = create_parser("Step 11: Frontend Trigger Design")
    parser.add_argument("--max-attempts", type=int, default=10,
        help="Maximum proposals per trigger design; including the first proposal (default: 10)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            input_dir, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            design_frontend_triggers(input_dir, output_dir / ".arc", args.pause, args.max_attempts)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
