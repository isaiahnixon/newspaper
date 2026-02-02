import argparse
from dataclasses import replace
from pathlib import Path

from .config import CONFIG_PATH, load_config
from .main import run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Daily AI Newspaper.")
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to the YAML configuration file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging for each step of the pipeline.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    if args.verbose:
        config = replace(config, verbose=True)
    run(config)
