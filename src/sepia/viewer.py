"""The picture window: full screen, nothing but the drawing."""

import contextlib
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol, cast, get_args

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from rich.console import Console, ScreenContext
from rich.control import Control
from rich.text import Text

from sepia.ascii_art import (
    CELL_HEIGHT,
    CELL_WIDTH,
    ArtStyle,
    Charset,
    SymbolArt,
    image_to_art,
    to_ansi,
    to_text,
)
from sepia.camera import Camera, CameraError
from sepia.config import DEFAULT_CHARSET, DEFAULT_STYLE
from sepia.ipc import Channel, Message, Session, connect
from sepia.mouse import MOUSE_OFF, MOUSE_ON, MouseParser, read_input
from sepia.painter import image_size
from sepia.raster import RGBImage, enhance, fit_image
from sepia.scene import Canvas
from sepia.trail import (
    FADE,
    FRAME_SECONDS,
    MAX_DABS,
    Dab,
    Levels,
    dabs_between,
    trail_ansi,
)
from sepia.video import MAX_SECONDS, VideoError, VideoFile

POLL_SECONDS = 0.01
"""How long to wait for a message before checking the window size again."""
RESIZE_SETTLE_SECONDS = 0.15
"""A resize drag fires many sizes; redraw once the window has stopped changing."""
LIVE_FPS = 15
"""Camera or video frames drawn a second, at most."""
LIVE_CELL_WIDTH, LIVE_CELL_HEIGHT = 4, 8
"""Pixels a cell averages in the live view: a quarter of a picture's, so a frame
draws in about 35 ms."""


@dataclass
class ViewerState:
    path: str | None = None
    style: ArtStyle = DEFAULT_STYLE
    charset: Charset = DEFAULT_CHARSET

    def apply(self, message: Message) -> bool:
        """Update from one message; False means the prompt asked the viewer to quit."""
        kind = message.get("type")
        if kind == "bye":
            return False
        if kind == "image" and isinstance(message.get("path"), str):
            self.path = message["path"]
        if kind == "clear":
            self.path = None
        if kind in ("image", "style"):
            style, charset = message.get("style"), message.get("charset")
            if style in get_args(ArtStyle):
                self.style = cast(ArtStyle, style)
            if charset in get_args(Charset):
                self.charset = cast(Charset, charset)
        return True


def render_frame(state: ViewerState, cols: int, rows: int) -> Text:
    """The picture sized to the window, or a blank screen before the first one."""
    art = render_art(state, cols, rows)
    return Text("") if art is None else _art_text(art)


def render_art(state: ViewerState, cols: int, rows: int) -> SymbolArt | None:
    """The symbol art for the window, or None before the first picture."""
    if state.path is None or cols <= 0 or rows <= 0:
        return None
    return _art(state.path, state.style, state.charset, cols, rows)


@lru_cache(maxsize=4)
def _art(
    path: str, style: ArtStyle, charset: Charset, cols: int, rows: int
) -> SymbolArt:
    pixels = fit_image(_picture(path), cols * CELL_WIDTH, rows * CELL_HEIGHT)
    return image_to_art(pixels, cols, rows, style=style, charset=charset)


@lru_cache(maxsize=4)
def _art_text(art: SymbolArt) -> Text:
    return to_text(art)


def draw_frame(console: Console, screen: ScreenContext, frame: Text) -> None:
    """Draw `frame` over the whole window. rich prints a screen from wherever the
    cursor is, and a trail or a resize leaves it mid-screen, where the frame would
    start off its first row and scroll the window; so it starts from home."""
    console.control(Control.home())
    screen.update(frame)


@lru_cache(maxsize=2)
def _picture(path: str) -> Image.Image:
    with Image.open(path) as image:
        return enhance(image)


class Hover:
    """Leaves a sepia trail along the mouse pointer's path over the picture."""

    def __init__(self, write: Callable[[str], object]) -> None:
        self._write = write
        self._parser = MouseParser()
        self._dabs: list[Dab] = []
        self._last: tuple[int, int] | None = None
        self._shown: Levels | None = None
        self._frame_at = 0.0

    def start(self) -> None:
        self._write(MOUSE_ON)

    def stop(self) -> None:
        self._write(MOUSE_OFF)

    def forget(self) -> None:
        """The screen was redrawn; no trail shows any more."""
        self._dabs.clear()
        self._last, self._shown = None, None

    def step(self, art: SymbolArt | None, typed: str) -> None:
        """Take new pointer reports and draw the next trail frame if one is due."""
        points = self._parser.feed(typed) if typed else []
        now = time.monotonic()
        if art is None:
            return
        for point in points:
            if 0 <= point[0] < art.cols and 0 <= point[1] < art.rows:
                laid = dabs_between(self._last, point, now)
                if laid:
                    self._dabs.extend(laid)
                    self._last = point
        self._dabs = [d for d in self._dabs[-MAX_DABS:] if now - d.born < FADE]
        if not self._dabs and self._shown is None:
            return
        if now - self._frame_at >= FRAME_SECONDS:
            ansi, shown = trail_ansi(art, self._dabs, now, self._shown)
            if ansi:
                self._write(ansi)
            self._shown = shown if shown.any() else None
            self._frame_at = now


