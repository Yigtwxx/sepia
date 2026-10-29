"""Fit pictures to the symbol grid."""

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageEnhance, ImageOps

RGBImage = npt.NDArray[np.uint8]
"""Pixels shaped (height, width, 3)."""

AUTOCONTRAST_CUTOFF = 1.0
"""Percent of the darkest and brightest pixels clipped when stretching contrast."""
SATURATION = 1.25
"""Color boost; symbols cover only part of a cell, so they need richer color."""


def fit_image(
    image: Image.Image,
    width: int,
    height: int,
    resample: Image.Resampling = Image.Resampling.LANCZOS,
) -> RGBImage:
    """Scale `image` to cover exactly `width` x `height` pixels and center-crop it.

    A window whose shape differs from the picture loses a little of the picture's
    edges instead of showing empty bars or a stretched image. A live camera frame
    takes a cheaper `resample` than a picture does.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"canvas must be positive, got {width}x{height}")
    fitted = ImageOps.fit(image.convert("RGB"), (width, height), method=resample)
    return np.asarray(fitted, dtype=np.uint8)


def letterbox(image: Image.Image, width: int, height: int) -> Image.Image:
    """`image` scaled to fit inside `width` x `height` and centered on black.

    A picture shown as it is keeps all of itself, where a painting fills the grid;
    transparent parts become black, the terminal's own background.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"canvas must be positive, got {width}x{height}")
    layer = ImageOps.contain(
        image.convert("RGBA"), (width, height), method=Image.Resampling.LANCZOS
    )
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    corner = ((width - layer.width) // 2, (height - layer.height) // 2)
    canvas.paste(layer, corner, layer)
    return canvas


def enhance(image: Image.Image) -> Image.Image:
    """Stretch contrast and boost color so a photo reads well as colored text."""
    stretched = ImageOps.autocontrast(image.convert("RGB"), cutoff=AUTOCONTRAST_CUTOFF)
    return ImageEnhance.Color(stretched).enhance(SATURATION)
