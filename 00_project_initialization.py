"""Step 00: initialize the application workspace for the selected technology stack."""

from contextlib import ExitStack
from infrastructure.stages.passes.project_initialization import project_initialization
from infrastructure.shared.project.initialize import DEFAULT_STACK, STACKS

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log


def main() -> None:
    parser = create_parser("Step 00: Project Initialization")
    parser.add_argument("--stack", choices=sorted(STACKS), default=DEFAULT_STACK, help="Technology stack; extend STACKS to register another template")
    parser.add_argument("--port", type=int, default=3000, help="Default backend port and frontend API proxy target (default: 3000)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            project_initialization(output_dir, args.pause, args.stack, args.port)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
