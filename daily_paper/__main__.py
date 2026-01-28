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
    args = parser.parse_args()
    config = replace(DEFAULT_CONFIG, verbose=args.verbose)
    run(config)
