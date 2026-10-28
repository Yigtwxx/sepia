"""The picture window: full screen, nothing but the drawing."""

import contextlib
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast, get_args

from rich.console import Console
from rich.text import Text

from sepia.ascii_art import CELL_HEIGHT, CELL_WIDTH, ArtStyle, image_to_art, to_text
from sepia.config import DEFAULT_STYLE
from sepia.ipc import Channel, Message, Session, connect
from sepia.raster import RenderError, render_svg

POLL_SECONDS = 0.05
"""How long to wait for a message before checking the window size again."""
RESIZE_SETTLE_SECONDS = 0.15
"""A resize drag fires many sizes; redraw once the window has stopped changing."""


@dataclass
class ViewerState:
    svg: str | None = None
    style: ArtStyle = DEFAULT_STYLE

    def apply(self, message: Message) -> bool:
        """Update from one message; False means the prompt asked the viewer to quit."""
        kind = message.get("type")
        if kind == "bye":
            return False
        if kind == "scene" and isinstance(message.get("svg"), str):
            self.svg = message["svg"]
        if kind == "clear":
            self.svg = None
        style = message.get("style")
        if kind in ("scene", "style") and style in get_args(ArtStyle):
            self.style = cast(ArtStyle, style)
        return True


def render_frame(state: ViewerState, cols: int, rows: int) -> Text:
    """The picture sized to the window, or a blank screen before the first one."""
    if state.svg is None or cols <= 0 or rows <= 0:
        return Text("")
    return _art_text(state.svg, state.style, cols, rows)


@lru_cache(maxsize=4)
def _art_text(svg: str, style: ArtStyle, cols: int, rows: int) -> Text:
    pixels = render_svg(svg, cols * CELL_WIDTH, rows * CELL_HEIGHT)
    return to_text(image_to_art(pixels, cols, rows, style))


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
    with console.screen(hide_cursor=True) as screen:
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
                with contextlib.suppress(RenderError):
                    frame = render_frame(state, size.width, size.height)
                screen.update(frame)
                dirty = False


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
        echo_and_line = 0x0004 | 0x0002  # ENABLE_ECHO_INPUT | ENABLE_LINE_INPUT
        kernel32.SetConsoleMode(handle, mode.value & ~echo_and_line)
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
