import numpy as np
import pytest
from PIL import Image

from sepia.raster import fit_image, letterbox

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


def test_letterbox_keeps_the_whole_picture_on_black(wide_image: Image.Image) -> None:
    boxed = letterbox(wide_image, 200, 200)
    assert boxed.size == (200, 200), f"Got {boxed.size}"
    corners = (boxed.getpixel((0, 0)), boxed.getpixel((199, 199)))
    assert corners == ((0, 0, 0), (0, 0, 0)), f"Expected black bars, got {corners}"
    assert boxed.getpixel((100, 100)) == BLUE, "The picture's middle must stay"


def test_letterbox_transparent_parts_become_black() -> None:
    clear = Image.new("RGBA", (50, 50), (255, 255, 255, 0))
    boxed = letterbox(clear, 50, 50)
    assert boxed.getpixel((25, 25)) == (0, 0, 0), "Transparency must show black"


def test_letterbox_empty_canvas_raises() -> None:
    with pytest.raises(ValueError):
        letterbox(Image.new("RGB", (4, 4)), 0, 10)


def test_fit_image_uses_the_resampling_it_is_given(wide_image: Image.Image) -> None:
    sharp = fit_image(wide_image, 20, 10, resample=Image.Resampling.NEAREST)
    colors = {tuple(pixel) for pixel in sharp.reshape(-1, 3).tolist()}
    assert colors == {RED, BLUE}, (
        f"Nearest must blend nothing, got {len(colors)} colors"
    )
