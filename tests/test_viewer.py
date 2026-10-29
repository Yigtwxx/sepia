import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from rich.console import Console
from rich.text import Text

from sepia.ascii_art import SymbolArt
from sepia.viewer import Hover, ViewerState, draw_frame, render_frame


@pytest.fixture
def picture(tmp_path: Path) -> str:
    path = tmp_path / "01.png"
    image = Image.new("RGB", (200, 100), (200, 40, 40))
    image.paste((40, 40, 200), (80, 30, 120, 70))
    image.save(path)
    return str(path)


def test_viewer_state_image_message_sets_path_style_and_charset(picture: str) -> None:
    state = ViewerState()
    message = {"type": "image", "path": picture, "style": "fill", "charset": "symbols"}
    assert state.apply(message), "An image message must not stop the viewer"
    assert state.path == picture, "Path was not stored"
    assert (state.style, state.charset) == ("fill", "symbols"), "Options not applied"


def test_viewer_state_clear_message_forgets_picture(picture: str) -> None:
    state = ViewerState(path=picture)
    state.apply({"type": "clear"})
    assert state.path is None, "Clear must forget the picture"


@pytest.mark.parametrize(
    "message",
    [
        {"type": "style", "style": "neon"},
        {"type": "style", "charset": "emoji"},
        {"type": "image", "path": 42},
        {"type": "?"},
    ],
)
def test_viewer_state_malformed_message_changes_nothing(
    picture: str, message: dict
) -> None:
    state = ViewerState(path=picture, style="ink", charset="classic")
    state.apply(message)
    current = (state.path, state.style, state.charset)
    assert current == (picture, "ink", "classic"), f"Changed by {message}"


def test_viewer_state_bye_message_stops_viewer() -> None:
    assert not ViewerState().apply({"type": "bye"}), "Bye must stop the viewer"


def test_render_frame_before_first_picture_is_blank() -> None:
    frame = render_frame(ViewerState(), 80, 24)
    assert frame.plain == "", f"Expected a blank frame, got {frame.plain!r}"


def test_render_frame_fills_the_window(picture: str) -> None:
    lines = render_frame(ViewerState(path=picture), 30, 10).plain.split("\n")
    assert len(lines) == 10, f"Expected 10 rows, got {len(lines)}"
    assert {len(line) for line in lines} == {30}, "Every row must span the window"


def test_draw_frame_starts_at_the_top_left_wherever_the_cursor_was() -> None:
    out = io.StringIO()
    console = Console(file=out, force_terminal=True, width=12, height=3)
    with console.screen() as screen:
        console.file.write("\x1b[2;7H")  # a ripple left the cursor mid-screen
        out.seek(0)
        out.truncate()
        draw_frame(console, screen, Text("abc\ndef\nghi"))
    drawn = out.getvalue()
    assert drawn.startswith("\x1b[H"), f"Frame must start from home, got {drawn!r}"


def _gray_art() -> SymbolArt:
    return SymbolArt(
        np.full((12, 40), "a"), np.full((12, 40, 3), 100, dtype=np.uint8), None
    )


def test_hover_pointer_report_drops_a_ripple_under_the_pointer() -> None:
    written: list[str] = []
    hover = Hover(written.append)
    hover.step(_gray_art(), "[<35;10;5M")
    assert any("[5;" in chunk for chunk in written), f"Got {written!r}"


def test_hover_after_a_full_redraw_draws_nothing() -> None:
    written: list[str] = []
    hover = Hover(written.append)
    hover.step(_gray_art(), "[<35;10;5M")
    hover.forget()
    written.clear()
    hover.step(_gray_art(), "")
    assert written == [], f"A redraw wiped the ripples, but got {written!r}"
