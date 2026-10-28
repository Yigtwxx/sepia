import numpy as np
import pytest
from PIL import Image

from sepia.raster import fit_image

RED, BLUE = (255, 0, 0), (0, 0, 255)


@pytest.fixture
def wide_image() -> Image.Image:
    """A 2:1 red picture with a blue square in its middle."""
    image = Image.new("RGB", (200, 100), RED)
    image.paste(BLUE, (80, 30, 120, 70))
    return image


def test_fit_image_matching_canvas_keeps_whole_picture(wide_image: Image.Image) -> None:
    pixels = fit_image(wide_image, 40, 20)
    assert pixels.shape == (20, 40, 3), f"Expected (20, 40, 3), got {pixels.shape}"
    assert pixels.dtype == np.uint8, f"Expected uint8, got {pixels.dtype}"
    assert tuple(pixels[0, 0]) == RED, f"Expected red corner, got {pixels[0, 0]}"
    assert tuple(pixels[10, 20]) == BLUE, f"Expected blue center, got {pixels[10, 20]}"


def test_fit_image_square_canvas_keeps_the_center(wide_image: Image.Image) -> None:
    pixels = fit_image(wide_image, 20, 20)
    assert pixels.shape == (20, 20, 3), f"Expected (20, 20, 3), got {pixels.shape}"
    assert tuple(pixels[10, 10]) == BLUE, f"Expected blue center, got {pixels[10, 10]}"


def test_fit_image_wider_canvas_has_no_empty_bars(wide_image: Image.Image) -> None:
    pixels = fit_image(wide_image, 80, 10)
    corners = {tuple(pixels[0, 0]), tuple(pixels[9, 79])}
    assert corners == {RED}, f"Expected red corners, got {corners}"


def test_fit_image_converts_other_modes_to_rgb() -> None:
    pixels = fit_image(Image.new("RGBA", (10, 10), (1, 2, 3, 0)), 5, 5)
    assert pixels.shape == (5, 5, 3), f"Expected RGB output, got {pixels.shape}"


@pytest.mark.parametrize(("width", "height"), [(0, 10), (10, -1)])
def test_fit_image_empty_canvas_raises_value_error(
    wide_image: Image.Image, width: int, height: int
) -> None:
    with pytest.raises(ValueError, match="canvas"):
        fit_image(wide_image, width, height)
