"""A sepia trail behind the mouse pointer: where it passes, the picture turns the
brown of an old photograph, then fades back to its own colors.

The pointer leaves a dab of tone every DAB_SPACING cell widths or less along its
path, the stretch between two pointer reports included, so a quick stroke stays
unbroken. A dab is a soft round brush that holds its strength, then fades out within
FADE seconds. Nothing moves: only the colors of the cells under the trail change.

The tone of a cell is kept in LEVELS steps, and a frame redraws only the cells whose
step changed since the last one, straight as ANSI escapes, so the trail can run at
30 frames a second on a picture of tens of thousands of cells.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from sepia.ascii_art import SymbolArt

ASPECT = 2.0
"""Cells are about twice as tall as wide; distances are measured in cell widths."""
BRUSH = 7.0
"""Spread (standard deviation) of a dab's tone, in cell widths. The picture window
is about 200 cells wide, so the trail is a soft stroke a few percent of it."""
FADE = 1.3
"""Seconds a dab lives. It keeps most of its tone at first and lets go at the end."""
STRENGTH = 0.95
"""Share of sepia in the middle of a fresh dab."""
LIFT = 0.2
"""How far fully toned ink moves toward white, so the trail reads on dark ink too."""
WASH = (50, 34, 16)
"""The dim brown laid behind ink-style cells, which have no background of their
own, where the trail is at full strength; weaker tone lays a darker wash."""
LEVELS = 16
"""Steps of tone between none and full. A cell is redrawn only when its step
changes, and the eye cannot tell one step from the next."""
DAB_SPACING = 3.5
"""Most cell widths between two dabs along the pointer's path. Half the brush
spread, so the stroke shows no beads."""
MAX_STROKE = 24.0
"""A pointer that moved further than this, in cell widths, between two reports left
the picture and came back: its trail starts again instead of bridging the gap."""
MAX_DABS = 160
"""Dabs alive at once; the oldest go first."""
FRAME_SECONDS = 1 / 30

_REACH = 2.65
"""Spreads (BRUSH widths) from a dab's middle at which its tone rounds to step 0."""
_SEPIA = np.array([[0.393, 0.769, 0.189], [0.349, 0.686, 0.168], [0.272, 0.534, 0.131]])
"""The classic sepia filter: each row mixes red, green and blue into one channel."""


def _kernel() -> npt.NDArray[np.float64]:
    """A whole-strength dab's tone around its middle cell, out to `_REACH`."""
    half_width = math.ceil(_REACH * BRUSH)
    half_height = math.ceil(_REACH * BRUSH / ASPECT)
    ys, xs = np.mgrid[-half_height : half_height + 1, -half_width : half_width + 1]
    distance2 = xs**2 + (ys * ASPECT) ** 2
    result: npt.NDArray[np.float64] = np.exp(-distance2 / (2.0 * BRUSH * BRUSH))
    return result


_KERNEL = _kernel()

Levels = npt.NDArray[np.uint8]
Colors = npt.NDArray[np.uint8]
Field = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Dab:
    """A dab of tone centered on cell (col, row), laid at `born`, monotonic seconds."""

    col: int
    row: int
    born: float


def dabs_between(
    last: tuple[int, int] | None, point: tuple[int, int], now: float
) -> list[Dab]:
    """The dabs the pointer lays going from `last`, where it laid its last dab, to
    `point`: evenly spaced, at most DAB_SPACING apart and ending on `point`, or none
    until it has moved that far. Without a `last`, or after a jump past MAX_STROKE,
    the trail starts again with one dab on `point`."""
    if last is None:
        return [Dab(point[0], point[1], now)]
    dx, dy = point[0] - last[0], point[1] - last[1]
    distance = math.hypot(dx, dy * ASPECT)
    if distance > MAX_STROKE:
        return [Dab(point[0], point[1], now)]
    if distance < DAB_SPACING:
        return []
    steps = math.ceil(distance / DAB_SPACING)
    return [
        Dab(
            round(last[0] + dx * step / steps),
            round(last[1] + dy * step / steps),
            now,
        )
        for step in range(1, steps + 1)
    ]


