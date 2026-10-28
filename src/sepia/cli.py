"""Command-line entry point for `sepia`."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from sepia import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sepia",
        description=(
            "Type a prompt, get a colored symbol painting in a second terminal window."
        ),
    )
    parser.add_argument("--version", action="version", version=f"sepia {__version__}")
    # Internal: the picture window runs `sepia --viewer <session file>`.
    parser.add_argument("--viewer", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.viewer is not None:
        from sepia.viewer import run_viewer

        return run_viewer(args.viewer)
    return 0
