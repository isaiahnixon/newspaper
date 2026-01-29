from dataclasses import replace
import argparse

from .config import DEFAULT_CONFIG
from .main import run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Daily AI Newspaper.")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging for each step of the pipeline.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip OpenAI API calls and use placeholder summaries.",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Enable deterministic test summaries instead of API calls.",
    )
    args = parser.parse_args()
    config = replace(
        DEFAULT_CONFIG,
        verbose=args.verbose,
        dry_run=args.dry_run,
        test_mode=args.test_mode,
    )
    run(config)