def trail_ansi(
    art: SymbolArt, dabs: Sequence[Dab], now: float, shown: Levels | None
) -> tuple[str, Levels]:
    """One frame of the trail `dabs` leave at `now`, and the tone step of each cell.

    `shown` is what the previous frame returned. Only cells whose step changed are
    drawn; those back at step 0 are drawn as the picture itself, so it heals behind
    the trail.
    """
    shape = (art.rows, art.cols)
    share = np.zeros(shape)
    for dab in dabs:
        _stamp(dab, now, share)
    levels = np.rint(share * LEVELS).astype(np.uint8)
    before = shown if shown is not None and shown.shape == shape else None
    write = levels != 0 if before is None else levels != before
    if not write.any():
        return "", levels
    part = levels / LEVELS
    fg = _tone(art.fg, part, LIFT)
    if art.bg is None:
        wash = np.rint(np.multiply.outer(part, WASH)).astype(np.uint8)
        bg, plain = wash, levels == 0
    else:
        bg, plain = _tone(art.bg, part, 0.0), None
    out = [
        _row_ansi(
            y,
            np.flatnonzero(write[y]).tolist(),
            art.chars[y].tolist(),
            fg[y].tolist(),
            bg[y].tolist(),
            None if plain is None else plain[y].tolist(),
        )
        for y in np.flatnonzero(write.any(axis=1)).tolist()
    ]
    return "".join(out) + "\x1b[0m", levels


def _stamp(dab: Dab, now: float, share: Field) -> None:
    """Raise `share` to one dab's tone wherever the dab is stronger, in place."""
    age = now - dab.born
    if not 0.0 <= age < FADE:
        return
    strength = STRENGTH * (1.0 - (age / FADE) ** 2)
    rows, cols = share.shape
    half_height, half_width = _KERNEL.shape[0] // 2, _KERNEL.shape[1] // 2
    top, left = dab.row - half_height, dab.col - half_width
    y0, y1 = max(top, 0), min(dab.row + half_height + 1, rows)
    x0, x1 = max(left, 0), min(dab.col + half_width + 1, cols)
    if y0 >= y1 or x0 >= x1:
        return
    tone = strength * _KERNEL[y0 - top : y1 - top, x0 - left : x1 - left]
    window = share[y0:y1, x0:x1]
    np.maximum(window, tone, out=window)


def _tone(colors: Colors, part: Field, lift: float) -> Colors:
    """`colors` turned toward their sepia by `part`, a share per cell, then lifted
    toward white by `lift` of that share."""
    rgb = colors.astype(np.float64)
    sepia = np.minimum(rgb @ _SEPIA.T, 255.0)
    share = part[..., None]
    toned = rgb + (sepia - rgb) * share
    lifted = toned + (255.0 - toned) * (lift * share)
    result: Colors = np.rint(lifted).astype(np.uint8)
    return result


def _row_ansi(
    y: int,
    columns: list[int],
    chars: list[str],
    fg: list[list[int]],
    bg: list[list[int]],
    plain: list[bool] | None,
) -> str:
    """The cells at `columns` of row `y`: a cursor move before each run of
    neighbors, and a color escape only where the color changes. Cells in `plain`
    keep the terminal's own background."""
    parts: list[str] = []
    ink: list[int] | None = None
    back: list[int] | None = None  # None: the terminal's own background
    fresh = True
    after = -2
    for x in columns:
        if x != after + 1:
            parts.append(f"\x1b[{y + 1};{x + 1}H")
            ink, fresh = None, True  # a new run states both colors again
        after = x
        color = fg[x]
        if color != ink:
            parts.append(f"\x1b[38;2;{color[0]};{color[1]};{color[2]}m")
            ink = color
        shade = None if plain is not None and plain[x] else bg[x]
        if fresh or shade != back:
            if shade is None:
                parts.append("\x1b[49m")
            else:
                parts.append(f"\x1b[48;2;{shade[0]};{shade[1]};{shade[2]}m")
            back, fresh = shade, False
        parts.append(chars[x])
    return "".join(parts)
