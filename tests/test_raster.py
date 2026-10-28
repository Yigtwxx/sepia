import numpy as np
import pytest

from sepia.raster import RenderError, render_svg

RED, BLUE = (255, 0, 0), (0, 0, 255)


def test_render_svg_matching_canvas_returns_exact_rgb_pixels(wide_svg: str) -> None:
    pixels = render_svg(wide_svg, 40, 20)
    assert pixels.shape == (20, 40, 3), f"Expected (20, 40, 3), got {pixels.shape}"
    assert pixels.dtype == np.uint8, f"Expected uint8, got {pixels.dtype}"
    assert tuple(pixels[0, 0]) == RED, f"Expected red corner, got {pixels[0, 0]}"
    assert tuple(pixels[10, 20]) == BLUE, f"Expected blue center, got {pixels[10, 20]}"


def test_render_svg_taller_canvas_keeps_the_center(wide_svg: str) -> None:
    pixels = render_svg(wide_svg, 20, 20)
    assert pixels.shape == (20, 20, 3), f"Expected (20, 20, 3), got {pixels.shape}"
    assert tuple(pixels[10, 10]) == BLUE, f"Expected blue center, got {pixels[10, 10]}"


def test_render_svg_wider_canvas_has_no_empty_bars(wide_svg: str) -> None:
    pixels = render_svg(wide_svg, 80, 10)
    corners = {tuple(pixels[0, 0]), tuple(pixels[9, 79])}
    assert pixels.shape == (10, 80, 3), f"Expected (10, 80, 3), got {pixels.shape}"
    assert corners == {RED}, f"Expected red corners, got {corners}"


def test_render_svg_transparent_area_shows_background() -> None:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'
    pixels = render_svg(svg, 10, 10, background="#102030")
    expected = (0x10, 0x20, 0x30)
    assert tuple(pixels[5, 5]) == expected, f"Expected {expected}, got {pixels[5, 5]}"


def test_render_svg_invalid_markup_raises_render_error() -> None:
    with pytest.raises(RenderError):
        render_svg("<svg", 10, 10)


@pytest.mark.parametrize(("width", "height"), [(0, 10), (10, -1)])
def test_render_svg_empty_canvas_raises_value_error(
    wide_svg: str, width: int, height: int
) -> None:
    with pytest.raises(ValueError, match="canvas"):
        render_svg(wide_svg, width, height)
