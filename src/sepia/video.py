"""Short videos for /play: checked and downloaded with yt-dlp into a folder of
their own in the temporary directory, played from the file by `VideoFile` in the
picture window, and deleted afterwards.

yt-dlp and OpenCV come with the optional `video` extra, so they are imported
inside functions.
"""

import contextlib
import importlib.util
import re
import shutil
import tempfile
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, Self

import numpy as np

from sepia.raster import RGBImage
from sepia.reference import UnusableLink, check_link

MAX_SECONDS = 60
"""The longest video /play downloads; a file from this computer has no limit."""
SLACK_SECONDS = 1.0
"""How far over a file measured after its download may run: frame counts are
estimates."""
MAX_BYTES = 100 * 1024 * 1024
"""The largest file yt-dlp downloads."""
MAX_HEIGHT = 480
"""Taller than any terminal shows in characters."""
FORMAT = (
    f"bv*[height<=?{MAX_HEIGHT}][vcodec^=avc1]/bv*[height<=?{MAX_HEIGHT}]"
    f"/b[height<=?{MAX_HEIGHT}]/wv*/w"
)
"""One file with the picture, never two to merge (that needs ffmpeg): H.264 first,
since every OpenCV build decodes it."""
FOLDER_PREFIX = "sepia-video-"
LEFTOVER_SECONDS = 3600.0
"""A folder this old was left by a sepia that did not close: a video playing now
is at most a minute old."""
SOCKET_SECONDS = 20.0
DEFAULT_FPS = 30.0
"""For a file that does not say its frame rate."""
MAX_FPS = 240.0
CAP_PROP_FPS, CAP_PROP_FRAME_COUNT = 5, 7
"""OpenCV's property ids, so that reading them needs no import of cv2."""
STOP_SECONDS = 2.0
"""How long stopping waits for a read in progress to end."""
ANSI = re.compile(r"\x1b\[[0-9;]*m")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
"""Characters a terminal acts on: a title from a web page must only be shown."""
MAX_HOPS = 3
"""Links that only point at another link, followed at most this many times."""

Reason = Literal["unusable", "too_long", "live", "not_a_video", "too_big", "failed"]


class VideoError(Exception):
    """A video /play cannot play; `reason` picks what the prompt says."""

    def __init__(
        self, reason: Reason, detail: str = "", seconds: float | None = None
    ) -> None:
        super().__init__(detail or reason)
        self.reason: Reason = reason
        self.detail = detail
        self.seconds = seconds
        """The video's length, for one that is too long."""


@dataclass(frozen=True)
class Video:
    path: Path
    title: str
    seconds: float | None
    """None when neither the site nor the file says."""
    host: str


class Downloader(Protocol):
    """The part of yt-dlp's `YoutubeDL` sepia uses."""

    def __enter__(self) -> Self: ...
    def __exit__(self, *exc: object) -> object: ...
    def extract_info(
        self,
        url: str,
        download: bool = ...,
        ie_key: str | None = ...,
        extra_info: dict[str, Any] | None = ...,
        process: bool = ...,
    ) -> dict[str, Any]: ...
    def process_ie_result(
        self, ie_result: dict[str, Any], download: bool = ...
    ) -> dict[str, Any]: ...


class Reader(Protocol):
    """The part of `cv2.VideoCapture` sepia uses on a file."""

    def isOpened(self) -> bool: ...
    def read(self) -> tuple[bool, Any]: ...
    def get(self, prop: int) -> float: ...
    def release(self) -> None: ...


