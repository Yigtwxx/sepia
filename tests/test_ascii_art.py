import re
from collections.abc import Callable

import numpy as np
import pytest

from sepia.ascii_art import (
    CELL_HEIGHT,
    CELL_WIDTH,
    RAMPS,
    SymbolArt,
    image_to_art,
    to_ansi,
    to_text,
)

Canvas = Callable[..., np.ndarray]  # the `make_canvas` fixture from conftest.py
RAMP_ORDER = [char for char, _ in RAMPS["symbols"]]


@pytest.mark.parametrize("charset", ["classic", "symbols"])
def test_ramp_densities_strictly_increase(charset: str) -> None:
    densities = [density for _, density in RAMPS[charset]]
    assert densities == sorted(set(densities)), f"{charset} ramp out of order"


def test_ramp_symbols_include_requested_and_exclude_outlines() -> None:
    chars = set(RAMP_ORDER)
    assert set("!'^+%&(") <= chars, f"Missing requested symbols in {chars}"
    overlap = chars & set("/\\|-_")
    assert not overlap, f"Outline glyphs must stay out of the ramp, found {overlap}"


def test_image_to_art_grid_matches_requested_shape(make_canvas: Canvas) -> None:
    art = image_to_art(make_canvas(12, 5), cols=12, rows=5, style="ink")
    assert (art.rows, art.cols) == (5, 12), f"Expected 5x12, got {art.rows}x{art.cols}"
    assert art.fg.shape == (5, 12, 3), f"Expected fg (5, 12, 3), got {art.fg.shape}"
    assert art.bg is None, "Ink style must not paint a background"


@pytest.mark.parametrize(("value", "expected"), [(0, {" "}), (255, {"@"})])
def test_image_to_art_solid_image_uses_one_symbol(
    make_canvas: Canvas, value: int, expected: set[str]
) -> None:
    chars = set("".join(image_to_art(make_canvas(4, 2, value), 4, 2).lines()))
    assert chars == expected, f"Expected {expected}, got {chars}"


def test_image_to_art_smooth_gradient_gets_denser_without_outlines(
    make_canvas: Canvas,
) -> None:
    img = make_canvas(16, 2)
    img[:, :, :] = np.linspace(0, 255, 16 * CELL_WIDTH).astype(np.uint8)[None, :, None]
    line = image_to_art(img, 16, 2, charset="symbols").lines()[0]
    positions = [RAMP_ORDER.index(char) for char in line]  # raises on outline glyphs
    assert positions == sorted(positions), f"Density not increasing: {line!r}"
    assert positions[0] < positions[-1], f"Gradient collapsed to one symbol: {line!r}"


def test_image_to_art_vertical_step_draws_single_vertical_outline(
    make_canvas: Canvas,
) -> None:
    img = make_canvas(8, 3)
    img[:, 4 * CELL_WIDTH :] = 255
    lines = image_to_art(img, 8, 3, charset="symbols", edges=True).lines()
    counts = [line.count("|") for line in lines]
    assert counts == [1, 1, 1], f"Expected one '|' per row, got {lines}"


@pytest.mark.parametrize(("row_in_cell", "glyph"), [(8, "-"), (14, "_")])
def test_image_to_art_horizontal_step_draws_dash_or_underscore(
    make_canvas: Canvas, row_in_cell: int, glyph: str
) -> None:
    img = make_canvas(6, 3)
    img[CELL_HEIGHT + row_in_cell :] = 255
    middle = image_to_art(img, 6, 3, charset="symbols", edges=True).lines()[1]
    assert middle == glyph * 6, f"Expected {glyph * 6!r}, got {middle!r}"


@pytest.mark.parametrize(
    ("bright_side", "glyph", "other"),
    [("anti_diagonal", "/", "\\"), ("diagonal", "\\", "/")],
)
def test_image_to_art_diagonal_step_draws_matching_slash(
    make_canvas: Canvas, bright_side: str, glyph: str, other: str
) -> None:
    ys, xs = np.mgrid[0 : 10 * CELL_HEIGHT, 0 : 20 * CELL_WIDTH]
    img = make_canvas(20, 10)
    img[(xs + ys > 160) if bright_side == "anti_diagonal" else (ys > xs)] = 255
    text = "".join(image_to_art(img, 20, 10, edges=True).lines())
    hits, misses = text.count(glyph), text.count(other)
    assert hits >= 5, f"Expected at least 5 {glyph!r}, got {hits}"
    assert hits > 3 * misses, f"Too many {other!r}: {misses} vs {hits}"


