import pytest

from sepia.scene import Canvas, Scene


@pytest.mark.parametrize(
    ("cols", "rows", "expected"),
    [(120, 40, (1200, 800)), (100, 50, (1200, 1200)), (200, 25, (1200, 300))],
)
def test_canvas_viewbox_matches_window_pixel_shape(
    cols: int, rows: int, expected: tuple[int, int]
) -> None:
    viewbox = Canvas(cols, rows).viewbox()
    assert viewbox == expected, f"Expected {expected}, got {viewbox}"


def test_scene_record_keeps_history_and_latest_svg() -> None:
    scene = Scene()
    scene.record("waterfall", "<svg>1</svg>")
    scene.record("mountains", "<svg>2</svg>")
    assert scene.requests == ["waterfall", "mountains"], f"Got {scene.requests}"
    assert scene.svg == "<svg>2</svg>", f"Got {scene.svg}"
    assert not scene.is_empty, "Scene with a drawing must not be empty"


def test_scene_reset_clears_everything() -> None:
    scene = Scene()
    scene.record("waterfall", "<svg/>")
    scene.reset()
    assert scene.is_empty, "Reset scene must be empty"
    assert scene.requests == [], f"Expected no requests, got {scene.requests}"
