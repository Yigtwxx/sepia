from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFont

from sepia import snapshot
from sepia.ascii_art import RAMPS, SymbolArt
from sepia.scene import Canvas

RGB = tuple[int, int, int]
NO_FONTS: tuple[str, ...] = ("no-such-font-sepia.ttf",)


@pytest.fixture
def font() -> snapshot.Font:
    """The fallback font: pixel tests must not depend on the machine's fonts."""
    return snapshot.load_font(names=NO_FONTS)


def _art(lines: list[str], fg: RGB, bg: RGB | None = None) -> SymbolArt:
    chars = np.array([list(line) for line in lines])
    shape = (*chars.shape, 3)
    fill = None if bg is None else np.full(shape, bg, np.uint8)
    return SymbolArt(chars, np.full(shape, fg, np.uint8), fill)


def _cell(picture: Image.Image, row: int, col: int) -> np.ndarray:
    w, h = snapshot.SNAPSHOT_CELL_WIDTH, snapshot.SNAPSHOT_CELL_HEIGHT
    return np.asarray(picture)[row * h : (row + 1) * h, col * w : (col + 1) * w]


def test_draw_size_is_one_snapshot_cell_per_character(font: snapshot.Font) -> None:
    picture = snapshot.draw(_art(["@@@", "@@@"], (255, 0, 0)), font)
    expected = (3 * snapshot.SNAPSHOT_CELL_WIDTH, 2 * snapshot.SNAPSHOT_CELL_HEIGHT)
    assert picture.size == expected, f"Expected {expected}, got {picture.size}"
    assert picture.mode == "RGB", f"Expected an RGB image, got {picture.mode}"


def test_draw_ink_space_stays_background_and_symbol_takes_fg(
    font: snapshot.Font,
) -> None:
    picture = snapshot.draw(_art(["@ "], (255, 0, 0)), font)
    space, symbol = _cell(picture, 0, 1), _cell(picture, 0, 0)
    assert (space == snapshot.BACKGROUND).all(), "A space must stay the background"
    assert symbol[..., 0].max() > 128, "The symbol must be drawn in its red fg"
    assert symbol[..., 1:].max() == 0, "Ink on black must add no other channel"


def test_draw_fill_space_is_its_cell_background(font: snapshot.Font) -> None:
    picture = snapshot.draw(_art([" "], (255, 255, 255), bg=(10, 20, 30)), font)
    assert (_cell(picture, 0, 0) == (10, 20, 30)).all(), "Fill must paint the bg"


def test_load_font_without_any_listed_font_uses_pillows_own() -> None:
    loaded = snapshot.load_font(names=NO_FONTS)
    default = ImageFont.load_default(snapshot.FONT_SIZE)
    assert isinstance(loaded, ImageFont.FreeTypeFont), f"Got {type(loaded)}"
    assert isinstance(default, ImageFont.FreeTypeFont), f"Got {type(default)}"
    assert loaded.getname() == default.getname(), f"Got {loaded.getname()}"


def test_load_font_fallback_widest_symbol_fits_a_cell() -> None:
    loaded = snapshot.load_font(names=NO_FONTS)
    symbols = {char for ramp in RAMPS.values() for char, _ in ramp}
    widest = max(loaded.getlength(char) for char in symbols)
    cell = snapshot.SNAPSHOT_CELL_WIDTH
    assert widest <= cell, f"Widest symbol is {widest} px, the cell {cell} px"


NOON = datetime(2026, 10, 29, 12, 0, 5)


def test_snapshot_size_follows_the_canvas(font: snapshot.Font) -> None:
    photo = Image.new("RGB", (64, 64), (120, 80, 40))
    picture = snapshot.snapshot(photo, Canvas(10, 4), "fill", "classic", font=font)
    expected = (10 * snapshot.SNAPSHOT_CELL_WIDTH, 4 * snapshot.SNAPSHOT_CELL_HEIGHT)
    assert picture.size == expected, f"Expected {expected}, got {picture.size}"


def test_save_snapshot_missing_folder_is_created_and_named_after_the_time(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Pictures" / "sepia"
    path = snapshot.save_snapshot(Image.new("RGB", (4, 4)), folder, NOON)
    assert path == folder / "2026-10-29_12-00-05.png", f"Got {path}"
    assert path.is_file(), "The PNG must be written"


def test_save_snapshot_same_second_keeps_the_earlier_file(tmp_path: Path) -> None:
    first = snapshot.save_snapshot(Image.new("RGB", (4, 4), "red"), tmp_path, NOON)
    second = snapshot.save_snapshot(Image.new("RGB", (4, 4), "blue"), tmp_path, NOON)
    assert second == tmp_path / "2026-10-29_12-00-05-2.png", f"Got {second}"
    with Image.open(first) as kept:
        assert kept.getpixel((0, 0)) == (255, 0, 0), "The first file was overwritten"


def test_pictures_dir_is_a_sepia_folder_in_pictures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshot, "user_pictures_path", lambda: tmp_path)
    folder = snapshot.pictures_dir()
    assert folder == tmp_path / "sepia", f"Got {folder}"
