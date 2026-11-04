"""Step 04: display requirement/database field relations and read/write obligations."""

from contextlib import ExitStack
from infrastructure.stages.passes.check_db_obligations import check_db_obligations

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log


def main() -> None:
    """Display obligation records using the shared CLI and workspace log."""
    parser = create_parser("Step 04: Display DB Obligation Records")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            check_db_obligations(output_dir / ".arc", args.pause)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
