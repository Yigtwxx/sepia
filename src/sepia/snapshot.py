"""/save: the picture in the window, drawn as its characters, kept as a PNG."""

from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from platformdirs import user_pictures_path

from sepia.ascii_art import (
    CELL_HEIGHT,
    CELL_WIDTH,
    RAMPS,
    ArtStyle,
    Charset,
    SymbolArt,
    image_to_art,
)
from sepia.raster import enhance, fit_image
from sepia.scene import Canvas

SNAPSHOT_CELL_WIDTH = 12
SNAPSHOT_CELL_HEIGHT = 24
"""Pixels per cell in the PNG: a terminal cell's 1:2 shape, large enough to read."""
FONT_SIZE = 20
"""Cascadia Mono advances exactly one 12 px cell at this size."""
BACKGROUND = (0, 0, 0)
"""The viewer profile's background (see launcher.py), under `ink` art."""
FONTS = ("CascadiaMono.ttf", "consola.ttf", "Menlo.ttc", "DejaVuSansMono.ttf")
"""Monospace fonts tried in turn: Windows Terminal's default and Consolas, then the
macOS and Linux ones. Pillow looks each name up in the system's font folders."""

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


def load_font(size: int = FONT_SIZE, names: tuple[str, ...] = FONTS) -> Font:
    """The first of `names` this machine has, else Pillow's own font. That one is
    proportional, so it is made small enough for its widest symbol to fit a cell."""
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    fallback = ImageFont.load_default(size)
    symbols = {char for ramp in RAMPS.values() for char, _ in ramp}
    widest = max(fallback.getlength(char) for char in symbols)
    if widest <= SNAPSHOT_CELL_WIDTH:
        return fallback
    return ImageFont.load_default(int(size * SNAPSHOT_CELL_WIDTH / widest))


def draw(art: SymbolArt, font: Font) -> Image.Image:
    """`art` as an RGB image: each cell its background, its symbol centered on it,
    so even a proportional fallback font keeps to the grid."""
    width, height = SNAPSHOT_CELL_WIDTH, SNAPSHOT_CELL_HEIGHT
    if art.bg is None:
        picture = Image.new("RGB", (art.cols * width, art.rows * height), BACKGROUND)
    else:
        cells = np.repeat(np.repeat(art.bg, height, axis=0), width, axis=1)
        picture = Image.fromarray(cells)
    pen = ImageDraw.Draw(picture)
    for row, col in zip(*np.nonzero(art.chars != " "), strict=True):
        center = ((col + 0.5) * width, (row + 0.5) * height)
        color = tuple(int(v) for v in art.fg[row, col])
        pen.text(center, str(art.chars[row, col]), fill=color, font=font, anchor="mm")
    return picture


def snapshot(
    image: Image.Image,
    canvas: Canvas,
    style: ArtStyle,
    charset: Charset,
    font: Font | None = None,
) -> Image.Image:
    """`image` drawn the way the viewer draws it in a `canvas`-sized window."""
    pixels = fit_image(
        enhance(image), canvas.cols * CELL_WIDTH, canvas.rows * CELL_HEIGHT
    )
    art = image_to_art(pixels, canvas.cols, canvas.rows, style=style, charset=charset)
    return draw(art, load_font() if font is None else font)


def save_snapshot(picture: Image.Image, folder: Path, now: datetime) -> Path:
    """Save `picture` in `folder`, named after `now`, never over an earlier one."""
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{now:%Y-%m-%d_%H-%M-%S}"
    path, count = folder / f"{stem}.png", 1
    while path.exists():
        count += 1
        path = folder / f"{stem}-{count}.png"
    picture.save(path)
    return path


def pictures_dir() -> Path:
    """Where /save keeps pictures: a sepia folder in the user's Pictures."""
    return user_pictures_path() / "sepia"
