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


def fit_image(image: Image.Image, width: int, height: int) -> RGBImage:
    """Scale `image` to cover exactly `width` x `height` pixels and center-crop it.

    A window whose shape differs from the picture loses a little of the picture's
    edges instead of showing empty bars or a stretched image.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"canvas must be positive, got {width}x{height}")
    fitted = ImageOps.fit(
        image.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS
    )
    return np.asarray(fitted, dtype=np.uint8)


def enhance(image: Image.Image) -> Image.Image:
    """Stretch contrast and boost color so a photo reads well as colored text."""
    stretched = ImageOps.autocontrast(image.convert("RGB"), cutoff=AUTOCONTRAST_CUTOFF)
    return ImageEnhance.Color(stretched).enhance(SATURATION)
