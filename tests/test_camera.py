import importlib.util
import time
from collections.abc import Callable

import numpy as np
import pytest

from sepia import camera
from sepia.camera import Camera, CameraError, camera_installed, mirrored_rgb


class FakeCapture:
    """Stands in for `cv2.VideoCapture`, the camera itself being external: gives
    its frames in turn, then keeps giving the last one as a camera does, or fails
    with `then_fail`."""

    def __init__(
        self,
        frames: list[np.ndarray] | None = None,
        opened: bool = True,
        then_fail: bool = False,
    ) -> None:
        self.frames = list(frames or [_bgr((0, 0, 0))])
        self.last = self.frames[0]
        self.opened = opened
        self.then_fail = then_fail
        self.released = False

    def isOpened(self) -> bool:
        return self.opened

    def read(self) -> tuple[bool, np.ndarray | None]:
        time.sleep(0.002)  # a camera gives a frame now and then, not at once
        if self.frames:
            self.last = self.frames.pop(0)
        elif self.then_fail:
            return False, None
        return True, self.last

    def set(self, prop: int, value: float) -> bool:
        return True

    def release(self) -> None:
        self.released = True


def _eventually(condition: Callable[[], bool], seconds: float = 2.0) -> bool:
    """Whether `condition` turns true before `seconds` pass (the camera reads on a
    thread of its own)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def _bgr(*pixels: tuple[int, int, int]) -> np.ndarray:
    """One row of BGR pixels, as OpenCV gives them."""
    return np.array([pixels], dtype=np.uint8)


def test_mirrored_rgb_flips_left_to_right_and_swaps_blue_and_red() -> None:
    rgb = mirrored_rgb(_bgr((1, 2, 3), (4, 5, 6)))
    assert rgb.tolist() == [[[6, 5, 4], [3, 2, 1]]], f"Got {rgb.tolist()}"
    assert rgb.flags["C_CONTIGUOUS"], "Pillow and numpy want a plain array"


def test_camera_start_without_a_camera_raises_and_lets_go() -> None:
    capture = FakeCapture(opened=False)
    with pytest.raises(CameraError):
        Camera(lambda: capture).start()
    assert capture.released, "A capture that never opened must be released"


def test_camera_start_when_opening_fails_names_the_error() -> None:
    def refuse() -> FakeCapture:
        raise RuntimeError("device busy")

    with pytest.raises(CameraError, match="device busy"):
        Camera(refuse).start()


def test_camera_latest_is_the_newest_frame_mirrored_in_rgb() -> None:
    capture = FakeCapture([_bgr((0, 0, 0), (0, 0, 0)), _bgr((1, 2, 3), (4, 5, 6))])
    live = Camera(lambda: capture)
    assert live.latest() is None, "No frame before the camera starts"
    live.start()
    try:
        newest = [[[6, 5, 4], [3, 2, 1]]]
        seen = _eventually(
            lambda: (frame := live.latest()) is not None and frame.tolist() == newest
        )
        assert seen, f"Latest frame is {live.latest()}"
        assert not live.failed, "A camera still giving frames has not failed"
    finally:
        live.stop()


def test_camera_failed_read_marks_it_failed() -> None:
    live = Camera(lambda: FakeCapture(then_fail=True))
    live.start()
    try:
        assert _eventually(lambda: live.failed), "A read that fails must be noticed"
    finally:
        live.stop()


def test_camera_stop_releases_the_capture() -> None:
    capture = FakeCapture()
    live = Camera(lambda: capture)
    live.start()
    live.stop()
    assert capture.released, "The camera must be let go"
    live.stop()  # stopping twice is harmless


@pytest.mark.parametrize(("found", "expected"), [(object(), True), (None, False)])
def test_camera_installed_follows_whether_opencv_is_importable(
    monkeypatch: pytest.MonkeyPatch, found: object, expected: bool
) -> None:
    asked: list[str] = []

    def find_spec(name: str) -> object:
        asked.append(name)
        return found

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)
    assert camera_installed() is expected, f"find_spec gave {found}"
    assert asked == ["cv2"], f"Looked for {asked}"


def test_camera_module_imports_without_opencv() -> None:
    assert not hasattr(camera, "cv2"), "OpenCV must be imported inside functions only"
