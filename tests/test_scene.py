import pytest
from PIL import Image

from sepia.reference import Reference
from sepia.scene import Canvas, Scene


@pytest.mark.parametrize(
    ("cols", "rows", "expected"),
    [(120, 40, 1.5), (100, 50, 1.0), (200, 25, 4.0)],
)
def test_canvas_aspect_matches_window_pixel_shape(
    cols: int, rows: int, expected: float
) -> None:
    aspect = Canvas(cols, rows).aspect
    assert aspect == pytest.approx(expected), f"Expected {expected}, got {aspect}"


def test_scene_record_keeps_history_and_latest_image() -> None:
    first, second = Image.new("RGB", (2, 2)), Image.new("RGB", (3, 3))
    scene = Scene()
    scene.record("şelale", "A waterfall.", first)
    scene.record("dağlar", "A waterfall with mountains.", second)
    assert scene.requests == ["şelale", "dağlar"], f"Got {scene.requests}"
    assert scene.prompts[-1] == "A waterfall with mountains.", f"Got {scene.prompts}"
    assert scene.image is second, "Latest image must replace the previous one"
    assert not scene.is_empty, "Scene with a picture must not be empty"


def test_scene_reset_clears_everything_and_picks_new_seed() -> None:
    scene = Scene()
    scene.record("şelale", "A waterfall.", Image.new("RGB", (2, 2)))
    scene.reset()
    assert scene.is_empty, "Reset scene must be empty"
    assert scene.requests == [] and scene.prompts == [], "History must be cleared"
    assert 0 <= scene.seed < 2**31, f"Seed out of range: {scene.seed}"


def test_scene_record_keeps_the_reference_until_reset() -> None:
    likeness = Reference("https://img.example.org/a.png", Image.new("RGB", (2, 2)))
    scene = Scene()
    scene.record("yunara lol", "The character.", Image.new("RGB", (2, 2)), likeness)
    assert scene.likeness is likeness, "The reference must stay for /add"
    scene.reset()
    assert scene.likeness is None, "A fresh picture starts without a reference"
