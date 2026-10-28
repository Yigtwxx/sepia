"""Command-line entry point for `sepia`."""

import argparse
from collections.abc import Sequence

from sepia import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sepia",
        description=(
            "Type a prompt, get a colored symbol painting in a second terminal window."
        ),
    )
    parser.add_argument("--version", action="version", version=f"sepia {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
