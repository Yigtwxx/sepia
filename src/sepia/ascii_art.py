"""Turn RGB images into colored symbol art."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt
from rich.style import Style
from rich.text import Text

from sepia.raster import RGBImage

CELL_WIDTH = 8
CELL_HEIGHT = 16
"""Pixels rendered per terminal cell. Terminal cells are about twice as tall as wide."""

ArtStyle = Literal["ink", "fill"]
"""`ink` colors the symbols on the terminal's own background (made for dark themes).
`fill` also paints each cell's background, which shows the picture on any theme."""

FloatArray = npt.NDArray[np.float32]

# Symbols with the share of a cell their ink covers, measured in Cascadia Mono (the
# Windows Terminal default) and cross-checked against Consolas. Directional glyphs stay
# out of the ramp so that a texture never reads as an outline.
_RAMP: tuple[tuple[str, float], ...] = (
    (" ", 0.00),
    (".", 0.08),
    ("'", 0.15),
    (":", 0.16),
    (";", 0.24),
    ("^", 0.27),
    ("!", 0.29),
    ("~", 0.30),
    ("+", 0.39),
    ("*", 0.45),
    ("(", 0.55),
    ("%", 0.80),
    ("#", 0.81),
    ("&", 0.87),
    ("@", 1.00),
)
_RAMP_CHARS = np.array([char for char, _ in _RAMP])
_RAMP_DENSITY = np.array([density for _, density in _RAMP])

EDGE_STRENGTH = 0.35
"""Sobel magnitude (blurred luma) above which a pixel counts as part of an edge."""
EDGE_MIN_PIXELS = 5
"""Thinned edge pixels a cell needs before it is drawn as an outline."""
CONTRAST_STRETCH = 0.6
"""How far luminance is stretched toward the full ramp (0 keeps, 1 stretches fully)."""
SATURATION_BOOST = 1.2
"""Thin glyphs show less color than a filled cell, so ink colors are pushed a little."""
INK_FLOOR = 0.35
"""Lowest brightness of an ink color (its strongest channel, 0..1). Symbol density
already shows how bright a cell is, so the color only has to carry its hue; without a
floor, dark surfaces print as nearly invisible symbols."""
DENSITY_GAMMA = 0.75
"""Curve from luminance to symbol density. Below 1 it lifts dark surfaces off the
background so they read as texture instead of empty space."""
FILL_BACKGROUND = 0.55
"""Brightness of the painted background in `fill` style, relative to the cell color."""
FILL_HIGHLIGHT = 0.35
"""How far `fill` symbols are mixed toward white so they stand out on their own cell."""
DITHER = 0.05
"""Ordered-dither amplitude added to mid-tone luminance before a symbol is picked. It
turns smooth gradients into mixed symbols instead of one-symbol bands."""

# 4x4 Bayer matrix, centered on zero so dithering does not shift overall brightness.
_BAYER = (
    np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32)
    + 0.5
) / 16 - 0.5


@dataclass(frozen=True, eq=False)
class SymbolArt:
    """A grid of symbols with a foreground (and optional background) color per cell."""

    chars: npt.NDArray[np.str_]
    fg: RGBImage
    bg: RGBImage | None

    @property
    def rows(self) -> int:
        return int(self.chars.shape[0])

    @property
    def cols(self) -> int:
        return int(self.chars.shape[1])

    def lines(self) -> list[str]:
        return ["".join(row) for row in self.chars]


def image_to_art(
    pixels: RGBImage, cols: int, rows: int, style: ArtStyle = "ink"
) -> SymbolArt:
    """Convert `pixels` into `cols` x `rows` cells of colored symbols.

    Each cell averages the pixels under it, so `pixels` should be rendered larger than
    the grid (see `CELL_WIDTH` and `CELL_HEIGHT`). Leftover pixels at the right and
    bottom edges are dropped.
    """
    if cols <= 0 or rows <= 0:
        raise ValueError(f"grid must be positive, got {cols}x{rows}")
    height, width = pixels.shape[:2]
    cell_h, cell_w = height // rows, width // cols
    if cell_h == 0 or cell_w == 0:
        raise ValueError(
            f"image {width}x{height} is smaller than the {cols}x{rows} grid"
        )
    srgb = pixels[: rows * cell_h, : cols * cell_w].astype(np.float32) / 255.0

    linear = _srgb_to_linear(srgb)
    cell_color = _linear_to_srgb(_cell_mean(linear, rows, cell_h, cols, cell_w))
    glow = _linear_to_srgb(_bright_mean(linear, rows, cell_h, cols, cell_w))
    density = _stretch(_luma(cell_color)) ** DENSITY_GAMMA
    chars = _RAMP_CHARS[_ramp_index(_dither(density))]
    edge_chars = _edge_chars(_luma(srgb), rows, cell_h, cols, cell_w)
    chars = np.where(edge_chars != "", edge_chars, chars)

    if style == "fill":
        fg = glow + (1.0 - glow) * FILL_HIGHLIGHT
        return SymbolArt(chars, _to_bytes(fg), _to_bytes(cell_color * FILL_BACKGROUND))
    return SymbolArt(chars, _to_bytes(_ink(glow)), None)


