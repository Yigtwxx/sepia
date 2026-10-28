"""The picture window: full screen, nothing but the drawing."""

import contextlib
import random
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast, get_args

from PIL import Image, UnidentifiedImageError
from rich.console import Console
from rich.text import Text

from sepia.ascii_art import (
    CELL_HEIGHT,
    CELL_WIDTH,
    ArtStyle,
    Charset,
    SymbolArt,
    image_to_art,
    to_text,
)
from sepia.config import DEFAULT_CHARSET, DEFAULT_STYLE
from sepia.glitch import DURATION, FRAME_SECONDS, glitch_ansi, restore_ansi
from sepia.ipc import Channel, Message, Session, connect
from sepia.mouse import MOUSE_OFF, MOUSE_ON, MouseParser, read_input
from sepia.raster import enhance, fit_image

POLL_SECONDS = 0.01
"""How long to wait for a message before checking the window size again."""
RESIZE_SETTLE_SECONDS = 0.15
"""A resize drag fires many sizes; redraw once the window has stopped changing."""


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


@lru_cache(maxsize=2)
def _picture(path: str) -> Image.Image:
    with Image.open(path) as image:
        return enhance(image)


class Hover:
    """Glitches the picture around the mouse pointer and heals it afterwards."""

    def __init__(self, write: Callable[[str], object]) -> None:
        self._write = write
        self._parser = MouseParser()
        self._rng = random.Random()
        self._point: tuple[int, int] | None = None
        self._moved_at = 0.0
        self._drawn: tuple[int, int] | None = None
        self._frame_at = 0.0

    def start(self) -> None:
        self._write(MOUSE_ON)

    def stop(self) -> None:
        self._write(MOUSE_OFF)

    def forget(self) -> None:
        """The screen was redrawn; nothing is glitched any more."""
        self._drawn = None

    def step(self, art: SymbolArt | None, typed: str) -> None:
        """Take new pointer reports and draw the next glitch frame if one is due."""
        point = self._parser.feed(typed) if typed else None
        now = time.monotonic()
        if art is None:
            return
        if point is not None:
            col, row = point
            if 0 <= col < art.cols and 0 <= row < art.rows:
                self._heal(art)
                self._point, self._moved_at = point, now
        if self._point is None:
            return
        age = now - self._moved_at
        if age >= DURATION:
            self._heal(art)
            self._point = None
        elif now - self._frame_at >= FRAME_SECONDS:
            strength = 1.0 - age / DURATION
            self._write(glitch_ansi(art, *self._point, strength, self._rng))
            self._drawn, self._frame_at = self._point, now

    def _heal(self, art: SymbolArt) -> None:
        if self._drawn is not None:
            self._write(restore_ansi(art, *self._drawn))
            self._drawn = None


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
    with console.screen(hide_cursor=True) as screen:
        hover.start()
        try:
            size = console.size
            channel.send({"type": "size", "cols": size.width, "rows": size.height})
            dirty, changed_at = True, 0.0
            while True:
                try:
                    if channel.poll(POLL_SECONDS):
                        if not state.apply(channel.receive()):
                            return
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
                if dirty and time.monotonic() - changed_at >= RESIZE_SETTLE_SECONDS:
                    with contextlib.suppress(
                        OSError, UnidentifiedImageError, ValueError
                    ):
                        art = render_art(state, size.width, size.height)
                        frame = Text("") if art is None else _art_text(art)
                    screen.update(frame)
                    hover.forget()  # the full redraw wiped any glitch
                    dirty = False
                hover.step(art, read_input())
                console.file.flush()
        finally:
            hover.stop()


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
