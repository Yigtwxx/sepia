"""The picture window: full screen, nothing but the drawing."""

import contextlib
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast, get_args

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
from sepia.ripple import (
    DURATION,
    FRAME_SECONDS,
    MAX_RIPPLES,
    Mask,
    Ripple,
    ripple_ansi,
    spaced,
)
from sepia.scene import Canvas

POLL_SECONDS = 0.01
"""How long to wait for a message before checking the window size again."""
RESIZE_SETTLE_SECONDS = 0.15
"""A resize drag fires many sizes; redraw once the window has stopped changing."""
LIVE_FPS = 15
"""Camera frames drawn a second, at most."""
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
    cursor is, and a ripple or a resize leaves it mid-screen, where the frame would
    start off its first row and scroll the window; so it starts from home."""
    console.control(Control.home())
    screen.update(frame)


@lru_cache(maxsize=2)
def _picture(path: str) -> Image.Image:
    with Image.open(path) as image:
        return enhance(image)


class Hover:
    """Drops ripples along the mouse pointer's path over the picture."""

    def __init__(self, write: Callable[[str], object]) -> None:
        self._write = write
        self._parser = MouseParser()
        self._ripples: list[Ripple] = []
        self._dropped: tuple[int, int] | None = None
        self._drawn: Mask | None = None
        self._frame_at = 0.0

    def start(self) -> None:
        self._write(MOUSE_ON)

    def stop(self) -> None:
        self._write(MOUSE_OFF)

    def forget(self) -> None:
        """The screen was redrawn; no ripple shows any more."""
        self._ripples.clear()
        self._dropped, self._drawn = None, None

    def step(self, art: SymbolArt | None, typed: str) -> None:
        """Take new pointer reports and draw the next ripple frame if one is due."""
        point = self._parser.feed(typed) if typed else None
        now = time.monotonic()
        if art is None:
            return
        if point is not None and spaced(self._dropped, point):
            col, row = point
            if 0 <= col < art.cols and 0 <= row < art.rows:
                kept = self._ripples[-(MAX_RIPPLES - 1) :]
                self._ripples = [*kept, Ripple(col, row, now)]
                self._dropped = point
        self._ripples = [r for r in self._ripples if now - r.born < DURATION]
        if not self._ripples and self._drawn is None:
            return
        if now - self._frame_at >= FRAME_SECONDS:
            ansi, drawn = ripple_ansi(art, self._ripples, now, self._drawn)
            self._write(ansi)
            self._drawn = drawn if drawn.any() else None
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


class LiveView:
    """The camera shown live, each frame written straight as ANSI (rich takes
    about 120 ms a frame), until it is stopped or a frame is kept. `handle` and
    `step` return the replies the prompt waits for."""

    def __init__(
        self, write: Callable[[str], object], make_camera: Callable[[], Camera]
    ) -> None:
        self._write = write
        self._make_camera = make_camera
        self._camera: Camera | None = None
        self._announced = False
        self._drawn_at = float("-inf")

    @property
    def active(self) -> bool:
        return self._camera is not None

    def handle(self, message: Message, cols: int, rows: int) -> Message | None:
        """Act on a `camera` message: on, off, or keep the newest frame."""
        if "keep" in message:
            return self._keep(message["keep"], cols, rows)
        if message.get("on") is True and self._camera is None:
            camera = self._make_camera()
            try:
                camera.start()
            except CameraError as exc:
                return {"type": "camera", "error": str(exc)}
            self._camera, self._announced = camera, False
            self._drawn_at = float("-inf")
        elif message.get("on") is False:
            self.stop()
        return None

    def step(
        self, cols: int, rows: int, style: ArtStyle, charset: Charset
    ) -> Message | None:
        """Draw the newest frame when one is due. Says "on" with the first frame,
        and an error when the camera is lost."""
        camera = self._camera
        if camera is None:
            return None
        if camera.failed:
            self.stop()
            return {"type": "camera", "error": "the camera stopped giving pictures"}
        now = time.monotonic()
        frame = camera.latest()
        due = now - self._drawn_at >= 1 / LIVE_FPS
        if frame is None or not due or cols <= 0 or rows <= 0:
            return None
        self._write(live_frame(frame, cols, rows, style, charset))
        self._drawn_at = now
        if self._announced:
            return None
        self._announced = True
        return {"type": "camera", "state": "on"}

    def stop(self) -> None:
        """Let go of the camera, if it is on."""
        if self._camera is not None:
            self._camera.stop()
            self._camera = None

    def _keep(self, path: object, cols: int, rows: int) -> Message:
        """Save the newest frame at `path`, cut to the window's shape at the size
        a painting has, so /add can paint over it; then stop."""
        frame = None if self._camera is None else self._camera.latest()
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
    live = LiveView(console.file.write, Camera)
    with console.screen(hide_cursor=True) as screen:
        hover.start()
        try:
            size = console.size
            channel.send({"type": "size", "cols": size.width, "rows": size.height})
            # Stays dirty while the camera is live, so its end redraws the picture.
            dirty, changed_at = True, 0.0
            while True:
                try:
                    if channel.poll(POLL_SECONDS):
                        message = channel.receive()
                        if not state.apply(message):
                            return
                        if message.get("type") == "camera":
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
                    hover.forget()  # the full redraw wiped any ripple
                    dirty = False
                # No ripples over a live camera: the next frame would wipe them.
                hover.step(None if live.active else art, read_input())
                console.file.flush()
        finally:
            live.stop()
            hover.stop()


def _answer(channel: Channel, reply: Message | None, state: ViewerState) -> None:
    """Tell the prompt what the camera did; a kept frame becomes the picture."""
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
