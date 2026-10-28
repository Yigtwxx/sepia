"""Command-line entry point for `sepia`."""

import argparse
import contextlib
import sys
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
    parser.add_argument(
        "--download",
        action="store_true",
        help="download the local image model (about 16 GB) used when the API fails",
    )
    # Internal: the picture window runs `sepia --viewer <session file>`.
    parser.add_argument("--viewer", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _use_utf8()
    args = build_parser().parse_args(argv)
    if args.viewer is not None:
        from sepia.viewer import run_viewer

        return run_viewer(args.viewer)
    if args.download:
        from sepia.painter import PainterError, download_local_model

        try:
            print(f"downloaded to {download_local_model()}")
        except PainterError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    from sepia.repl import run_repl

    return run_repl()


def _use_utf8() -> None:
    """Block and box glyphs need UTF-8 even where the console code page is not."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8")