def to_text(art: SymbolArt) -> Text:
    """Build a rich `Text` that prints the art, one terminal line per row."""
    text = Text(no_wrap=True, overflow="crop", end="")
    styles: dict[tuple[int, ...], Style] = {}
    for row in range(art.rows):
        for col in range(art.cols):
            fg = tuple(int(v) for v in art.fg[row, col])
            bg = () if art.bg is None else tuple(int(v) for v in art.bg[row, col])
            key = fg + bg
            style = styles.get(key)
            if style is None:
                style = Style(color=_hex(fg), bgcolor=_hex(bg) if bg else None)
                styles[key] = style
            text.append(str(art.chars[row, col]), style)
        if row < art.rows - 1:
            text.append("\n")
    return text


def _srgb_to_linear(c: FloatArray) -> FloatArray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c: FloatArray) -> FloatArray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def _luma(srgb: FloatArray) -> FloatArray:
    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    result: FloatArray = srgb @ weights
    return result


def _cell_mean(
    values: FloatArray, rows: int, cell_h: int, cols: int, cell_w: int
) -> FloatArray:
    shaped = values.reshape(rows, cell_h, cols, cell_w, *values.shape[2:])
    result: FloatArray = shaped.mean(axis=(1, 3))
    return result


def _bright_mean(
    linear: FloatArray, rows: int, cell_h: int, cols: int, cell_w: int
) -> FloatArray:
    """Cell color weighted toward its brightest pixels.

    A symbol's ink stands for the light in its cell, so a small lit window or star
    should give the symbol its color instead of being averaged into the dark around
    it. Weighting by squared luminance does that and leaves flat cells unchanged.
    """
    weight = (_luma(linear) ** 2 + 1e-6)[..., None]
    total = _cell_mean(linear * weight, rows, cell_h, cols, cell_w)
    result: FloatArray = total / _cell_mean(weight, rows, cell_h, cols, cell_w)
    return result


def _stretch(luma: FloatArray) -> FloatArray:
    low, high = (float(v) for v in np.percentile(luma, [2, 98]))
    if high - low < 1e-3:
        return luma
    stretched = np.clip((luma - low) / (high - low), 0.0, 1.0)
    result: FloatArray = luma + (stretched - luma) * CONTRAST_STRETCH
    return result


