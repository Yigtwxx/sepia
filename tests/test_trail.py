import re
from typing import NamedTuple

import numpy as np
import pytest

from sepia.ascii_art import SymbolArt
from sepia.trail import (
    BRUSH,
    DAB_SPACING,
    FADE,
    LEVELS,
    MAX_STROKE,
    Dab,
    dabs_between,
    trail_ansi,
)

TOKEN = re.compile(
    r"\x1b\[(\d+);(\d+)H"
    r"|\x1b\[38;2;(\d+);(\d+);(\d+)m"
    r"|\x1b\[48;2;(\d+);(\d+);(\d+)m"
    r"|\x1b\[(49)m"
    r"|\x1b\[[0-9;]*m"
    r"|(.)",
    re.DOTALL,
)
NOW = 100.0
CENTER = (30, 10)

Color = tuple[int, int, int]


class Cell(NamedTuple):
    char: str
    fg: Color
    bg: Color | None
    """None where the cell keeps the terminal's own background."""


Cells = dict[tuple[int, int], Cell]


def _art(cols: int = 60, rows: int = 20, bg: bool = False) -> SymbolArt:
    """Gray cells whose character names their column: chr(65 + col)."""
    letters = np.array([[chr(65 + x) for x in range(cols)] for _ in range(rows)])
    gray = np.full((rows, cols, 3), 100, dtype=np.uint8)
    return SymbolArt(letters, gray, gray.copy() if bg else None)


def _cells(ansi: str) -> Cells:
    """Every cell the escapes draw, by (row, col), with its character and colors.

    Colors carry over from cell to cell, as on a terminal, so a cell drawn with a
    stale color shows up here with that stale color."""
    cells: Cells = {}
    row = col = 0
    fg: Color = (0, 0, 0)
    bg: Color | None = None
    for match in TOKEN.finditer(ansi):
        if match[1]:
            row, col = int(match[1]) - 1, int(match[2]) - 1
        elif match[3]:
            fg = (int(match[3]), int(match[4]), int(match[5]))
        elif match[6]:
            bg = (int(match[6]), int(match[7]), int(match[8]))
        elif match[9]:
            bg = None
        elif match[10] is not None:
            cells[row, col] = Cell(match[10], fg, bg)
            col += 1
    return cells


def _frame(age: float, art: SymbolArt | None = None) -> Cells:
    ansi, _ = trail_ansi(art or _art(), [Dab(*CENTER, NOW - age)], NOW, None)
    return _cells(ansi)


def _warmth(color: Color) -> int:
    """How far a gray has turned sepia: red over blue."""
    return color[0] - color[2]


def test_dabs_between_first_report_lays_one_dab_on_the_pointer() -> None:
    dabs = dabs_between(None, (3, 4), NOW)
    assert dabs == [Dab(3, 4, NOW)], f"Expected one dab on the pointer, got {dabs}"


def test_dabs_between_move_shorter_than_the_spacing_lays_nothing() -> None:
    dabs = dabs_between((10, 5), (11, 5), NOW)
    assert dabs == [], f"One cell width is under {DAB_SPACING}, got {dabs}"


def test_dabs_between_long_move_fills_the_gap_and_ends_on_the_pointer() -> None:
    dabs = dabs_between((10, 5), (20, 5), NOW)
    gaps = np.diff([10] + [dab.col for dab in dabs])
    assert (dabs[-1].col, dabs[-1].row) == (20, 5), f"Last dab off the pointer: {dabs}"
    # Dabs sit on whole cells, so a gap may round up by one.
    assert len(dabs) > 1 and gaps.max() <= DAB_SPACING + 1, f"Gaps too wide: {gaps}"
    assert all(dab.born == NOW for dab in dabs), "Every dab must be laid now"


@pytest.mark.parametrize(
    ("point", "expected"),
    [((13, 5), 0), ((10, 7), 2), ((14, 5), 2)],
)
def test_dabs_between_counts_rows_as_two_cell_widths(
    point: tuple[int, int], expected: int
) -> None:
    got = len(dabs_between((10, 5), point, NOW))
    assert got == expected, f"(10, 5) -> {point}: expected {expected} dabs, got {got}"


def test_dabs_between_jump_past_max_stroke_starts_a_new_trail() -> None:
    far = (int(MAX_STROKE) + 10, 0)
    dabs = dabs_between((0, 0), far, NOW)
    assert dabs == [Dab(*far, NOW)], f"A jump must not be bridged, got {dabs}"


def test_trail_ansi_without_dabs_or_shown_cells_writes_nothing() -> None:
    ansi, levels = trail_ansi(_art(), [], NOW, None)
    assert ansi == "", f"Nothing to draw, but got {ansi!r}"
    assert not levels.any(), "No cell may carry tone"


def test_trail_ansi_faded_dab_changes_nothing() -> None:
    ansi, levels = trail_ansi(_art(), [Dab(*CENTER, NOW - FADE)], NOW, None)
    assert ansi == "" and not levels.any(), "A dab past its life must not show"