class _Silent:
    """yt-dlp's logger: nothing it says may print over the prompt window. Its
    errors still raise."""

    def debug(self, message: str) -> None:
        pass

    def info(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass


def video_installed() -> bool:
    """Whether the optional `video` extra (yt-dlp and OpenCV) is installed."""
    return all(importlib.util.find_spec(name) is not None for name in ("yt_dlp", "cv2"))


def open_downloader(options: dict[str, Any]) -> Downloader:
    from yt_dlp import YoutubeDL

    downloader: Downloader = YoutubeDL(options)
    return downloader


def open_video(path: str) -> Reader:
    import cv2

    reader: Reader = cv2.VideoCapture(path)
    return reader


def video_seconds(
    path: Path, open_file: Callable[[str], Reader] = open_video
) -> float | None:
    """A file's length from its frame count and rate; None when it does not say."""
    try:
        reader = open_file(str(path))
    except Exception:  # OpenCV raises its own cv2.error
        return None
    try:
        if not reader.isOpened():
            return None
        fps, frames = reader.get(CAP_PROP_FPS), reader.get(CAP_PROP_FRAME_COUNT)
    finally:
        reader.release()
    if fps > 0 and frames > 0:
        return frames / fps
    return None


class _Stopped(Exception):
    """Raised from yt-dlp's progress hook to end a download early."""


def fetch(
    url: str,
    folder: Path,
    make: Callable[[dict[str, Any]], Downloader] = open_downloader,
    measure: Callable[[Path], float | None] = video_seconds,
    cancel: threading.Event | None = None,
) -> Video:
    """Download the video at `url` into `folder`, after making sure it is one
    video of at most a minute; VideoError says why not. Setting `cancel` ends a
    download in progress."""
    try:
        check_link(url)
    except UnusableLink as exc:
        raise VideoError("unusable") from exc
    over: list[bool] = []

    def guard(status: dict[str, Any]) -> None:
        """Stop when cancelled, or past the size limit: `max_filesize` only reads
        a size the server announces, which a stream in pieces never does."""
        if cancel is not None and cancel.is_set():
            raise _Stopped("cancelled")
        done = _number(status.get("downloaded_bytes"))
        if done is not None and done > MAX_BYTES:
            over.append(True)
            raise _Stopped("too big")

    options: dict[str, Any] = {
        "format": FORMAT,
        "outtmpl": {"default": str(folder / "video.%(ext)s")},
        "noplaylist": True,
        "max_filesize": MAX_BYTES,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _Silent(),
        "socket_timeout": SOCKET_SECONDS,
        "progress_hooks": [guard],
    }
    failure: VideoError | None = None
    try:
        with make(options) as downloader:
            info = _probe(downloader, url)
            downloader.process_ie_result(info, download=True)
    except VideoError:
        raise
    except Exception as exc:  # yt-dlp raises its own DownloadError, and others
        failure = VideoError("too_big") if over else VideoError("failed", _short(exc))
    if failure is not None:
        # Raised out here, with yt-dlp's frames gone: they hold the unfinished
        # file open, and Windows deletes no open file.
        raise failure
    path = _downloaded(folder)
    if path is None:
        raise VideoError("too_big")
    seconds = _number(info.get("duration"))
    if seconds is None:
        seconds = measure(path)
        if seconds is not None and seconds > MAX_SECONDS + SLACK_SECONDS:
            raise VideoError("too_long", seconds=seconds)
    title = _shown(str(info.get("title") or ""))
    return Video(path, title, seconds, urllib.parse.urlsplit(url).hostname or url)


def _probe(downloader: Downloader, url: str) -> dict[str, Any]:
    """What `url` is, without resolving every entry of a playlist or a channel
    (which takes minutes); VideoError for anything /play does not play."""
    info = downloader.extract_info(url, download=False, process=False)
    for _ in range(MAX_HOPS):
        if info.get("_type") not in ("url", "url_transparent"):
            break
        _refuse(info)
        info = downloader.extract_info(
            str(info.get("url")),
            download=False,
            ie_key=info.get("ie_key"),
            process=False,
        )
    if info.get("_type") in ("url", "url_transparent"):
        raise VideoError("not_a_video")
    _refuse(info)
    return info


def _refuse(info: dict[str, Any]) -> None:
    """Raise VideoError for what /play does not play: a playlist or channel, a
    live stream, a video over a minute."""
    if info.get("_type") in ("playlist", "multi_video"):
        raise VideoError("not_a_video")
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise VideoError("live")
    seconds = _number(info.get("duration"))
    if seconds is not None and seconds > MAX_SECONDS:
        raise VideoError("too_long", seconds=seconds)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _downloaded(folder: Path) -> Path | None:
    """The finished video in `folder`; parts of an unfinished one do not count."""
    for path in sorted(folder.glob("video.*")):
        if path.is_file() and path.suffix not in (".part", ".ytdl", ".temp"):
            return path
    return None


def _short(exc: Exception) -> str:
    """yt-dlp's message without its colors, its "ERROR:" and its advice lines."""
    lines = ANSI.sub("", str(exc)).strip().splitlines()
    first = lines[0] if lines else type(exc).__name__
    return _shown(first.removeprefix("ERROR:").strip())


def _shown(text: str) -> str:
    """`text` without the characters a terminal would act on."""
    return CONTROL.sub("", text)


def new_folder(root: Path | None = None) -> Path:
    """A fresh folder for one video, in the temporary directory."""
    return Path(tempfile.mkdtemp(prefix=FOLDER_PREFIX, dir=root))


def discard(folder: Path) -> None:
    """Delete a video's folder; one still open elsewhere stays for `sweep`."""
    shutil.rmtree(folder, ignore_errors=True)


def sweep(
    root: Path | None = None,
    older_than: float = LEFTOVER_SECONDS,
    now: float | None = None,
) -> None:
    """Delete video folders left by a sepia that did not close properly."""
    base = Path(tempfile.gettempdir()) if root is None else root
    moment = time.time() if now is None else now
    with contextlib.suppress(OSError):
        for folder in base.glob(f"{FOLDER_PREFIX}*"):
            with contextlib.suppress(OSError):
                if folder.is_dir() and moment - folder.stat().st_mtime > older_than:
                    discard(folder)


class VideoFile:
    """Plays a video file once at its own speed, on a thread, keeping the frame
    due now. The same shape as `Camera`, so the live view shows either. It stops
    after `limit` seconds (a download whose length was not known), or plays to
    the end when `limit` is None (a file from this computer)."""

    def __init__(
        self,
        path: str,
        open_file: Callable[[str], Reader] = open_video,
        clock: Callable[[], float] = time.monotonic,
        *,
        limit: float | None = MAX_SECONDS,
    ) -> None:
        self.path = path
        self._open = open_file
        self._clock = clock
        self._limit = limit
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._latest: RGBImage | None = None
        self.failed = False
        """The file gave no frame at all."""
        self.ended = False
        """The last frame, or the limit, has been played."""

    def start(self) -> None:
        """Open the file and start playing; VideoError when it does not open."""
        try:
            reader = self._open(self.path)
        except Exception as exc:  # OpenCV raises its own cv2.error
            raise VideoError("failed", str(exc)) from exc
        if not reader.isOpened():
            reader.release()
            raise VideoError("failed", "the video file did not open")
        self._latest = None
        self.failed = self.ended = False
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._play, args=(reader,), name="sepia-video", daemon=True
        )
        self._thread.start()

    def latest(self) -> RGBImage | None:
        """The frame due now, or None before the first one."""
        with self._lock:
            return self._latest

    def stop(self) -> None:
        """Stop playing; the playing thread lets go of the file as it ends, since
        OpenCV is not safe to release during a read."""
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=STOP_SECONDS)
            self._thread = None

    def _play(self, reader: Reader) -> None:
        try:
            self._frames(reader)
        except Exception:  # OpenCV raises its own cv2.error
            self.failed = True
        finally:
            reader.release()

    def _frames(self, reader: Reader) -> None:
        fps = reader.get(CAP_PROP_FPS)
        if not 0 < fps <= MAX_FPS:
            fps = DEFAULT_FPS
        begun = self._clock()
        index = 0
        while not self._stopping.is_set():
            ok, frame = reader.read()
            if self._stopping.is_set():
                return
            if not ok or frame is None:
                # The last frame stays on screen for its own time first.
                if index == 0:
                    self.failed = True
                elif not self._wait_until(begun + index / fps):
                    self.ended = True
                return
            due = index / fps
            if self._limit is not None and due >= self._limit:
                self.ended = True
                return
            index += 1
            if begun + due - self._clock() < -1 / fps:
                continue  # its time has passed: decoding fell behind
            if self._wait_until(begun + due):
                return
            rgb = np.ascontiguousarray(frame[:, :, ::-1])
            with self._lock:
                self._latest = rgb

    def _wait_until(self, moment: float) -> bool:
        """Wait for `moment` on the clock; True when stopped meanwhile."""
        wait = moment - self._clock()
        return wait > 0 and self._stopping.wait(wait)
