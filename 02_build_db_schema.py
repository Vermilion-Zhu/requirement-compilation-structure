"""Step 02: discover entities and fields incrementally using schema RAG."""

from contextlib import ExitStack
from infrastructure.stages.passes.build_db_schema import build_db_schema

from infrastructure.utils.cli import create_parser, resolve_directories
from infrastructure.utils.presentation.logging import console_log


def main() -> None:
    parser = create_parser("Step 02: Build DB Schema with RAG")
    parser.add_argument("--top-k", type=int, default=6, help="Number of BM25 entity/field hits (default: 6)")
    parser.add_argument("--max-attempts", type=int, default=10, help="Maximum proposals per requirement; including the first proposal (default: 10)")
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            _, output_dir = resolve_directories(args)
            stack.enter_context(console_log(output_dir, debug_model_io=args.debug_model_io))
            build_db_schema(output_dir / ".arc", args.pause, args.top_k, args.max_attempts)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Execution failed: {error}\n")


if __name__ == "__main__":
    main()
