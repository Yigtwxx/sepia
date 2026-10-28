"""A glitch around the mouse pointer: torn rows, corrupted glyphs, split colors.

Only the cells around the pointer are redrawn, straight as ANSI escapes, so the
effect can run at 30 frames a second on a picture of tens of thousands of cells.
"""

import random

from sepia.ascii_art import SymbolArt

RADIUS_X = 13
RADIUS_Y = 6
"""Half-size of the glitched area in cells; cells are about twice as tall as wide,
so this reads as roughly round."""
DURATION = 0.9
"""Seconds the glitch lingers and fades after the pointer stops."""
FRAME_SECONDS = 1 / 30
MAX_SHIFT = 5
"""How far, in cells, a torn row segment slides sideways."""

# How often each kind of damage happens at full strength, per row or per cell.
TEAR_RATE = 0.85
"""A row segment slides sideways."""
JUMP_RATE = 0.3
"""A row shows its neighbor above or below instead, so the area judders."""
NOISE_RATE = 0.7
"""A glyph turns into noise."""
SPLIT_RATE = 0.8
"""A cell's color splits: red from the left neighbor, green and blue from the right."""
FLASH_RATE = 0.25
"""A cell flashes magenta, cyan or white."""

NOISE = "░▒▓█▚▞#@%&$!?/\\|<>"
SPLIT_COLORS = ((255, 0, 170), (0, 255, 255), (255, 255, 255))
"""Magenta, cyan and white flashes, the usual colors of a broken signal."""

Cell = tuple[str, tuple[int, int, int], tuple[int, int, int] | None]


def area(art: SymbolArt, col: int, row: int) -> tuple[int, int, int, int]:
    """Rows [top, bottom) and columns [left, right) the glitch touches."""
    top, bottom = max(row - RADIUS_Y, 0), min(row + RADIUS_Y + 1, art.rows)
    left, right = max(col - RADIUS_X, 0), min(col + RADIUS_X + 1, art.cols)
    return top, bottom, left, right


def glitch_ansi(
    art: SymbolArt, col: int, row: int, strength: float, rng: random.Random
) -> str:
    """One frame of the glitch centered on (col, row); `strength` runs 1 -> 0."""
    top, bottom, left, right = area(art, col, row)
    out: list[str] = []
    for y in range(top, bottom):
        dy = (y - row) / RADIUS_Y
        shift = 0
        if rng.random() < TEAR_RATE * strength:
            shift = rng.randint(-MAX_SHIFT, MAX_SHIFT)
        source_row = y
        if rng.random() < JUMP_RATE * strength:
            source_row = min(max(y + rng.choice((-1, 1)), 0), art.rows - 1)
        cells: list[Cell] = []
        for x in range(left, right):
            dx = (x - col) / RADIUS_X
            # Strongest at the pointer, fading toward the edge of the ellipse.
            chance = max(0.0, 1.0 - (dx * dx + dy * dy)) ** 0.6 * strength
            source = min(max(x - shift, 0), art.cols - 1)
            char, fg, bg = _cell(art, source_row, source)
            if rng.random() < chance * NOISE_RATE:
                char = rng.choice(NOISE)
            if rng.random() < chance * SPLIT_RATE:
                red = _cell(art, source_row, max(source - 1, 0))[1][0]
                right_fg = _cell(art, source_row, min(source + 1, art.cols - 1))[1]
                fg = (red, right_fg[1], right_fg[2])
            if rng.random() < chance * FLASH_RATE:
                fg = rng.choice(SPLIT_COLORS)
            cells.append((char, fg, bg))
        out.append(_row_ansi(y, left, cells))
    return "".join(out) + "\x1b[0m"


def restore_ansi(art: SymbolArt, col: int, row: int) -> str:
    """The untouched cells of the area around (col, row)."""
    top, bottom, left, right = area(art, col, row)
    out = [
        _row_ansi(y, left, [_cell(art, y, x) for x in range(left, right)])
        for y in range(top, bottom)
    ]
    return "".join(out) + "\x1b[0m"


def _cell(art: SymbolArt, y: int, x: int) -> Cell:
    red, green, blue = (int(v) for v in art.fg[y, x])
    bg = None
    if art.bg is not None:
        bg_red, bg_green, bg_blue = (int(v) for v in art.bg[y, x])
        bg = (bg_red, bg_green, bg_blue)
    return str(art.chars[y, x]), (red, green, blue), bg


def _row_ansi(y: int, left: int, cells: list[Cell]) -> str:
    parts = [f"\x1b[{y + 1};{left + 1}H"]
    for char, (red, green, blue), bg in cells:
        parts.append(f"\x1b[38;2;{red};{green};{blue}m")
        if bg is not None:
            parts.append(f"\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m")
        else:
            parts.append("\x1b[49m")
        parts.append(char)
    return "".join(parts)
