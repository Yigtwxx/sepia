from pathlib import Path

import pytest
from PIL import Image

from sepia.reference import Reference
from sepia.scene import Canvas, History, Scene, new_seed


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


def test_scene_record_keeps_where_the_picture_is_and_what_it_was_painted_over(
    tmp_path: Path,
) -> None:
    base, image = Image.new("RGB", (2, 2)), Image.new("RGB", (2, 2))
    scene = Scene()
    scene.record(
        "swans", "A lake with swans.", image, path=tmp_path / "02.png", base=base
    )
    assert scene.path == tmp_path / "02.png", f"Got {scene.path}"
    assert scene.base is base, "/again must know what the picture was painted over"


def test_scene_copy_changes_without_touching_the_original() -> None:
    likeness = Reference("https://img.example.org/a.png", Image.new("RGB", (2, 2)))
    first = Image.new("RGB", (2, 2))
    scene = Scene()
    scene.record("şelale", "A waterfall.", first, likeness)
    copy = scene.copy()
    copy.record("dağlar", "A waterfall with mountains.", Image.new("RGB", (3, 3)))
    assert scene.requests == ["şelale"], f"The original changed: {scene.requests}"
    assert scene.image is first, "The original keeps its picture"
    assert copy.requests == ["şelale", "dağlar"], f"Got {copy.requests}"
    assert copy.seed == scene.seed, "A copy keeps the composition"


def test_new_seed_is_in_the_models_range() -> None:
    seeds = {new_seed() for _ in range(20)}
    assert all(0 <= seed < 2**31 for seed in seeds), f"Out of range: {seeds}"
    assert len(seeds) > 1, "Seeds must differ"


def test_history_pop_returns_the_newest_scene_first() -> None:
    history = History()
    older, newer = Scene(), Scene()
    history.push(older)
    history.push(newer)
    popped = (history.pop(), history.pop())
    assert popped == (newer, older), f"Got {popped}"


def test_history_pop_with_nothing_left_is_none() -> None:
    assert History().pop() is None, "An empty history has nothing to give back"


def test_history_beyond_its_limit_drops_the_oldest() -> None:
    history = History(limit=2)
    scenes = [Scene() for _ in range(3)]
    for scene in scenes:
        history.push(scene)
    assert len(history) == 2, f"Kept {len(history)}"
    kept = [history.pop(), history.pop()]
    assert kept == [scenes[2], scenes[1]], "The oldest must go first"
