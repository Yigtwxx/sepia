import numpy as np
import pytest

from sepia.raster import RenderError, render_svg

WIDE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
    '<rect width="100" height="50" fill="#ff0000"/>'
    '<rect x="40" y="15" width="20" height="20" fill="#0000ff"/>'
    "</svg>"
)


def test_renders_exact_size_as_rgb() -> None:
    pixels = render_svg(WIDE, 40, 20)
    assert pixels.shape == (20, 40, 3)
    assert pixels.dtype == np.uint8
    assert tuple(pixels[0, 0]) == (255, 0, 0)
    assert tuple(pixels[10, 20]) == (0, 0, 255)


def test_taller_canvas_is_covered_and_center_cropped() -> None:
    pixels = render_svg(WIDE, 20, 20)
    assert pixels.shape == (20, 20, 3)
    # Covering a square with a 2:1 drawing keeps its middle, where the blue square is.
    assert tuple(pixels[10, 10]) == (0, 0, 255)
    assert tuple(pixels[0, 0]) == (255, 0, 0)


def test_wider_canvas_is_covered_without_bars() -> None:
    pixels = render_svg(WIDE, 80, 10)
    assert pixels.shape == (10, 80, 3)
    assert tuple(pixels[0, 0]) == (255, 0, 0)
    assert tuple(pixels[9, 79]) == (255, 0, 0)


def test_transparent_areas_show_background() -> None:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'
    pixels = render_svg(svg, 10, 10, background="#102030")
    assert tuple(pixels[5, 5]) == (0x10, 0x20, 0x30)


def test_invalid_svg_raises_render_error() -> None:
    with pytest.raises(RenderError):
        render_svg("<svg", 10, 10)


@pytest.mark.parametrize(("width", "height"), [(0, 10), (10, -1)])
def test_rejects_empty_canvas(width: int, height: int) -> None:
    with pytest.raises(ValueError, match="canvas"):
        render_svg(WIDE, width, height)
