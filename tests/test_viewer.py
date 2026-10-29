import contextlib
import io
import json
import re
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from rich.console import Console
from rich.text import Text

from sepia import viewer
from sepia.ascii_art import SymbolArt
from sepia.camera import CameraError
from sepia.ipc import Channel, Session
from sepia.mouse import MOUSE_OFF, MOUSE_ON
from sepia.painter import image_size
from sepia.ripple import DURATION, FRAME_SECONDS
from sepia.scene import Canvas
from sepia.viewer import (
    LIVE_FPS,
    Hover,
    LiveView,
    ViewerState,
    draw_frame,
    live_frame,
    render_frame,
)


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


def test_hover_start_and_stop_switch_mouse_reporting_on_and_off() -> None:
    written: list[str] = []
    hover = Hover(written.append)
    hover.start()
    hover.stop()
    assert written == [MOUSE_ON, MOUSE_OFF], f"Got {written!r}"


def test_hover_pointer_before_the_first_picture_draws_nothing() -> None:
    written: list[str] = []
    Hover(written.append).step(None, "\x1b[<35;10;5M")
    assert written == [], f"There is no picture to ripple, but got {written!r}"


def test_hover_pointer_outside_the_picture_draws_nothing() -> None:
    written: list[str] = []
    hover = Hover(written.append)
    hover.step(_gray_art(), "\x1b[<35;90;5M")  # the art is 40 columns wide
    assert written == [], f"No ripple belongs outside the grid, got {written!r}"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Time for the viewer module; a test moves it by changing `clock[0]`."""
    now = [100.0]
    fake = types.SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(viewer, "time", fake)
    return now


def test_hover_frames_are_limited_to_the_frame_rate(clock: list[float]) -> None:
    written: list[str] = []
    hover = Hover(written.append)
    hover.step(_gray_art(), "\x1b[<35;10;5M")
    clock[0] += FRAME_SECONDS / 4
    hover.step(_gray_art(), "")
    assert len(written) == 1, f"A second frame came too soon: {len(written)}"
    clock[0] += FRAME_SECONDS
    hover.step(_gray_art(), "")
    assert len(written) == 2, f"The next frame was not drawn: {len(written)}"


def test_hover_finished_ripple_is_erased_once_then_the_hover_goes_quiet(
    clock: list[float],
) -> None:
    written: list[str] = []
    hover = Hover(written.append)
    hover.step(_gray_art(), "\x1b[<35;10;5M")
    clock[0] += DURATION + 0.5
    hover.step(_gray_art(), "")
    assert len(written) == 2, f"Expected a frame that heals the picture: {written!r}"
    assert written[1].endswith("\x1b[0m"), "The healing frame must reset the colors"
    clock[0] += 1.0
    hover.step(_gray_art(), "")
    assert len(written) == 2, "Nothing may be drawn once the picture has healed"


def test_hover_pointer_far_from_the_last_ring_adds_a_ring(
    clock: list[float],
) -> None:
    def second_frame(report: str) -> str:
        written: list[str] = []
        hover = Hover(written.append)
        hover.step(_gray_art(), "\x1b[<35;10;5M")
        written.clear()
        clock[0] += FRAME_SECONDS * 2
        hover.step(_gray_art(), report)
        return written[0]

    near = second_frame("\x1b[<35;11;5M")  # one cell away: too close for a ring
    far = second_frame("\x1b[<35;30;5M")
    assert len(far) > len(near), "A far pointer must redraw more cells than a near one"


class _FakeConnection:
    """The viewer's end of the link: replays `incoming`, records what is sent."""

    def __init__(
        self, incoming: list[bytes], fail_sends_after: int | None = None
    ) -> None:
        self.incoming = incoming
        self.sent: list[dict] = []
        self.closed = False
        self._idle_polls = 0
        self._fail_sends_after = fail_sends_after

    def send_bytes(self, buf: bytes) -> None:
        limit = self._fail_sends_after
        if limit is not None and len(self.sent) >= limit:
            raise OSError("the prompt is gone")
        self.sent.append(json.loads(buf))

    def recv_bytes(self) -> bytes:
        if not self.incoming:
            raise EOFError
        return self.incoming.pop(0)

    def poll(self, timeout: float | None = None) -> bool:
        """Messages waiting; once idle for long enough the prompt "hangs up" (EOF)."""
        self._idle_polls = 0 if self.incoming else self._idle_polls + 1
        return bool(self.incoming) or self._idle_polls > 20

    def close(self) -> None:
        self.closed = True