def live_frame(
    pixels: RGBImage, cols: int, rows: int, style: ArtStyle, charset: Charset
) -> str:
    """One camera frame drawn over the whole window, as ANSI."""
    small = fit_image(
        Image.fromarray(pixels),
        cols * LIVE_CELL_WIDTH,
        rows * LIVE_CELL_HEIGHT,
        resample=Image.Resampling.BILINEAR,
    )
    enhanced = np.asarray(enhance(Image.fromarray(small)), dtype=np.uint8)
    return to_ansi(image_to_art(enhanced, cols, rows, style=style, charset=charset))


class FrameSource(Protocol):
    """The camera or a video file: frames read on a thread of their own."""

    @property
    def failed(self) -> bool: ...
    @property
    def ended(self) -> bool: ...
    def start(self) -> None: ...
    def latest(self) -> RGBImage | None: ...
    def stop(self) -> None: ...


class MakeVideo(Protocol):
    """Opens a video file to play, for at most `limit` seconds (None: whole)."""

    def __call__(self, path: str, *, limit: float | None) -> FrameSource: ...


Live = Literal["camera", "video"]
LOST: dict[Live, str] = {
    "camera": "the camera stopped giving pictures",
    "video": "the video file could not be read",
}


class LiveView:
    """The camera, or a video from /play, shown live: each frame written straight
    as ANSI (rich takes about 120 ms a frame), until it is stopped, a camera frame
    is kept or the video ends. `handle` and `step` return the replies the prompt
    waits for; a video's replies name its file, which the prompt then deletes."""

    def __init__(
        self,
        write: Callable[[str], object],
        make_camera: Callable[[], FrameSource],
        make_video: MakeVideo = VideoFile,
    ) -> None:
        self._write = write
        self._make_camera = make_camera
        self._make_video = make_video
        self._source: FrameSource | None = None
        self._kind: Live = "camera"
        self._path = ""
        """The video's file."""
        self._announced = False
        self._drawn_at = float("-inf")

    @property
    def active(self) -> bool:
        return self._source is not None

    def handle(self, message: Message, cols: int, rows: int) -> Message | None:
        """Act on a `camera` message (on, off, or keep the newest frame) or a
        `video` one (play a file, or off)."""
        if message.get("type") == "video":
            return self._video(message)
        if "keep" in message:
            return self._keep(message["keep"], cols, rows)
        if message.get("on") is True and not self._showing("camera"):
            return self._start("camera", "", self._make_camera)
        if message.get("on") is False and self._showing("camera"):
            self.stop()
        return None

    def step(
        self, cols: int, rows: int, style: ArtStyle, charset: Charset
    ) -> Message | None:
        """Draw the newest frame when one is due. Says "on" with the first frame,
        "ended" after a video's last, and an error when the source is lost."""
        source = self._source
        if source is None:
            return None
        if source.failed:
            return self._reply(error=LOST[self._kind])
        frame = source.latest()
        if source.ended and (self._announced or frame is None):
            return self._reply(state="ended")
        now = time.monotonic()
        due = now - self._drawn_at >= 1 / LIVE_FPS
        if frame is None or not due or cols <= 0 or rows <= 0:
            return None
        self._write(live_frame(frame, cols, rows, style, charset))
        self._drawn_at = now
        if self._announced:
            return None
        self._announced = True
        return self._said(state="on")

    def stop(self) -> None:
        """Let go of the camera or the video file, if one is live."""
        if self._source is not None:
            self._source.stop()
            self._source = None

    def _showing(self, kind: Live) -> bool:
        return self._source is not None and self._kind == kind

    def _start(
        self, kind: Live, path: str, make: Callable[[], FrameSource]
    ) -> Message | None:
        """Show a new source in place of any live one; an error when it does not
        start."""
        self.stop()
        self._kind, self._path = kind, path
        source = make()
        try:
            source.start()
        except (CameraError, VideoError) as exc:
            return self._said(error=str(exc))
        self._source, self._announced = source, False
        self._drawn_at = float("-inf")
        return None

    def _video(self, message: Message) -> Message | None:
        """Play the file a `video` message names, or stop the video playing. A
        download plays at most its first minute; a `whole` one, a file from this
        computer, plays to its end."""
        if message.get("on") is False:
            return self._reply(state="off") if self._showing("video") else None
        path = message.get("path")
        if not isinstance(path, str):
            return None
        limit = None if message.get("whole") is True else MAX_SECONDS
        return self._start("video", path, lambda: self._make_video(path, limit=limit))

    def _reply(self, **fields: object) -> Message:
        """Stop the live source and say so."""
        self.stop()
        return self._said(**fields)

    def _said(self, **fields: object) -> Message:
        """A reply about the live source; a video's names its file."""
        reply: Message = {"type": self._kind, **fields}
        if self._kind == "video":
            reply["path"] = self._path
        return reply

    def _keep(self, path: object, cols: int, rows: int) -> Message:
        """Save the newest frame at `path`, cut to the window's shape at the size
        a painting has, so /add can paint over it; then stop."""
        if self._showing("video"):
            return {"type": "camera", "error": "a video is playing, not the camera"}
        frame = None if self._source is None else self._source.latest()
        self.stop()
        if frame is None or not isinstance(path, str) or cols <= 0 or rows <= 0:
            return {"type": "camera", "error": "there was no frame to keep"}
        size = image_size(Canvas(cols, rows).aspect)
        kept = ImageOps.fit(
            Image.fromarray(frame), size, method=Image.Resampling.LANCZOS
        )
        try:
            kept.save(path)
        except (OSError, ValueError) as exc:
            return {"type": "camera", "error": str(exc)}
        return {"type": "camera", "state": "kept", "path": path}


