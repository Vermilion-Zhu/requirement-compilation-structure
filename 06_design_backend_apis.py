"""Step 06: design complete APIs with interfaces, obligations and P/Q."""

from contextlib import ExitStack
from infrastructure.stages.passes.design_backend_apis import design_backend_apis

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log


def main() -> None:
    parser = create_parser("Step 06: Complete Backend API Design / Obligation Propagation")
    parser.add_argument("--top-k", type=int, default=6, help="Number of API retrieval hits")
    parser.add_argument("--max-attempts", type=int, default=10, help="Maximum proposals per requirement; including the first proposal (default: 10)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output = resolve_directories(args)
            stack.enter_context(console_log(output, debug_model_io=args.debug_model_io))
            design_backend_apis(output / ".arc", args.pause, args.top_k, args.max_attempts)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
