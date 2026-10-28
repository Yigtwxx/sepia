"""Rasterize SVG scenes into RGB pixel arrays."""

import io

import numpy as np
import numpy.typing as npt
import resvg_py
from PIL import Image

RGBImage = npt.NDArray[np.uint8]
"""Pixels shaped (height, width, 3)."""


class RenderError(ValueError):
    """The SVG could not be parsed or rendered."""


def render_svg(
    svg: str, width: int, height: int, background: str = "#000000"
) -> RGBImage:
    """Render `svg` to exactly `width` x `height` pixels.

    The drawing is scaled to cover the whole canvas and center-cropped, so a window
    whose aspect ratio differs from the SVG never shows empty bars.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"canvas must be positive, got {width}x{height}")
    image = _render(svg, width=width, background=background)
    if image.height < height:
        image = _render(svg, height=height, background=background)
    left = (image.width - width) // 2
    top = (image.height - height) // 2
    image = image.crop((left, top, left + width, top + height))
    if image.size != (width, height):
        image = image.resize((width, height))
    return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _render(
    svg: str, *, background: str, width: int | None = None, height: int | None = None
) -> Image.Image:
    try:
        png = resvg_py.svg_to_bytes(
            svg_string=svg,
            width=width,
            height=height,
            background=background,
            skip_system_fonts=True,
        )
    except ValueError as exc:
        raise RenderError(str(exc)) from exc
    return Image.open(io.BytesIO(png))