def test_image_to_art_ink_style_keeps_hue(make_canvas: Canvas) -> None:
    img = make_canvas(2, 1)
    img[:, :] = (200, 30, 30)
    red, green, blue = (int(v) for v in image_to_art(img, 2, 1, style="ink").fg[0, 0])
    assert red > 200, f"Expected a strong red, got {red}"
    assert green < 60 and blue < 60, f"Expected weak green/blue, got {green}, {blue}"


def test_image_to_art_fill_style_paints_darker_background(make_canvas: Canvas) -> None:
    img = make_canvas(2, 1)
    img[:, :] = (200, 30, 30)
    art = image_to_art(img, 2, 1, style="fill")
    assert art.bg is not None, "Fill style must paint a background"
    bg, fg = int(art.bg[0, 0, 0]), int(art.fg[0, 0, 0])
    assert bg < fg, f"Expected background darker than symbol, got {bg} >= {fg}"


def test_to_text_rows_and_colors_match_art(make_canvas: Canvas) -> None:
    img = make_canvas(3, 2)
    img[:, :CELL_WIDTH] = (255, 0, 0)
    art = image_to_art(img, 3, 2)
    text = to_text(art)
    assert text.plain == "\n".join(art.lines()), f"Unexpected text {text.plain!r}"
    styles = [str(span.style) for span in text.spans]
    assert any("#ff" in style for style in styles), f"No red style in {styles}"


@pytest.mark.parametrize(("cols", "rows"), [(0, 1), (1, 0), (100, 1)])
def test_image_to_art_impossible_grid_raises_value_error(
    make_canvas: Canvas, cols: int, rows: int
) -> None:
    with pytest.raises(ValueError):
        image_to_art(make_canvas(2, 1), cols, rows)


def test_image_to_art_without_edges_uses_only_ramp_characters(
    make_canvas: Canvas,
) -> None:
    img = make_canvas(8, 3)
    img[:, 4 * CELL_WIDTH :] = 255
    text = "".join(image_to_art(img, 8, 3, charset="symbols").lines())
    assert set(text) <= set(RAMP_ORDER), f"Outline glyphs without edges: {text!r}"


def _art(chars: list[str], fg: list[list[tuple[int, int, int]]], bg=None) -> SymbolArt:
    """Hand-made art: one string per row, one color per cell."""
    grid = np.array([list(row) for row in chars])
    colors = np.array(fg, dtype=np.uint8)
    return SymbolArt(grid, colors, None if bg is None else np.array(bg, np.uint8))


ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def test_to_ansi_places_each_row_at_its_first_column(make_canvas: Canvas) -> None:
    art = image_to_art(make_canvas(6, 3), 6, 3)
    ansi = to_ansi(art)
    starts = [ansi.index(f"\x1b[{row};1H") for row in (1, 2, 3)]
    assert starts == sorted(starts), f"Rows must come in order, got {starts}"
    shown = ESCAPE.sub("", ansi)
    expected = to_text(art).plain.replace("\n", "")
    assert shown == expected, f"Expected the characters of to_text, got {shown!r}"


def test_to_ansi_writes_each_cells_color_once_per_run() -> None:
    red, blue = (255, 0, 0), (0, 0, 255)
    ansi = to_ansi(_art(["abc"], [[red, red, blue]]))
    assert ansi.count("\x1b[38;2;255;0;0m") == 1, f"Red repeated in {ansi!r}"
    assert "\x1b[38;2;255;0;0mab\x1b[38;2;0;0;255mc" in ansi, f"Got {ansi!r}"


def test_to_ansi_fill_style_paints_backgrounds() -> None:
    ansi = to_ansi(_art(["a"], [[(250, 250, 250)]], [[(10, 20, 30)]]))
    assert "\x1b[48;2;10;20;30m" in ansi, f"No background in {ansi!r}"


def test_to_ansi_starts_and_ends_with_a_reset() -> None:
    ansi = to_ansi(_art(["a"], [[(1, 2, 3)]]))
    assert ansi.startswith("\x1b[0m"), f"A stale color must not leak in: {ansi!r}"
    assert ansi.endswith("\x1b[0m"), f"The color must not leak out: {ansi!r}"