def run_viewer(session_file: Path) -> int:
    channel = connect(Session.load(session_file))
    console = Console(highlight=False)
    console.set_window_title("sepia")
    try:
        with _no_echo():
            _loop(channel, console)
    except KeyboardInterrupt:
        pass
    finally:
        channel.close()
    return 0


def _loop(channel: Channel, console: Console) -> None:
    state = ViewerState()
    frame = Text("")
    art: SymbolArt | None = None
    hover = Hover(console.file.write)
    live = LiveView(console.file.write, Camera, VideoFile)
    with console.screen(hide_cursor=True) as screen:
        hover.start()
        try:
            size = console.size
            channel.send({"type": "size", "cols": size.width, "rows": size.height})
            # Dirty while a camera or video is live, so its end redraws the picture.
            dirty, changed_at = True, 0.0
            while True:
                try:
                    if channel.poll(POLL_SECONDS):
                        message = channel.receive()
                        if not state.apply(message):
                            return
                        if message.get("type") in ("camera", "video"):
                            reply = live.handle(message, size.width, size.height)
                            _answer(channel, reply, state)
                        dirty = True
                except (EOFError, OSError, ValueError):
                    return  # the prompt is gone
                current = console.size
                if current != size:
                    size, changed_at, dirty = current, time.monotonic(), True
                    with contextlib.suppress(OSError, EOFError):
                        channel.send(
                            {"type": "size", "cols": size.width, "rows": size.height}
                        )
                if live.active:
                    reply = live.step(
                        size.width, size.height, state.style, state.charset
                    )
                    _answer(channel, reply, state)
                settled = time.monotonic() - changed_at >= RESIZE_SETTLE_SECONDS
                if dirty and settled and not live.active:
                    with contextlib.suppress(
                        OSError, UnidentifiedImageError, ValueError
                    ):
                        art = render_art(state, size.width, size.height)
                        frame = Text("") if art is None else _art_text(art)
                    draw_frame(console, screen, frame)
                    hover.forget()  # the full redraw wiped the trail
                    dirty = False
                # No trail over a live view: the next frame would wipe it.
                hover.step(None if live.active else art, read_input())
                console.file.flush()
        finally:
            live.stop()
            hover.stop()


def _answer(channel: Channel, reply: Message | None, state: ViewerState) -> None:
    """Tell the prompt what the camera or video did; a kept frame becomes the
    picture."""
    if reply is None:
        return
    if reply.get("state") == "kept":
        state.path = reply["path"]
    with contextlib.suppress(OSError, EOFError):
        channel.send(reply)


@contextlib.contextmanager
def _no_echo() -> Iterator[None]:
    """Stop keys typed into the window from printing over the picture."""
    if not sys.stdin.isatty():
        yield
        return
    with _quiet_console():
        yield


if sys.platform == "win32":

    @contextlib.contextmanager
    def _quiet_console() -> Iterator[None]:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            yield
            return
        echo_line_quick_edit = 0x0004 | 0x0002 | 0x0040
        vt_input_extended = 0x0200 | 0x0080  # ENABLE_VIRTUAL_TERMINAL_INPUT, flags
        quiet = (mode.value & ~echo_line_quick_edit) | vt_input_extended
        kernel32.SetConsoleMode(handle, quiet)
        try:
            yield
        finally:
            kernel32.FlushConsoleInputBuffer(handle)
            kernel32.SetConsoleMode(handle, mode.value)

else:

    @contextlib.contextmanager
    def _quiet_console() -> Iterator[None]:
        import termios

        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        quiet = termios.tcgetattr(fd)
        quiet[3] &= ~(termios.ECHO | termios.ICANON)
        termios.tcsetattr(fd, termios.TCSADRAIN, quiet)
        try:
            yield
        finally:
            termios.tcflush(fd, termios.TCIFLUSH)
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
