import random
import re

import numpy as np
import pytest

from sepia.ascii_art import SymbolArt
from sepia.glitch import RADIUS_X, RADIUS_Y, area, glitch_ansi, restore_ansi
from sepia.mouse import MouseParser

POSITION = re.compile(r"\x1b\[(\d+);(\d+)H")
COLOR = re.compile(r"\x1b\[[0-9;]*m")


def _art(cols: int = 40, rows: int = 12) -> SymbolArt:
    chars = np.full((rows, cols), "a")
    fg = np.zeros((rows, cols, 3), dtype=np.uint8)
    fg[:, :, 0] = np.arange(cols, dtype=np.uint8)[None, :]
    return SymbolArt(chars, fg, None)


def _text(ansi: str) -> str:
    return COLOR.sub("", POSITION.sub("", ansi))


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        (["\x1b[<35;10;5M"], (9, 4)),
        (["\x1b[<35;1;1M\x1b[<35;20;8M"], (19, 7)),
        (["\x1b[<35;3", ";4M"], (2, 3)),
        (["hello"], None),
    ],
)
def test_mouse_parser_reports_the_latest_cell(chunks, expected) -> None:
    parser = MouseParser()
    results = [parser.feed(chunk) for chunk in chunks]
    assert results[-1] == expected, f"{chunks!r}: expected {expected}, got {results}"


def test_area_is_clipped_to_the_picture() -> None:
    top, bottom, left, right = area(_art(cols=40, rows=12), 0, 0)
    assert (top, left) == (0, 0), f"Area must not go negative: {top}, {left}"
    assert (bottom, right) == (RADIUS_Y + 1, RADIUS_X + 1), f"Got {bottom}, {right}"


def test_restore_ansi_redraws_the_original_cells() -> None:
    art = _art()
    top, bottom, left, right = area(art, 20, 6)
    text = _text(restore_ansi(art, 20, 6))
    expected = "a" * ((bottom - top) * (right - left))
    assert text == expected, f"Restore changed characters: {text!r}"


def test_glitch_ansi_at_zero_strength_changes_nothing() -> None:
    art = _art()
    calm = glitch_ansi(art, 20, 6, 0.0, random.Random(1))
    assert calm == restore_ansi(art, 20, 6), "A spent glitch must look untouched"


def test_glitch_ansi_at_full_strength_corrupts_and_stays_in_place() -> None:
    art = _art()
    noisy = glitch_ansi(art, 20, 6, 1.0, random.Random(7))
    top, bottom, left, _ = area(art, 20, 6)
    rows = [int(row) - 1 for row, _ in POSITION.findall(noisy)]
    cols = {int(col) - 1 for _, col in POSITION.findall(noisy)}
    assert rows == list(range(top, bottom)), f"Rows drawn: {rows}"
    assert cols == {left}, f"Every row starts at the area's left edge, got {cols}"
    assert set(_text(noisy)) != {"a"}, "Full strength must corrupt some glyphs"