def test_trail_ansi_fresh_dab_turns_the_ink_under_it_sepia() -> None:
    fg = _frame(0.0)[CENTER[1], CENTER[0]].fg
    assert fg[0] > fg[1] > fg[2], f"Toned ink must be warm (red > green > blue): {fg}"
    assert fg[0] > 100, f"Toned ink must be lifted toward white: {fg}"


def test_trail_ansi_keeps_every_character_in_place() -> None:
    cells = _frame(0.1)
    moved = {(y, x): c.char for (y, x), c in cells.items() if c.char != chr(65 + x)}
    assert cells and not moved, f"Characters left their cells: {moved}"


def test_trail_ansi_tone_weakens_away_from_the_dab() -> None:
    cells = _frame(0.0)
    row, col = CENTER[1], CENTER[0]
    near, mid = cells[row, col].fg, cells[row, col + int(BRUSH)].fg
    assert _warmth(near) > _warmth(mid) > 0, f"Tone must fall off: {near} {mid}"


def test_trail_ansi_tone_rounds_to_nothing_before_the_brush_edge() -> None:
    _, levels = trail_ansi(_art(), [Dab(*CENTER, NOW)], NOW, None)
    row, col = CENTER[1], CENTER[0]
    edge = col + int(2.8 * BRUSH)
    assert levels[row, col] > 0, "The dab's middle must carry tone"
    assert levels[row, edge] == 0, f"Tone left at {edge}: {levels[row, edge]}"


def test_trail_ansi_tone_fades_with_age() -> None:
    young = _frame(0.2)[CENTER[1], CENTER[0]].fg
    old = _frame(FADE * 0.8)[CENTER[1], CENTER[0]].fg
    assert _warmth(young) > _warmth(old), f"The trail must fade: {young}, then {old}"


def test_trail_ansi_ink_style_lays_a_warm_wash_behind_the_trail() -> None:
    bg = _frame(0.0)[CENTER[1], CENTER[0]].bg
    assert bg is not None and _warmth(bg) > 0, f"Expected a warm wash, got {bg}"
    assert max(bg) < 100, f"The wash must stay dim under the ink: {bg}"


def test_trail_ansi_fill_style_tones_the_background_too() -> None:
    bg = _frame(0.0, _art(bg=True))[CENTER[1], CENTER[0]].bg
    assert bg is not None and _warmth(bg) > 0, f"Expected a sepia background: {bg}"


def test_trail_ansi_unchanged_frame_writes_nothing() -> None:
    art, dabs = _art(), [Dab(*CENTER, NOW)]
    _, levels = trail_ansi(art, dabs, NOW, None)
    ansi, again = trail_ansi(art, dabs, NOW, levels)
    assert ansi == "", f"No cell changed its step, but got {len(ansi)} characters"
    assert np.array_equal(levels, again), "The steps must be the same"


def test_trail_ansi_redraws_only_cells_whose_step_changed() -> None:
    art, dabs = _art(), [Dab(*CENTER, NOW)]
    _, levels = trail_ansi(art, dabs, NOW, None)
    ansi, later = trail_ansi(art, dabs, NOW + 0.5, levels)
    redrawn = set(_cells(ansi))
    stepped = set(zip(*np.nonzero(later != levels), strict=True))
    assert redrawn == stepped, f"Redrew {len(redrawn)} cells, {len(stepped)} stepped"


def test_trail_ansi_heals_shown_cells_the_trail_has_left() -> None:
    art = _art()
    shown = np.zeros((art.rows, art.cols), dtype=np.uint8)
    shown[2, 5] = 3
    ansi, levels = trail_ansi(art, [], NOW, shown)
    cells = _cells(ansi)
    assert cells == {(2, 5): Cell("F", (100, 100, 100), None)}, f"Got {ansi!r}"
    assert not levels.any(), "A healed picture carries no tone"


def test_trail_ansi_run_mixing_toned_and_healed_cells_sets_each_background() -> None:
    art = _art()
    shown = np.zeros((art.rows, art.cols), dtype=np.uint8)
    shown[CENTER[1]] = LEVELS  # higher than any dab reaches: the whole row redraws
    ansi, _ = trail_ansi(art, [Dab(*CENTER, NOW)], NOW, shown)
    row = [_cells(ansi)[CENTER[1], x] for x in range(art.cols)]
    assert row[CENTER[0]].bg is not None, "The middle of the trail needs its wash"
    healed = [cell for cell in row if cell.bg is None]
    assert healed and all(cell.fg == (100, 100, 100) for cell in healed), (
        f"Healed cells must be the picture itself: {healed[:2]}"
    )
    moves = re.findall(rf"\x1b\[{CENTER[1] + 1};\d+H", ansi)
    assert len(moves) == 1, f"The whole row must be one run, got {moves}"


def test_trail_ansi_dab_in_the_corner_stays_on_the_picture() -> None:
    art = _art()
    ansi, levels = trail_ansi(art, [Dab(0, 0, NOW - 0.1)], NOW, None)
    cells = _cells(ansi)
    assert cells, "A dab in the corner must still show"
    assert all(0 <= y < art.rows and 0 <= x < art.cols for y, x in cells), (
        f"Drew off the picture: {sorted(cells)[-3:]}"
    )
    assert levels.shape == (art.rows, art.cols), f"Steps shape {levels.shape}"
