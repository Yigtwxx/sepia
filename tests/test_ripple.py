import re

import numpy as np
import pytest

from sepia.ascii_art import SymbolArt
from sepia.ripple import DURATION, MAX_SHIFT, Ripple, ripple_ansi, spaced

TOKEN = re.compile(
    r"\x1b\[(\d+);(\d+)H|\x1b\[38;2;(\d+);(\d+);(\d+)m|\x1b\[[0-9;]*m|(.)", re.DOTALL
)
BACKGROUND = re.compile(r"\x1b\[48;2;(\d+);(\d+);(\d+)m")
NOW = 100.0
CENTER = (30, 10)

Cells = dict[tuple[int, int], tuple[str, tuple[int, int, int]]]


def _art(cols: int = 60, rows: int = 20, bg: bool = False) -> SymbolArt:
    """Gray cells whose character names their column: chr(65 + col)."""
    letters = np.array([[chr(65 + x) for x in range(cols)] for _ in range(rows)])
    gray = np.full((rows, cols, 3), 100, dtype=np.uint8)
    return SymbolArt(letters, gray, gray.copy() if bg else None)


def _cells(ansi: str) -> Cells:
    """Every cell the escapes draw, by (row, col), with its character and color."""
    cells: Cells = {}
    row = col = 0
    fg = (0, 0, 0)
    for match in TOKEN.finditer(ansi):
        if match[1]:
            row, col = int(match[1]) - 1, int(match[2]) - 1
        elif match[3]:
            fg = (int(match[3]), int(match[4]), int(match[5]))
        elif match[6] is not None:
            cells[row, col] = (match[6], fg)
            col += 1
    return cells


def _frame(age: float, art: SymbolArt | None = None) -> Cells:
    ansi, _ = ripple_ansi(art or _art(), [Ripple(*CENTER, NOW - age)], NOW, None)
    return _cells(ansi)


def test_spaced_first_drop_is_always_spaced() -> None:
    assert spaced(None, (3, 3)), "The first pointer report must drop a ring"


@pytest.mark.parametrize(
    ("last", "point", "expected"),
    [
        ((10, 5), (12, 5), False),
        ((10, 5), (15, 5), True),
        ((10, 5), (10, 8), True),
        ((10, 5), (11, 6), False),
    ],
)
def test_spaced_counts_rows_as_two_cell_widths(last, point, expected) -> None:
    got = spaced(last, point)
    assert got == expected, f"{last} -> {point}: expected {expected}, got {got}"


def test_ripple_ansi_without_rings_or_drawn_cells_writes_nothing() -> None:
    ansi, changed = ripple_ansi(_art(), [], NOW, None)
    assert ansi == "", f"Nothing to draw, but got {ansi!r}"
    assert not changed.any(), "No cell may be marked as changed"


def test_ripple_ansi_spent_ring_changes_nothing() -> None:
    ripples = [Ripple(*CENTER, NOW - DURATION)]
    ansi, changed = ripple_ansi(_art(), ripples, NOW, None)
    assert ansi == "" and not changed.any(), "A ring past its life must not show"


def test_ripple_ansi_crest_lifts_the_colors_toward_white() -> None:
    cells = _frame(0.4)  # a ring 10 cell widths out
    _, crest = cells[CENTER[1], CENTER[0] + 10]
    assert crest[0] > 100 and len(set(crest)) == 1, (
        f"Crest must be lighter gray: {crest}"
    )
    assert (CENTER[1], CENTER[0]) not in cells, "The calm middle must not be redrawn"


def test_ripple_ansi_troughs_beside_the_crest_darken_the_colors() -> None:
    cells = _frame(0.4)  # crest 10 cell widths out, troughs about 4 either side
    row = CENTER[1]
    outer, inner = cells[row, CENTER[0] + 14][1], cells[row, CENTER[0] + 6][1]
    assert outer[0] < 100 and inner[0] < 100, f"Troughs must be darker: {outer} {inner}"


def test_ripple_ansi_bends_the_picture_away_from_the_crest_line() -> None:
    cells = _frame(0.2)  # a ring 5 cell widths out
    row = CENTER[1]
    # Characters name their source column, so `moved` is how far each cell looks.
    moved = {x: ord(cells[row, x][0]) - 65 - x for x in range(60) if (row, x) in cells}
    outside = [moved.get(x, 0) for x in range(CENTER[0] + 6, CENTER[0] + 10)]
    inside = [moved.get(x, 0) for x in range(CENTER[0] + 1, CENTER[0] + 5)]
    assert max(outside) > 0 and min(outside) >= 0, f"Outside looks outward: {outside}"
    assert min(inside) < 0 and max(inside) <= 0, f"Inside looks inward: {inside}"
    assert all(abs(step) <= MAX_SHIFT for step in moved.values()), f"Too far: {moved}"


def test_ripple_ansi_ring_travels_outward_with_age() -> None:
    def farthest(age: float) -> int:
        return max(abs(x - CENTER[0]) for y, x in _frame(age) if y == CENTER[1])

    young, old = farthest(0.2), farthest(0.6)
    assert young < old, f"The ring must spread: {young} cells, then {old}"


def test_ripple_ansi_fill_style_lifts_the_background_too() -> None:
    ansi, _ = ripple_ansi(_art(bg=True), [Ripple(*CENTER, NOW - 0.4)], NOW, None)
    lightest = max(int(match[1]) for match in BACKGROUND.finditer(ansi))
    assert lightest > 100, f"Crest backgrounds must be lighter, got {lightest}"


def test_ripple_ansi_heals_drawn_cells_no_ring_touches() -> None:
    art = _art()
    drawn = np.zeros((art.rows, art.cols), dtype=bool)
    drawn[2, 5] = True
    ansi, changed = ripple_ansi(art, [], NOW, drawn)
    assert _cells(ansi) == {(2, 5): ("F", (100, 100, 100))}, f"Got {ansi!r}"
    assert not changed.any(), "A healed picture has no changed cells"


def test_ripple_ansi_ring_in_the_corner_stays_on_the_picture() -> None:
    art = _art()
    ansi, changed = ripple_ansi(art, [Ripple(0, 0, NOW - 0.5)], NOW, None)
    cells = _cells(ansi)
    assert cells, "A ring in the corner must still show"
    assert all(0 <= y < art.rows and 0 <= x < art.cols for y, x in cells), (
        f"Drew off the picture: {sorted(cells)[-3:]}"
    )
    assert changed.shape == (art.rows, art.cols), f"Mask shape {changed.shape}"
