"""Ripples from the mouse pointer: rings that bend the picture and catch the light.

Each ring grows out of the spot where the pointer dropped it. As light through a
water wave would, its slope moves the picture a cell or two, its crest lifts the
colors toward white and the troughs either side of it darken them, and it fades
as it spreads. The pictures are already bright, so the dark troughs are what
make the crest stand out. Only the cells the rings touch are redrawn, straight
as ANSI escapes, so a trail of rings can run at 30 frames a second on a picture
of tens of thousands of cells.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from sepia.ascii_art import SymbolArt

ASPECT = 2.0
"""Cells are about twice as tall as wide; distances are measured in cell widths."""
REACH = 25.0
"""How far a ring travels before it is gone, in cell widths."""
DURATION = 1.0
"""Seconds a ring lives."""
WIDTH = 3.5
"""Half-width of a ring's crest, in cell widths."""
MAX_SHIFT = 3.0
"""How far, in cell widths, the steepest part of a fresh ring moves the picture.
Kept under WIDTH so one ring bends the picture without folding it over itself."""
LIGHT = 0.8
"""How far a fresh crest moves a cell's colors toward white; its troughs darken
them by up to 45% of this toward black."""
DROP_SPACING = 5.0
"""How far, in cell widths, the pointer moves before it drops the next ring."""
MAX_RIPPLES = 8
"""Rings alive at once; a new one replaces the oldest."""
FRAME_SECONDS = 1 / 30

_EDGE = 3.0
"""A ring reaches this many crest half-widths either side of its radius."""
_SLOPE_PEAK = math.sqrt(2) * math.exp(-0.5)
"""The largest value of 2u * exp(-u^2), so the steepest point moves MAX_SHIFT."""
_FAINT = 0.02
"""Light below this share does not show and is not drawn."""

Mask = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class Ripple:
    """A ring growing from cell (col, row) since `born`, in monotonic seconds."""

    col: int
    row: int
    born: float


def spaced(last: tuple[int, int] | None, point: tuple[int, int]) -> bool:
    """Whether the pointer at `point` is far enough from the last drop for a ring."""
    if last is None:
        return True
    distance = math.hypot(point[0] - last[0], (point[1] - last[1]) * ASPECT)
    return distance >= DROP_SPACING


def ripple_ansi(
    art: SymbolArt, ripples: Sequence[Ripple], now: float, drawn: Mask | None
) -> tuple[str, Mask]:
    """One frame of `ripples` at `now`, and the mask of cells it leaves changed.

    `drawn` is the mask the previous frame returned. Its cells that no ring
    touches any more are redrawn as they are, so the picture heals behind the
    rings.
    """
    shape = (art.rows, art.cols)
    shift_x, shift_y, light = np.zeros(shape), np.zeros(shape), np.zeros(shape)
    for ripple in ripples:
        _add(ripple, now, shift_x, shift_y, light)
    rows, cols = np.indices(shape)
    source_x = np.clip(np.rint(cols + shift_x).astype(np.intp), 0, art.cols - 1)
    source_y = np.clip(np.rint(rows + shift_y).astype(np.intp), 0, art.rows - 1)
    light = np.clip(light, -1.0, 1.0)
    light[np.abs(light) < _FAINT] = 0.0
    changed = (source_x != cols) | (source_y != rows) | (light != 0.0)
    write = changed if drawn is None or drawn.shape != shape else changed | drawn
    if not write.any():
        return "", changed
    chars = art.chars[source_y, source_x]
    fg = _shade(art.fg[source_y, source_x], light)
    bg = None if art.bg is None else _shade(art.bg[source_y, source_x], light)
    out = [
        _run_ansi(y, run, chars, fg, bg)
        for y in np.flatnonzero(write.any(axis=1)).tolist()
        for run in _runs(np.flatnonzero(write[y]))
    ]
    return "".join(out) + "\x1b[0m", changed


def _add(
    ripple: Ripple,
    now: float,
    shift_x: npt.NDArray[np.float64],
    shift_y: npt.NDArray[np.float64],
    light: npt.NDArray[np.float64],
) -> None:
    """Add one ring's bend and light to the frame's fields, in place."""
    age = now - ripple.born
    if not 0.0 <= age < DURATION:
        return
    fade = 1.0 - age / DURATION
    radius = REACH * age / DURATION
    outer = radius + _EDGE * WIDTH
    rows, cols = light.shape
    top = max(math.floor(ripple.row - outer / ASPECT), 0)
    bottom = min(math.ceil(ripple.row + outer / ASPECT) + 1, rows)
    left = max(math.floor(ripple.col - outer), 0)
    right = min(math.ceil(ripple.col + outer) + 1, cols)
    if top >= bottom or left >= right:
        return
    ys, xs = np.mgrid[top:bottom, left:right]
    dx = (xs - ripple.col).astype(np.float64)
    dy = (ys - ripple.row) * ASPECT
    distance = np.hypot(dx, dy)
    u = (distance - radius) / WIDTH
    crest = np.exp(-u * u)
    # Each cell shows the picture from a little further along its own radius,
    # by the ring's slope there, as a lens would.
    push = MAX_SHIFT * fade * 2.0 * u * crest / _SLOPE_PEAK
    reach = np.maximum(distance, 1e-9)
    shift_x[top:bottom, left:right] += push * dx / reach
    shift_y[top:bottom, left:right] += push * dy / reach / ASPECT
    # A bright crest with a dark trough either side: (1 - 2u^2) * exp(-u^2).
    light[top:bottom, left:right] += LIGHT * fade * (1.0 - 2.0 * u * u) * crest


def _shade(
    colors: npt.NDArray[np.uint8], light: npt.NDArray[np.float64]
) -> npt.NDArray[np.uint8]:
    """`colors` moved toward white by a positive `light`, toward black by a negative
    one, a share per cell."""
    share = light[..., None]
    shaded = np.where(
        share > 0, colors + (255.0 - colors) * share, colors * (1 + share)
    )
    return np.rint(shaded).astype(np.uint8)


def _runs(columns: npt.NDArray[np.intp]) -> list[npt.NDArray[np.intp]]:
    """Sorted column numbers split where they stop being consecutive."""
    return np.split(columns, np.flatnonzero(np.diff(columns) != 1) + 1)


def _run_ansi(
    y: int,
    run: npt.NDArray[np.intp],
    chars: npt.NDArray[np.str_],
    fg: npt.NDArray[np.uint8],
    bg: npt.NDArray[np.uint8] | None,
) -> str:
    parts = [f"\x1b[{y + 1};{int(run[0]) + 1}H"]
    if bg is None:
        parts.append("\x1b[49m")  # once per run: ink cells keep the default
    color = ""
    for x in run:
        red, green, blue = (int(v) for v in fg[y, x])
        cell = f"\x1b[38;2;{red};{green};{blue}m"
        if bg is not None:
            bg_red, bg_green, bg_blue = (int(v) for v in bg[y, x])
            cell += f"\x1b[48;2;{bg_red};{bg_green};{bg_blue}m"
        if cell != color:
            parts.append(cell)
            color = cell
        parts.append(str(chars[y, x]))
    return "".join(parts)