def _dither(luma: FloatArray) -> FloatArray:
    """Add the Bayer pattern, fading it out toward pure black and pure white."""
    rows, cols = luma.shape
    pattern = np.tile(_BAYER, (rows // 4 + 1, cols // 4 + 1))[:rows, :cols]
    midtone = 4.0 * luma * (1.0 - luma)
    result: FloatArray = (luma + pattern * 2.0 * DITHER * midtone).astype(np.float32)
    return result


def _ramp_index(target: FloatArray) -> npt.NDArray[np.intp]:
    """Index of the ramp symbol whose ink density is closest to each target value."""
    index: npt.NDArray[np.intp] = np.abs(target[..., None] - _RAMP_DENSITY).argmin(
        axis=-1
    )
    return index


def _edge_chars(
    luma: FloatArray, rows: int, cell_h: int, cols: int, cell_w: int
) -> npt.NDArray[np.str_]:
    """Outline glyph per cell (`| / - _ \\`), or "" for cells without a strong edge."""
    blurred = _blur(luma)
    gx, gy = _sobel(blurred)
    magnitude = np.hypot(gx, gy)
    # Gradient angle folded into [0, 180): 0 means brightness changes left to right, so
    # the edge itself runs vertically. Image rows grow downward.
    angle = np.degrees(np.arctan2(gy, gx)) % 180.0
    bins = ((angle + 22.5) // 45.0).astype(np.intp) % 4  # 0: |  1: /  2: -  3: \
    strong = (magnitude > EDGE_STRENGTH) & _ridge(magnitude, bins)

    def per_cell(mask: npt.NDArray[np.bool_]) -> FloatArray:
        return _cell_mean(mask.astype(np.float64), rows, cell_h, cols, cell_w)

    coverage = np.stack([per_cell(strong & (bins == b)) for b in range(4)], axis=-1)
    best = coverage.argmax(axis=-1)
    is_edge = coverage.sum(axis=-1) * cell_h * cell_w >= EDGE_MIN_PIXELS

    # A horizontal edge in the lower part of its cell reads better as "_" than "-".
    row_pos = np.broadcast_to(
        np.arange(luma.shape[0], dtype=np.float64)[:, None], luma.shape
    )
    row_in_cell = (row_pos % cell_h) / max(cell_h - 1, 1)
    horizontal = strong & (bins == 2)
    count = per_cell(horizontal)
    weighted = _cell_mean(row_in_cell * horizontal, rows, cell_h, cols, cell_w)
    mean_pos = np.divide(weighted, count, out=np.zeros_like(count), where=count > 0)
    glyphs = np.array(["|", "/", "-", "\\"])[best]
    glyphs = np.where((best == 2) & (mean_pos > 0.7), "_", glyphs)
    return np.where(is_edge, glyphs, "")


def _ridge(magnitude: FloatArray, bins: npt.NDArray[np.intp]) -> npt.NDArray[np.bool_]:
    """Keep only pixels that peak across their edge (non-maximum suppression).

    Blurring smears an edge over several pixels, which would mark the cells on both
    sides of it. Thinning to a one-pixel ridge puts each edge in exactly one cell; the
    `>=` / `>` pair breaks ties the same way every time.
    """
    height, width = magnitude.shape
    padded = np.pad(magnitude, 1)

    def neighbor(dy: int, dx: int) -> FloatArray:
        result: FloatArray = padded[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width]
        return result

    # Neighbors along the gradient, i.e. across the edge, for each direction bin.
    across = {
        0: ((0, -1), (0, 1)),
        1: ((-1, -1), (1, 1)),
        2: ((-1, 0), (1, 0)),
        3: ((-1, 1), (1, -1)),
    }
    keep = np.zeros(magnitude.shape, dtype=bool)
    for direction, (before, after) in across.items():
        peak = (magnitude >= neighbor(*before)) & (magnitude > neighbor(*after))
        keep |= (bins == direction) & peak
    return keep


def _blur(image: FloatArray, sigma: float = 1.5) -> FloatArray:
    radius = int(3 * sigma)
    offsets = np.arange(-radius, radius + 1)
    kernel = np.exp(-(offsets**2) / (2 * sigma**2)).astype(np.float32)
    kernel /= kernel.sum()
    for axis in (0, 1):
        pad = [(radius, radius) if a == axis else (0, 0) for a in (0, 1)]
        padded = np.pad(image, pad, "edge")
        length = image.shape[axis]
        blurred = np.zeros_like(image)
        for i, weight in enumerate(kernel):
            blurred += weight * np.take(padded, np.arange(i, i + length), axis=axis)
        image = blurred
    return image


def _sobel(image: FloatArray) -> tuple[FloatArray, FloatArray]:
    p = np.pad(image, 1, "edge")
    top_left, top, top_right = p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:]
    left, right = p[1:-1, :-2], p[1:-1, 2:]
    bottom_left, bottom, bottom_right = p[2:, :-2], p[2:, 1:-1], p[2:, 2:]
    gx = (top_right + 2 * right + bottom_right) - (top_left + 2 * left + bottom_left)
    gy = (bottom_left + 2 * bottom + bottom_right) - (top_left + 2 * top + top_right)
    return gx, gy


def _ink(color: FloatArray) -> FloatArray:
    gray = _luma(color)[..., None]
    saturated = np.clip(gray + (color - gray) * SATURATION_BOOST, 0.0, 1.0)
    value = saturated.max(axis=-1, keepdims=True)
    lifted = INK_FLOOR + (1.0 - INK_FLOOR) * value
    scale = np.divide(lifted, value, out=np.ones_like(value), where=value > 0.02)
    result: FloatArray = np.clip(saturated * scale, 0.0, 1.0).astype(np.float32)
    return result


def _to_bytes(color: FloatArray) -> RGBImage:
    return np.clip(np.rint(color * 255.0), 0, 255).astype(np.uint8)


def _hex(rgb: tuple[int, ...]) -> str:
    red, green, blue = rgb
    return f"#{red:02x}{green:02x}{blue:02x}"
