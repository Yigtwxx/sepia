"""/copy: the picture in the window as plain text on the clipboard."""

import shutil
import subprocess
import sys
from collections.abc import Sequence

from PIL import Image

from sepia.ascii_art import CELL_HEIGHT, CELL_WIDTH, Charset, image_to_art
from sepia.raster import enhance, fit_image
from sepia.scene import Canvas

COPY_COLS = 60
"""Widest copy, in characters. Discord wraps a code block's longer rows at its
spaces (about 72 characters fit beside the member list on a 1920 px screen), which
breaks the picture apart; 60 leaves room for smaller windows."""
COPY_LIMIT = 2000
"""Longest copy, fences included: what Discord takes in one message."""
FENCE = "```"
"""Code fence: Discord, Slack and GitHub show what it wraps in a monospace font."""
COPY_SECONDS = 5.0
"""How long the clipboard tool may take."""
LINUX_TOOLS: tuple[tuple[str, ...], ...] = (
    ("wl-copy",),
    ("xclip", "-selection", "clipboard"),
    ("xsel", "--clipboard", "--input"),
)
"""Clipboard tools tried in turn on Linux: Wayland's, then the two X11 ones."""


class ClipboardError(Exception):
    """The text could not be put on the clipboard."""


def _rows(cols: int, canvas: Canvas) -> int:
    """Rows that keep `canvas`'s shape at `cols` columns."""
    return max(1, round(cols * canvas.rows / max(1, canvas.cols)))


def _longest(cols: int, rows: int) -> int:
    """The fenced text's length with every row full: two fence lines, their two
    newlines, and each row with its newline (the last row's is a fence's)."""
    return rows * (cols + 1) + 2 * len(FENCE) + 1


def copy_size(canvas: Canvas) -> Canvas:
    """The copy's grid: `canvas`'s shape, at most `COPY_COLS` wide, shrunk until
    the fenced text fits `COPY_LIMIT`. Rows are capped last, so even a window of an
    absurd shape fits."""
    cols = max(1, min(COPY_COLS, canvas.cols))
    rows = _rows(cols, canvas)
    while cols > 1 and _longest(cols, rows) > COPY_LIMIT:
        cols -= 1
        rows = _rows(cols, canvas)
    rows = min(rows, (COPY_LIMIT - _longest(cols, 0)) // (cols + 1))
    return Canvas(cols, rows)


def fence(lines: Sequence[str]) -> str:
    """`lines` between fence lines, without trailing spaces, and with each backtick
    turned into a dot of about the same ink, so no row can close the fence."""
    body = [line.replace("`", ".").rstrip(" ") for line in lines]
    return "\n".join([FENCE, *body, FENCE])


def art_text(image: Image.Image, canvas: Canvas, charset: Charset) -> str:
    """`image` drawn as the viewer draws it, on the copy's grid, as fenced text.
    The symbols do not depend on the style, only their colors do."""
    size = copy_size(canvas)
    pixels = fit_image(enhance(image), size.cols * CELL_WIDTH, size.rows * CELL_HEIGHT)
    art = image_to_art(pixels, size.cols, size.rows, charset=charset)
    return fence(art.lines())


def _command() -> list[str]:
    """The tool that takes text on its standard input and puts it on the clipboard."""
    if sys.platform == "win32":
        return ["clip"]
    if sys.platform == "darwin":
        return ["pbcopy"]
    for tool in LINUX_TOOLS:
        if shutil.which(tool[0]):
            return list(tool)
    raise ClipboardError("no clipboard tool found; install wl-copy or xclip")


def copy_text(text: str) -> None:
    """Put `text` on the clipboard with the operating system's own tool. Its output
    goes nowhere: `wl-copy` and `xclip` leave a process behind that holds the
    clipboard, and a pipe it inherited would keep `run` waiting for it."""
    command = _command()
    name = command[0]
    try:
        subprocess.run(
            command,
            input=text.encode(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=COPY_SECONDS,
        )
    except subprocess.CalledProcessError as exc:
        raise ClipboardError(f"{name} exited with code {exc.returncode}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ClipboardError(f"{name} did not finish in time") from exc
    except OSError as exc:
        raise ClipboardError(f"could not run {name}") from exc
