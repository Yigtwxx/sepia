import pytest

from sepia.viewer import ViewerState, render_frame


def test_viewer_state_scene_message_sets_svg_and_style(wide_svg: str) -> None:
    state = ViewerState()
    keep_going = state.apply({"type": "scene", "svg": wide_svg, "style": "ink"})
    assert keep_going, "A scene message must not stop the viewer"
    assert state.svg == wide_svg, "SVG was not stored"
    assert state.style == "ink", f"Expected ink, got {state.style}"


def test_viewer_state_clear_message_forgets_picture(wide_svg: str) -> None:
    state = ViewerState(svg=wide_svg)
    state.apply({"type": "clear"})
    assert state.svg is None, "Clear must forget the picture"


@pytest.mark.parametrize(
    "message",
    [{"type": "style", "style": "neon"}, {"type": "scene", "svg": 42}, {"type": "?"}],
)
def test_viewer_state_malformed_message_changes_nothing(
    wide_svg: str, message: dict
) -> None:
    state = ViewerState(svg=wide_svg, style="fill")
    state.apply(message)
    assert (state.svg, state.style) == (wide_svg, "fill"), f"Changed by {message}"


def test_viewer_state_bye_message_stops_viewer() -> None:
    assert not ViewerState().apply({"type": "bye"}), "Bye must stop the viewer"


def test_render_frame_before_first_picture_is_blank() -> None:
    frame = render_frame(ViewerState(), 80, 24)
    assert frame.plain == "", f"Expected a blank frame, got {frame.plain!r}"


def test_render_frame_fills_the_window(wide_svg: str) -> None:
    lines = render_frame(ViewerState(svg=wide_svg), 30, 10).plain.split("\n")
    assert len(lines) == 10, f"Expected 10 rows, got {len(lines)}"
    assert {len(line) for line in lines} == {30}, "Every row must span the window"
