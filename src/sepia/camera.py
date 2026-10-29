"""The webcam, for /cam: frames read on a thread of their own, the newest kept.

OpenCV comes with the optional `cam` extra, so it is imported inside functions.
"""

import sys
import threading
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from sepia.raster import RGBImage

FRAME_WIDTH, FRAME_HEIGHT = 1280, 720
"""What the camera is asked for; it gives the nearest size it has."""
STOP_SECONDS = 2.0
"""How long stopping waits for a read in progress to end."""


class CameraError(Exception):
    """The camera could not be opened."""


class Capture(Protocol):
    """The part of `cv2.VideoCapture` sepia uses."""

    def isOpened(self) -> bool: ...
    def read(self) -> tuple[bool, Any]: ...
    def set(self, prop: int, value: float) -> bool: ...
    def release(self) -> None: ...


def camera_installed() -> bool:
    """Whether the optional `cam` extra (OpenCV) is installed."""
    import importlib.util

    return importlib.util.find_spec("cv2") is not None


def open_capture() -> Capture:
    """The first camera, through the platform's own camera API: DirectShow opens
    much faster than Media Foundation on Windows."""
    import cv2

    backends = {"win32": cv2.CAP_DSHOW, "darwin": cv2.CAP_AVFOUNDATION}
    capture: Capture = cv2.VideoCapture(0, backends.get(sys.platform, cv2.CAP_ANY))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    return capture


def mirrored_rgb(frame: npt.NDArray[np.uint8]) -> RGBImage:
    """A BGR camera frame as RGB, flipped left to right like a mirror."""
    return np.ascontiguousarray(frame[:, ::-1, ::-1])


class Camera:
    """Reads the camera on a thread and keeps the newest frame, mirrored."""

    def __init__(self, open_camera: Callable[[], Capture] = open_capture) -> None:
        self._open = open_camera
        self._capture: Capture | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._latest: RGBImage | None = None
        self.failed = False
        """A read failed: the camera was unplugged, or another app took it."""

    def start(self) -> None:
        """Open the camera and start reading it; CameraError when it does not."""
        try:
            capture = self._open()
        except Exception as exc:  # OpenCV raises its own cv2.error
            raise CameraError(str(exc)) from exc
        if not capture.isOpened():
            capture.release()
            raise CameraError("no camera answered")
        self._capture, self._latest, self.failed = capture, None, False
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._read, args=(capture,), name="sepia-camera", daemon=True
        )
        self._thread.start()

    def latest(self) -> RGBImage | None:
        """The newest frame, or None before the first one."""
        with self._lock:
            return self._latest

    def stop(self) -> None:
        """Stop reading and let go of the camera. OpenCV is not safe to release
        during a read, so the reading thread ends first; a read takes one frame."""
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=STOP_SECONDS)
            self._thread = None
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _read(self, capture: Capture) -> None:
        while not self._stopping.is_set():
            ok, frame = capture.read()
            if self._stopping.is_set():
                return
            if not ok or frame is None:
                self.failed = True
                return
            rgb = mirrored_rgb(frame)
            with self._lock:
                self._latest = rgb