def _wire(*messages: dict) -> list[bytes]:
    return [json.dumps(message).encode("utf-8") for message in messages]


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@pytest.fixture
def window() -> tuple[Console, io.StringIO]:
    out = io.StringIO()
    console = Console(
        file=out,
        force_terminal=True,
        legacy_windows=False,
        color_system="truecolor",
        width=30,
        height=10,
        highlight=False,
    )
    return console, out


@pytest.fixture(autouse=True)
def no_keyboard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read the real terminal; tests that need keys replace this."""
    monkeypatch.setattr(viewer, "read_input", lambda: "")


def test_loop_announces_its_size_and_draws_each_picture_sent(
    picture: str, window: tuple[Console, io.StringIO]
) -> None:
    console, out = window
    link = _FakeConnection(
        _wire({"type": "image", "path": picture, "style": "fill", "charset": "classic"})
    )
    viewer._loop(Channel(link), console)
    assert link.sent == [{"type": "size", "cols": 30, "rows": 10}], link.sent
    shown = _ANSI.sub("", out.getvalue())
    expected = render_frame(ViewerState(path=picture, style="fill"), 30, 10)
    for line in expected.plain.split("\n"):
        assert line in shown, f"Row {line!r} was not drawn"
    assert MOUSE_ON in out.getvalue(), "Mouse reporting was not switched on"
    assert MOUSE_OFF in out.getvalue(), "Mouse reporting was not switched off"


def test_loop_bye_message_ends_the_loop_and_restores_the_mouse(
    window: tuple[Console, io.StringIO],
) -> None:
    console, out = window
    link = _FakeConnection(_wire({"type": "bye"}, {"type": "clear"}))
    viewer._loop(Channel(link), console)
    assert len(link.incoming) == 1, "Messages after bye must stay unread"
    assert MOUSE_OFF in out.getvalue(), "The mouse must be released on the way out"


@pytest.mark.parametrize("garbage", [b"[1, 2]", b"not json", b"\xff\xfe"])
def test_loop_unreadable_message_ends_the_loop(
    window: tuple[Console, io.StringIO], garbage: bytes
) -> None:
    console, out = window
    viewer._loop(Channel(_FakeConnection([garbage])), console)
    assert MOUSE_OFF in out.getvalue(), f"{garbage!r} must end the loop cleanly"


def test_loop_picture_that_cannot_be_read_leaves_a_blank_window(
    tmp_path: Path, window: tuple[Console, io.StringIO]
) -> None:
    console, out = window
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"this is not a picture")
    link = _FakeConnection(
        _wire({"type": "image", "path": str(tmp_path / "missing.png")})
        + _wire({"type": "image", "path": str(broken)})
    )
    viewer._loop(Channel(link), console)
    shown = _ANSI.sub("", out.getvalue().replace(MOUSE_ON, "").replace(MOUSE_OFF, ""))
    assert shown.strip() == "", f"A bad picture must draw nothing, got {shown!r}"


def _drive(
    monkeypatch: pytest.MonkeyPatch,
    link: _FakeConnection,
    script: dict[int, Callable[[], str | None]],
) -> None:
    """Run `script[n]` on the n-th keyboard read of the loop (it may return keys)."""
    passes = iter(range(1000))

    def keyboard() -> str:
        action = script.get(next(passes))
        return (action() if action else "") or ""

    monkeypatch.setattr(viewer, "read_input", keyboard)


def _say_bye(link: _FakeConnection) -> Callable[[], None]:
    return lambda: link.incoming.extend(_wire({"type": "bye"}))


def test_loop_resize_redraws_to_the_new_size_and_tells_the_prompt(
    picture: str, window: tuple[Console, io.StringIO], monkeypatch: pytest.MonkeyPatch
) -> None:
    console, out = window
    monkeypatch.setattr(viewer, "RESIZE_SETTLE_SECONDS", 0.0)
    link = _FakeConnection(_wire({"type": "image", "path": picture}))

    def shrink() -> None:
        console.size = (20, 6)  # the user dragged the window smaller

    _drive(monkeypatch, link, {0: shrink, 1: _say_bye(link)})
    viewer._loop(Channel(link), console)
    assert link.sent == [
        {"type": "size", "cols": 30, "rows": 10},
        {"type": "size", "cols": 20, "rows": 6},
    ], f"Sizes sent: {link.sent}"
    smaller = render_frame(ViewerState(path=picture), 20, 6).plain.split("\n")
    assert smaller[0] in _ANSI.sub("", out.getvalue()), "Not redrawn at the new size"


def test_loop_resize_waits_until_the_window_stops_changing(
    picture: str, window: tuple[Console, io.StringIO], monkeypatch: pytest.MonkeyPatch
) -> None:
    console, out = window
    link = _FakeConnection(_wire({"type": "image", "path": picture}))
    drawn_before = {}

    def shrink() -> None:
        drawn_before["length"] = len(out.getvalue())
        monkeypatch.setattr(viewer, "RESIZE_SETTLE_SECONDS", 3600.0)
        console.size = (20, 6)

    _drive(monkeypatch, link, {0: shrink, 3: _say_bye(link)})
    viewer._loop(Channel(link), console)
    assert {"type": "size", "cols": 20, "rows": 6} in link.sent, "Size not reported"
    after = _ANSI.sub("", out.getvalue()[drawn_before["length"] :])
    smaller = render_frame(ViewerState(path=picture), 20, 6).plain.split("\n")
    assert smaller[0] not in after, "A drag in progress must not redraw the picture"


def test_loop_resize_survives_a_prompt_that_stopped_listening(
    window: tuple[Console, io.StringIO], monkeypatch: pytest.MonkeyPatch
) -> None:
    console, out = window
    link = _FakeConnection([], fail_sends_after=1)

    def shrink() -> None:
        console.size = (20, 6)
        link.incoming.extend(_wire({"type": "bye"}))

    _drive(monkeypatch, link, {0: shrink})
    link.incoming.extend(_wire({"type": "style", "style": "ink"}))
    viewer._loop(Channel(link), console)
    assert len(link.sent) == 1, "Only the first size message could be delivered"
    assert MOUSE_OFF in out.getvalue(), "The loop must end normally"


def test_loop_pointer_report_ripples_the_drawn_picture(
    picture: str, window: tuple[Console, io.StringIO], monkeypatch: pytest.MonkeyPatch
) -> None:
    console, out = window
    link = _FakeConnection(_wire({"type": "image", "path": picture}))
    _drive(
        monkeypatch,
        link,
        {0: lambda: "\x1b[<35;10;5M", 1: _say_bye(link)},
    )
    viewer._loop(Channel(link), console)
    assert "\x1b[5;" in out.getvalue(), "No ripple was drawn around row 5"


def _use_window(
    monkeypatch: pytest.MonkeyPatch, console: Console, link: _FakeConnection
) -> list[Session]:
    connected: list[Session] = []

    def fake_connect(found: Session) -> Channel:
        connected.append(found)
        return Channel(link)

    monkeypatch.setattr(viewer, "connect", fake_connect)
    monkeypatch.setattr(viewer, "Console", lambda **options: console)
    return connected


def test_run_viewer_connects_with_the_saved_session_and_closes_the_link(
    tmp_path: Path,
    window: tuple[Console, io.StringIO],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console, out = window
    session = Session(port=4321, authkey=b"secret-key")
    session_file = tmp_path / "session.json"
    session.save(session_file)
    link = _FakeConnection(_wire({"type": "bye"}))
    connected = _use_window(monkeypatch, console, link)
    assert viewer.run_viewer(session_file) == 0, "A normal exit must return 0"
    assert connected == [session], f"Connected with {connected}"
    assert link.closed, "The link must be closed on the way out"
    assert "\x1b]0;sepia\x07" in out.getvalue(), "The window title was not set"


def test_run_viewer_ctrl_c_still_exits_cleanly_and_closes_the_link(
    tmp_path: Path,
    window: tuple[Console, io.StringIO],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console, out = window
    session_file = tmp_path / "session.json"
    Session(port=1, authkey=b"k").save(session_file)
    link = _FakeConnection([])

    def interrupt() -> str:
        raise KeyboardInterrupt

    _use_window(monkeypatch, console, link)
    monkeypatch.setattr(viewer, "read_input", interrupt)
    # Keep the link open so only the keyboard read can stop the loop.
    monkeypatch.setattr(link, "poll", lambda timeout=None: False)
    assert viewer.run_viewer(session_file) == 0, "Ctrl+C must not be an error"
    assert link.closed, "The link must be closed after Ctrl+C"
    assert MOUSE_OFF in out.getvalue(), "The mouse must be released after Ctrl+C"


def _recording_quiet_console(events: list[str]) -> Callable[[], object]:
    @contextlib.contextmanager
    def quiet() -> Iterator[None]:
        events.append("quiet")
        yield
        events.append("restored")

    return quiet


def test_no_echo_leaves_a_piped_stdin_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(viewer, "_quiet_console", _recording_quiet_console(events))
    with viewer._no_echo():
        events.append("inside")
    assert events == ["inside"], f"The console was touched: {events}"


def test_no_echo_quiets_a_real_console_for_the_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(viewer, "_quiet_console", _recording_quiet_console(events))
    with viewer._no_echo():
        events.append("inside")
    assert events == ["quiet", "inside", "restored"], f"Got {events}"


class _FakeKernel32:
    """A console whose mode flags the test can read back."""

    def __init__(self, mode: int | None) -> None:
        self.mode = mode
        self.set_to: list[int] = []
        self.flushed = False

    def GetStdHandle(self, which: int) -> int:
        assert which == -10, f"Expected the input handle, asked for {which}"
        return 7

    def GetConsoleMode(self, handle: int, out: object) -> int:
        if self.mode is None:
            return 0
        out._obj.value = self.mode  # type: ignore[attr-defined]
        return 1

    def SetConsoleMode(self, handle: int, mode: int) -> int:
        self.set_to.append(mode)
        return 1

    def FlushConsoleInputBuffer(self, handle: int) -> int:
        self.flushed = True
        return 1


@pytest.fixture
def kernel32(monkeypatch: pytest.MonkeyPatch) -> Callable[[int | None], _FakeKernel32]:
    import ctypes

    def install(mode: int | None) -> _FakeKernel32:
        fake = _FakeKernel32(mode)
        windll = types.SimpleNamespace(kernel32=fake)
        monkeypatch.setattr(ctypes, "windll", windll, raising=False)
        return fake

    return install


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console modes")
def test_quiet_console_clears_echo_and_restores_the_mode_afterwards(
    kernel32: Callable[[int | None], _FakeKernel32],
) -> None:
    original = 0x0004 | 0x0002 | 0x0040 | 0x0001
    console = kernel32(original)
    with viewer._quiet_console():
        quiet = console.set_to[-1]
        assert quiet & (0x0004 | 0x0002 | 0x0040) == 0, f"Echo flags left: {quiet:#x}"
        assert quiet & 0x0200, "Virtual terminal input must be on"
        assert quiet & 0x0001, "Unrelated flags must be kept"
        assert not console.flushed, "Nothing may be flushed while quiet"
    assert console.set_to[-1] == original, "The original mode was not restored"
    assert console.flushed, "Typed keys must be dropped on the way out"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console modes")
def test_quiet_console_without_a_console_changes_nothing(
    kernel32: Callable[[int | None], _FakeKernel32],
) -> None:
    console = kernel32(None)
    with viewer._quiet_console():
        pass
    assert console.set_to == [], f"The mode was set: {console.set_to}"
    assert not console.flushed, "Nothing may be flushed without a console"


# --- the camera, live --------------------------------------------------------------


class FakeCamera:
    """Stands in for the webcam, which is hardware: one fixed frame (or none), or a
    camera that cannot open."""

    def __init__(self, frame: np.ndarray | None = None, error: str = "") -> None:
        self.frame = frame
        self.error = error
        self.failed = False
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1
        if self.error:
            raise CameraError(self.error)

    def latest(self) -> np.ndarray | None:
        return self.frame

    def stop(self) -> None:
        self.stopped += 1


def _frame() -> np.ndarray:
    """A 160x90 RGB frame: red with a blue square, like the test picture."""
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[:, :] = (200, 40, 40)
    frame[30:60, 60:100] = (40, 40, 200)
    return frame


ON = {"type": "camera", "on": True}


def _live(camera: FakeCamera) -> tuple[LiveView, list[str]]:
    written: list[str] = []
    return LiveView(written.append, lambda: camera), written


def test_live_view_on_starts_the_camera_and_says_so_with_the_first_frame() -> None:
    camera = FakeCamera(_frame())
    live, written = _live(camera)
    assert live.handle(ON, 30, 10) is None, "On is said once a frame is drawn"
    assert live.active and camera.started == 1, "The camera must be started"
    reply = live.step(30, 10, "ink", "classic")
    assert reply == {"type": "camera", "state": "on"}, f"Replied {reply}"
    assert len(written) == 1 and "\x1b[10;1H" in written[0], "A whole frame is drawn"


def test_live_view_camera_that_cannot_open_replies_the_error() -> None:
    live, _ = _live(FakeCamera(error="no camera answered"))
    reply = live.handle(ON, 30, 10)
    assert reply == {"type": "camera", "error": "no camera answered"}, f"Got {reply}"
    assert not live.active, "No camera, no live view"


def test_live_view_on_twice_starts_the_camera_once() -> None:
    camera = FakeCamera(_frame())
    live, _ = _live(camera)
    live.handle(ON, 30, 10)
    live.handle(ON, 30, 10)
    assert camera.started == 1, f"Started {camera.started} times"


def test_live_view_off_stops_the_camera() -> None:
    camera = FakeCamera(_frame())
    live, _ = _live(camera)
    live.handle(ON, 30, 10)
    assert live.handle({"type": "camera", "on": False}, 30, 10) is None, "No reply"
    assert not live.active and camera.stopped == 1, "The camera must be let go"


def test_live_view_keep_saves_the_frame_at_the_window_shape_and_stops(
    tmp_path: Path,
) -> None:
    camera = FakeCamera(_frame())
    live, _ = _live(camera)
    live.handle(ON, 30, 10)
    path = str(tmp_path / "03.png")
    reply = live.handle({"type": "camera", "keep": path}, 30, 10)
    assert reply == {"type": "camera", "state": "kept", "path": path}, f"Got {reply}"
    with Image.open(path) as kept:
        expected = image_size(Canvas(30, 10).aspect)
        assert kept.size == expected, (
            f"Kept at {kept.size}, the paint size is {expected}"
        )
        red = kept.getpixel((2, 2))
    assert red == (200, 40, 40), f"The frame's colors must be kept, got {red}"
    assert not live.active and camera.stopped == 1, "Keeping a frame stops the camera"


@pytest.mark.parametrize(
    ("frame", "keep"),
    [(None, "03.png"), (_frame(), 42)],
    ids=["no frame", "no path"],
)
def test_live_view_keep_without_a_frame_or_a_path_replies_an_error(
    tmp_path: Path, frame: np.ndarray | None, keep: object
) -> None:
    live, _ = _live(FakeCamera(frame))
    live.handle(ON, 30, 10)
    target = str(tmp_path / keep) if isinstance(keep, str) else keep
    reply = live.handle({"type": "camera", "keep": target}, 30, 10)
    assert reply is not None and "error" in reply, f"Replied {reply}"
    assert not live.active, "The live view must stop"
    assert list(tmp_path.iterdir()) == [], "Nothing may be saved"


def test_live_view_keep_while_off_replies_an_error(tmp_path: Path) -> None:
    live, _ = _live(FakeCamera(_frame()))
    reply = live.handle({"type": "camera", "keep": str(tmp_path / "a.png")}, 30, 10)
    assert reply is not None and "error" in reply, f"Replied {reply}"


def test_live_view_frames_are_limited_to_the_frame_rate(clock: list[float]) -> None:
    live, written = _live(FakeCamera(_frame()))
    live.handle(ON, 30, 10)
    live.step(30, 10, "ink", "classic")
    clock[0] += 1 / LIVE_FPS / 4
    live.step(30, 10, "ink", "classic")
    assert len(written) == 1, f"A second frame came too soon: {len(written)}"
    clock[0] += 1 / LIVE_FPS
    assert live.step(30, 10, "ink", "classic") is None, "On is said only once"
    assert len(written) == 2, f"The next frame was not drawn: {len(written)}"


def test_live_view_without_a_frame_yet_draws_nothing() -> None:
    live, written = _live(FakeCamera(None))
    live.handle(ON, 30, 10)
    assert live.step(30, 10, "ink", "classic") is None, "Nothing to say yet"
    assert written == [], f"Nothing to draw, got {written!r}"


def test_live_view_lost_camera_stops_and_replies_an_error() -> None:
    camera = FakeCamera(_frame())
    live, _ = _live(camera)
    live.handle(ON, 30, 10)
    camera.failed = True
    reply = live.step(30, 10, "ink", "classic")
    assert reply is not None and "error" in reply, f"Replied {reply}"
    assert not live.active and camera.stopped == 1, "A lost camera must be let go"


@pytest.mark.parametrize("style", ["ink", "fill"])
def test_live_frame_draws_every_cell_of_the_window(style: str) -> None:
    ansi = live_frame(_frame(), 30, 10, style, "classic")
    shown = _ANSI.sub("", ansi)
    assert len(shown) == 300, f"Expected 30x10 cells, got {len(shown)}"
    assert ("\x1b[48;2;" in ansi) == (style == "fill"), "Only fill paints backgrounds"


def test_loop_camera_on_draws_live_then_keep_shows_the_kept_frame(
    tmp_path: Path, window: tuple[Console, io.StringIO], monkeypatch: pytest.MonkeyPatch
) -> None:
    console, out = window
    camera = FakeCamera(_frame())
    monkeypatch.setattr(viewer, "Camera", lambda: camera)
    path = str(tmp_path / "02.png")
    link = _FakeConnection(_wire(ON))
    keep = {"type": "camera", "keep": path}
    _drive(
        monkeypatch,
        link,
        {0: lambda: link.incoming.extend(_wire(keep)), 1: _say_bye(link)},
    )
    viewer._loop(Channel(link), console)
    assert link.sent[1:] == [
        {"type": "camera", "state": "on"},
        {"type": "camera", "state": "kept", "path": path},
    ], f"Replies {link.sent}"
    kept = render_frame(ViewerState(path=path), 30, 10).plain.split("\n")
    assert kept[0] in _ANSI.sub("", out.getvalue()), "The kept frame must be drawn"


def test_loop_leaving_lets_go_of_the_camera(
    window: tuple[Console, io.StringIO], monkeypatch: pytest.MonkeyPatch
) -> None:
    console, _ = window
    camera = FakeCamera(_frame())
    monkeypatch.setattr(viewer, "Camera", lambda: camera)
    link = _FakeConnection(_wire(ON, {"type": "bye"}))
    viewer._loop(Channel(link), console)
    assert camera.stopped == 1, "The camera must be released on the way out"
