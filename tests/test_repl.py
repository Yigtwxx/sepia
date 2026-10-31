import io
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from PIL import Image
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sepia import config, repl, ui
from sepia.chatbar import Resized
from sepia.config import Settings
from sepia.director import Director
from sepia.ipc import Session
from sepia.launcher import LaunchError
from sepia.painter import FallbackPainter, PainterError, Painting, Source
from sepia.painter import image_size as paint_size
from sepia.reference import Reference
from sepia.repl import (
    Command,
    Interrupts,
    Repl,
    Transcript,
    named_option,
    new_session_dir,
    parse_command,
)
from sepia.scene import Canvas
from sepia.usage import Earlier, Ledger


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("/style ink", Command("style", "ink")),
        ("/NEW", Command("new", "")),
        ("/charset   Symbols ", Command("charset", "Symbols")),
        ("/add Snowy Peaks", Command("add", "Snowy Peaks")),
        ("şelale", None),
        ("a /slash inside", None),
    ],
)
def test_parse_command_splits_slash_commands_only(
    line: str, expected: Command | None
) -> None:
    assert parse_command(line) == expected, f"{line!r} parsed as {parse_command(line)}"


@pytest.mark.parametrize(
    ("argument", "expected"),
    [("fill", "fill"), ("INK", "ink"), ("", None), ("x", None)],
)
def test_named_option_matches_only_listed_options(
    argument: str, expected: str | None
) -> None:
    result = named_option(("ink", "fill"), argument)
    assert result == expected, f"{argument!r}: expected {expected}, got {result}"


def test_new_session_dir_keeps_only_the_newest_folders(tmp_path: Path) -> None:
    for index in range(5):
        old = tmp_path / f"2020010{index}-000000-000000"
        old.mkdir()
        os.utime(old, (time.time(), time.time()))
    folder = new_session_dir(tmp_path, keep=3)
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert folder.exists(), "The new session folder must exist"
    assert len(remaining) == 3, f"Expected 3 folders, got {remaining}"
    assert folder.name in remaining, "The new folder must never be pruned"


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_interrupts_second_ctrl_c_soon_after_the_first_leaves() -> None:
    clock = Clock()
    interrupts = Interrupts(window=2.0, clock=clock)
    first = interrupts.press()
    clock.now += 1.0
    second = interrupts.press()
    assert (first, second) == (False, True), f"Got {(first, second)}"


def test_interrupts_second_ctrl_c_after_the_window_starts_over() -> None:
    clock = Clock()
    interrupts = Interrupts(window=2.0, clock=clock)
    interrupts.press()
    clock.now += 3.0
    assert interrupts.press() is False, "A late second press must not leave"
    assert interrupts.armed, "The late press arms the next one"


def test_interrupts_armed_only_inside_the_window() -> None:
    clock = Clock()
    interrupts = Interrupts(window=2.0, clock=clock)
    before = interrupts.armed
    interrupts.press()
    during = interrupts.armed
    clock.now += 2.5
    assert (before, during, interrupts.armed) == (False, True, False), (
        f"Got {(before, during, interrupts.armed)}"
    )


def _console(width: int) -> tuple[Console, io.StringIO]:
    out = io.StringIO()
    return Console(file=out, width=width, color_system=None), out


def test_transcript_replay_prints_what_was_said_at_the_new_width() -> None:
    console, out = _console(40)
    transcript = Transcript(console)
    transcript.say(Panel(Text("hello"), expand=True))
    transcript.say()
    console.width = 20
    out.seek(0)
    out.truncate()
    transcript.replay()
    rows = out.getvalue().splitlines()
    widths = [len(row) for row in rows[:3]]
    assert widths == [20, 20, 20], f"The box must fit 20 columns, got {rows!r}"
    assert rows[3:] == [""], f"The empty line must come back, got {rows!r}"


def test_transcript_clear_forgets_what_was_said() -> None:
    console, out = _console(40)
    transcript = Transcript(console)
    transcript.say(Text("old"))
    transcript.clear()
    out.seek(0)
    out.truncate()
    transcript.replay()
    assert out.getvalue() == "", f"Got {out.getvalue()!r}"


def test_first_run_keeps_typed_keys_and_skips_empty_ones(terminal, env_file) -> None:
    keys, _ = terminal
    keys.send_text("sk-test\r\r")  # Enter alone skips Cloudflare
    done = repl._first_run(Console(file=io.StringIO()), ui.Words())
    lines = env_file.read_text().splitlines()
    assert done, "The Anthropic key was given, so sepia must start"
    assert lines == ["ANTHROPIC_API_KEY=sk-test"], f"Got {lines}"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test", "Keys must hold at once"


def test_first_run_without_the_anthropic_key_stops(terminal, env_file) -> None:
    keys, _ = terminal
    keys.send_text("\r")
    done = repl._first_run(Console(file=io.StringIO()), ui.Words())
    assert not done, "sepia cannot start without the Anthropic key"
    assert not env_file.exists(), "Nothing typed, nothing saved"


# --- the prompt window -------------------------------------------------------------

DOWN = "\x1b[B"


class StubPainter:
    """Stands in for the Cloudflare and local painters, whose HTTP and torch are
    external: records every call and paints a solid picture, or fails."""

    def __init__(self, source: Source, error: PainterError | None = None) -> None:
        self.source = source
        self.error = error
        self.calls: list[tuple[Any, ...]] = []
        self.loads = 0
        self.picture = Image.new("RGB", (64, 40), (200, 120, 60))

    def paint(self, prompt, size, seed, reference=None, likeness=None) -> Painting:
        self.calls.append((prompt, size, seed, reference, likeness))
        if self.error is not None:
            raise self.error
        return Painting(self.picture, self.source, 1.5)

    def load_in_background(self) -> None:
        self.loads += 1


class FakeHost:
    """The IPC host without its socket: records what is sent to the viewer. The
    viewer "opens" (connects) as soon as the host starts waiting for it."""

    def __init__(self, on_message: Callable[[Any], None]) -> None:
        self.on_message = on_message
        self.session = Session(port=1, authkey=b"key")
        self.connected = False
        self.opens_viewer = True
        self.sent: list[dict[str, Any]] = []
        self.accepting = 0
        self.closed = False
        self.answers: list[dict[str, Any]] = []
        """What the viewer replies, in turn, to camera messages that wait for one.
        A kept frame is written where the prompt asked for it."""

    def accept_in_background(self) -> None:
        self.accepting += 1
        self.connected = self.opens_viewer

    def wait_connected(self, timeout: float) -> bool:
        return self.connected

    def send(self, message: dict[str, Any]) -> bool:
        if not self.connected:
            return False
        self.sent.append(message)
        waits = message.get("on") is True or "keep" in message
        if message.get("type") == "camera" and waits and self.answers:
            answer = self.answers.pop(0)
            if answer.get("state") == "kept":
                Image.new("RGB", (64, 40), (90, 90, 90)).save(message["keep"])
            self.on_message(answer)
        return True

    def close(self) -> None:
        self.closed = True


PLAIN_REPLY: dict[str, object] = {
    "message": "A calm lake.",
    "prompt": "a lake at dawn",
    "edit": False,
    "references": [],
    "subject": "",
    "show": False,
}


@dataclass
class Rig:
    """A prompt window wired to fakes for its painters, viewer and window launch."""

    repl: Repl
    out: io.StringIO
    host: FakeHost
    local: StubPainter
    launched: list[Path]
    folder: Path
    client: MagicMock
    set_message: Callable[..., None]
    make_message: Callable[..., Any]

    def say(self, line: str) -> bool:
        return self.repl._handle(line)

    def printed(self) -> str:
        return self.out.getvalue()

    def forget_printed(self) -> None:
        self.out.truncate(0)
        self.out.seek(0)

    def direct(self, **fields: object) -> None:
        """What Claude answers from now on; `fields` override a plain reply."""
        self.set_message(self.make_message({**PLAIN_REPLY, **fields}))

    def direct_each(self, *replies: dict[str, object]) -> None:
        """Claude's answers to the next calls, in order; each overrides a plain
        reply."""
        stream = self.client.beta.messages.stream.return_value.__enter__.return_value
        stream.get_final_message.side_effect = [
            self.make_message({**PLAIN_REPLY, **fields}) for fields in replies
        ]


def _reference(url: str = "https://example.com/a.png") -> Reference:
    return Reference(url, Image.new("RGB", (300, 200), (10, 90, 200)))


@pytest.fixture(autouse=True)
def isolated_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, private_config_dir: Path
) -> None:
    """Pictures saved by /save stay in the test's folder, the spinner and resize
    waits are near-instant, and no `SEPIA_*` setting comes from the shell."""
    private_config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(repl, "pictures_dir", lambda: tmp_path / "pictures")
    monkeypatch.setattr(repl, "FRAME_SECONDS", 0.001)
    monkeypatch.setattr(repl, "RESIZE_SETTLE_SECONDS", 0.0)
    for variable in ("SEPIA_EFFORT", "SEPIA_MODEL", "SEPIA_STYLE", "SEPIA_CHARSET"):
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def rig(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_client: MagicMock,
    set_final_message: Callable[..., None],
    make_message: Callable[..., Any],
) -> Rig:
    launched: list[Path] = []
    monkeypatch.setattr(repl, "Host", FakeHost)
    monkeypatch.setattr(repl, "open_viewer", launched.append)
    out = io.StringIO()
    console = Console(file=out, width=200, color_system=None)
    folder = tmp_path / "session"
    folder.mkdir()
    local = StubPainter("local")
    window = Repl(
        console,
        ui.Words(),
        Settings(),
        Director(fake_client, "claude-haiku-5-5", "high"),
        None,
        cast(Any, local),
        folder,
        Ledger(tmp_path / "config" / "usage.json", lambda: Earlier()),
    )
    made = Rig(
        window,
        out,
        cast(FakeHost, window.host),
        local,
        launched,
        folder,
        fake_client,
        set_final_message,
        make_message,
    )
    made.direct()
    return made


def _with_cloudflare(rig: Rig, primary: StubPainter) -> FallbackPainter:
    """Give the rig a Cloudflare chain: `primary`, then the rig's local painter."""
    chain = FallbackPainter(primary, cast(Any, rig.local))
    rig.repl.api = chain
    rig.repl.paint_with = "api"
    return chain


def _choices() -> dict[str, Any]:
    return json.loads(config.choices_file().read_text(encoding="utf-8"))


def test_host_without_a_hostname_names_the_text_itself() -> None:
    assert repl._host("https://upload.example.org/x.png") == "upload.example.org"
    assert repl._host("picture.png") == "picture.png", "No host: show the text"


# --- plain commands ----------------------------------------------------------------


def test_repl_help_prints_the_command_table(rig: Rig) -> None:
    keep_going = rig.say("/help")
    assert keep_going, "/help must not close sepia"
    assert "/charset" in rig.printed(), f"No command list in {rig.printed()!r}"


@pytest.mark.parametrize("name", ["exit", "quit", "q"])
def test_repl_exit_commands_ask_to_close(rig: Rig, name: str) -> None:
    assert rig.say(f"/{name}") is False, f"/{name} must close sepia"


def test_repl_unknown_command_says_so_and_keeps_going(rig: Rig) -> None:
    keep_going = rig.say("/nope")
    assert keep_going, "A typo must not close sepia"
    assert "No such command /nope" in rig.printed(), rig.printed()
    assert rig.client.beta.messages.stream.call_count == 0, "No request for a command"


def test_repl_usage_shows_a_closable_panel_without_leaving_a_trace(
    rig: Rig, terminal
) -> None:
    keys, screen = terminal
    keys.send_text("q")
    rig.say("/usage")
    assert "Usage" in screen.getvalue(), "The usage panel must be drawn"
    assert "Usage" not in rig.printed(), "The panel must not enter the transcript"


def test_repl_clear_forgets_the_picture_and_tells_the_viewer(rig: Rig) -> None:
    rig.say("a lake")
    rig.forget_printed()
    rig.say("/clear")
    assert rig.repl.scene.is_empty, "The scene must start over"
    assert rig.host.sent[-1] == {"type": "clear"}, f"Sent {rig.host.sent[-1]}"
    assert "a lake" not in rig.printed(), "The old transcript must be gone"
    assert "Welcome to sepia" in rig.printed(), "The welcome box must come back"


def test_repl_add_without_text_explains_the_usage(rig: Rig) -> None:
    rig.say("/add")
    assert "Say what to add" in rig.printed(), rig.printed()
    assert rig.local.calls == [], "Nothing may be painted"
    assert rig.client.beta.messages.stream.call_count == 0, "Claude must not be asked"


# --- choices -----------------------------------------------------------------------


def test_repl_model_named_switches_director_and_is_remembered(rig: Rig) -> None:
    rig.say("/model Sonnet")
    assert rig.repl.director.model == "claude-sonnet-5-5", rig.repl.director.model
    assert _choices()["model"] == "claude-sonnet-5-5", "Must be kept for later"
    assert "Model: sonnet-5-5" in rig.printed(), rig.printed()


def test_repl_model_menu_picks_the_option_under_the_pointer(rig: Rig, terminal) -> None:
    keys, _ = terminal
    keys.send_text(f"{DOWN}\r")  # haiku is current; one down is sonnet
    rig.say("/model")
    assert rig.repl.director.model == "claude-sonnet-5-5", rig.repl.director.model


def test_repl_model_menu_cancelled_changes_nothing(rig: Rig, terminal) -> None:
    keys, _ = terminal
    keys.send_text("\x03")
    rig.say("/model")
    assert rig.repl.director.model == "claude-haiku-5-5", "Model must stay"
    assert not config.choices_file().exists(), "Nothing may be remembered"
    assert "Model:" not in rig.printed(), "No confirmation for a cancelled menu"


def test_repl_effort_named_switches_director_and_is_remembered(rig: Rig) -> None:
    rig.say("/effort max")
    assert rig.repl.director.effort == "max", rig.repl.director.effort
    assert _choices()["effort"] == "max", "Effort must be kept for later"
    assert "Effort: max" in rig.printed(), rig.printed()


@pytest.mark.parametrize(("argument", "expected"), [("on", True), ("off", False)])
def test_repl_mature_named_switches_director_and_is_remembered(
    rig: Rig, argument: str, expected: bool
) -> None:
    rig.repl.director.mature = not expected
    rig.say(f"/mature {argument}")
    assert rig.repl.director.mature is expected, f"/mature {argument}"
    assert _choices()["mature"] is expected, "Switch must be kept for later"
    assert f"Mature pictures {argument}" in rig.printed(), rig.printed()


def test_repl_style_named_updates_viewer_and_is_remembered(rig: Rig) -> None:
    rig.host.connected = True
    rig.say("/style fill")
    expected = {"type": "style", "style": "fill", "charset": "classic"}
    assert rig.host.sent == [expected], f"Viewer got {rig.host.sent}"
    assert _choices()["style"] == "fill", "Style must be kept for later"
    assert "Style: fill · charset: classic" in rig.printed(), rig.printed()


def test_repl_charset_named_updates_viewer_and_is_remembered(rig: Rig) -> None:
    rig.host.connected = True
    rig.say("/charset symbols")
    expected = {"type": "style", "style": "ink", "charset": "symbols"}
    assert rig.host.sent == [expected], f"Viewer got {rig.host.sent}"
    assert _choices()["charset"] == "symbols", "Charset must be kept"


@pytest.mark.parametrize("command", ["/style", "/charset"])
def test_repl_style_menu_cancelled_leaves_viewer_alone(
    rig: Rig, terminal, command: str
) -> None:
    keys, _ = terminal
    keys.send_text("\x03")
    rig.host.connected = True
    rig.say(command)
    assert rig.host.sent == [], f"The viewer must hear nothing, got {rig.host.sent}"
    assert not config.choices_file().exists(), "Nothing may be remembered"


def test_repl_style_unlisted_name_opens_the_menu(rig: Rig, terminal) -> None:
    keys, _ = terminal
    keys.send_text("2")  # the second option: fill
    rig.say("/style bogus")
    assert rig.repl.style == "fill", f"The menu's pick must win, got {rig.repl.style}"


# --- picture requests --------------------------------------------------------------


def test_repl_request_paints_the_direction_and_shows_the_picture(rig: Rig) -> None:
    rig.say("a lake")
    scene = rig.repl.scene
    prompt, size, seed, reference, likeness = rig.local.calls[0]
    assert prompt == "a lake at dawn", f"Painted {prompt!r}"
    assert size == paint_size(rig.repl.canvas.aspect), f"Painted at {size}"
    assert seed == scene.seed, "The scene's seed must be used"
    assert reference is None and likeness is None, "A new picture has no reference"
    assert scene.requests == ["a lake"], f"Scene holds {scene.requests}"
    assert scene.prompts == ["a lake at dawn"], f"Scene holds {scene.prompts}"
    saved = rig.folder / "01.png"
    assert saved.exists(), "The picture must be kept in the session folder"
    assert rig.host.sent[-1] == {
        "type": "image",
        "path": str(saved),
        "style": "ink",
        "charset": "classic",
    }, f"Viewer got {rig.host.sent[-1]}"
    assert "A calm lake." in rig.printed(), "Claude's message must be shown"
    assert "local GPU · 1.5s" in rig.printed(), "The painter and time must be shown"


def test_repl_request_opens_the_picture_window_once(rig: Rig) -> None:
    rig.say("a lake")
    rig.say("a river")
    assert rig.launched == [rig.repl.session_file], f"Opened {rig.launched}"
    assert rig.host.accepting == 1, "The host must wait for the viewer once"
    names = [p.name for p in sorted(rig.folder.glob("*.png"))]
    assert names == ["01.png", "02.png"], f"Kept {names}"


def test_repl_request_tallies_usage_for_session_and_all_time(rig: Rig) -> None:
    rig.say("a lake")
    session, total = rig.repl.usage, rig.repl.ledger.read().total
    assert (session.requests, session.pictures) == (1, {"local": 1}), session
    assert (total.requests, total.pictures) == (1, {"local": 1}), total
    assert session.input_tokens == 1200, f"Tokens counted: {session.input_tokens}"


def test_repl_add_keeps_the_scene_and_paints_over_the_last_picture(rig: Rig) -> None:
    rig.say("a lake")
    first, seed = rig.repl.scene.image, rig.repl.scene.seed
    rig.direct(edit=True, prompt="a lake with swans")
    rig.say("/add swans")
    _, _, used_seed, reference, _ = rig.local.calls[1]
    assert reference is first, "/add must paint over the previous picture"
    assert used_seed == seed, "The seed must stay for the same composition"
    assert rig.repl.scene.requests == ["a lake", "swans"], rig.repl.scene.requests


def test_repl_add_on_an_empty_scene_paints_a_new_picture(rig: Rig) -> None:
    rig.say("/add swans")
    assert rig.local.calls[0][3] is None, "No picture to build on yet"
    assert rig.repl.scene.requests == ["swans"], rig.repl.scene.requests


def test_repl_new_request_starts_a_new_scene(rig: Rig) -> None:
    rig.say("a lake")
    old_seed = rig.repl.scene.seed
    rig.say("a river")
    assert rig.repl.scene.requests == ["a river"], rig.repl.scene.requests
    assert rig.repl.scene.seed != old_seed, "A new picture needs fresh noise"


@pytest.mark.parametrize(
    ("stop_reason", "text"), [("refusal", "declined"), ("max_tokens", "cut off")]
)
def test_repl_request_failed_direction_explains_and_paints_nothing(
    rig: Rig, make_message, set_final_message, stop_reason: str, text: str
) -> None:
    set_final_message(make_message({}, stop_reason=stop_reason))
    rig.say("a lake")
    assert text in rig.printed(), f"Expected {text!r} in {rig.printed()!r}"
    assert rig.local.calls == [], "Nothing may be painted after a failure"
    assert rig.repl.usage.requests == 0, "A failed request is not counted"
    assert rig.repl.scene.is_empty, "The scene must stay untouched"


def test_repl_request_malformed_reply_says_so(
    rig: Rig, make_message, set_final_message
) -> None:
    set_final_message(make_message("not json"))
    rig.say("a lake")
    assert "malformed" in rig.printed(), rig.printed()


def test_repl_request_paint_failure_names_the_error_and_hints_at_cloudflare(
    rig: Rig,
) -> None:
    rig.local.error = PainterError("out of memory")
    rig.say("a lake")
    assert "Could not paint the picture: out of memory" in rig.printed(), rig.printed()
    assert "/keys cloudflare" in rig.printed(), "Without Cloudflare, say how to add it"
    assert rig.repl.scene.is_empty, "A failed picture must not enter the scene"
    assert list(rig.folder.glob("*.png")) == [], "Nothing may be saved"


def test_repl_request_cloudflare_failure_is_named_beside_the_local_result(
    rig: Rig,
) -> None:
    primary = StubPainter("api", PainterError("rate limited", rate_limited=True))
    _with_cloudflare(rig, primary)
    rig.say("a lake")
    assert "local GPU · 1.5s · rate limited" in rig.printed(), rig.printed()
    assert len(primary.calls) == 1 and len(rig.local.calls) == 1, "Tried both"


def test_repl_request_both_painters_failing_report_both_errors(rig: Rig) -> None:
    _with_cloudflare(rig, StubPainter("api", PainterError("cloud down")))
    rig.local.error = PainterError("no gpu")
    rig.say("a lake")
    assert "cloud down; no gpu" in rig.printed(), rig.printed()
    assert "/keys cloudflare" not in rig.printed(), "Cloudflare is set up here"


def test_repl_request_cloudflare_success_shows_its_source(rig: Rig) -> None:
    _with_cloudflare(rig, StubPainter("api"))
    rig.say("a lake")
    assert "cloudflare · 1.5s" in rig.printed(), rig.printed()
    assert rig.local.calls == [], "The local model must stay idle"
    assert rig.repl.usage.pictures == {"api": 1}, rig.repl.usage.pictures


def test_repl_request_painter_choice_local_skips_cloudflare(rig: Rig) -> None:
    primary = StubPainter("api")
    _with_cloudflare(rig, primary)
    rig.repl.paint_with = "local"
    rig.say("a lake")
    assert primary.calls == [], "/local means Cloudflare is not used"
    assert len(rig.local.calls) == 1, "The local painter must paint"


# --- clarifying questions ----------------------------------------------------------

VAGUE = {
    "message": "A spiral galaxy.",
    "prompt": "a galaxy guess",
    "questions": [
        {
            "header": "Subject",
            "question": "What should it show?",
            "multi": False,
            "options": [
                {"label": "A galaxy", "description": "spiral arms"},
                {"label": "A black hole", "description": "a bright disk"},
            ],
        }
    ],
}
CLEAR = {"message": "A black hole.", "prompt": "a black hole", "questions": []}


def test_repl_vague_request_asks_then_paints_from_the_answers(
    rig: Rig, terminal
) -> None:
    keys, _ = terminal
    rig.repl.director.ask = True
    rig.direct_each(VAGUE, CLEAR)
    keys.send_text("2")
    rig.say("universe")
    painted = [call[0] for call in rig.local.calls]
    assert painted == ["a black hole"], f"The answered direction must paint: {painted}"
    calls = rig.client.beta.messages.stream.call_args_list
    second = calls[1].kwargs["messages"][0]["content"]
    assert "Subject: What should it show? A black hole" in second, second
    requests = rig.repl.scene.requests
    assert requests == ["universe (Subject: A black hole)"], f"Kept {requests}"
    assert "· Subject  A black hole" in rig.printed(), rig.printed()
    assert "A black hole." in rig.printed(), "The second message must be shown"


def test_repl_skipped_questions_paint_the_guess_with_one_call(
    rig: Rig, terminal
) -> None:
    keys, _ = terminal
    rig.repl.director.ask = True
    rig.direct_each(VAGUE, CLEAR)
    keys.send_text("\x1b")
    rig.say("universe")
    painted = [call[0] for call in rig.local.calls]
    assert painted == ["a galaxy guess"], f"The guess must paint: {painted}"
    count = rig.client.beta.messages.stream.call_count
    assert count == 1, f"Skipping must not ask Claude again, asked {count} times"
    assert "Skipped the questions" in rig.printed(), rig.printed()


def test_repl_cancelled_questions_paint_nothing_and_keep_the_scene(
    rig: Rig, terminal
) -> None:
    keys, _ = terminal
    rig.say("a lake")
    before = rig.repl.scene
    rig.repl.director.ask = True
    rig.direct_each(VAGUE, CLEAR)
    keys.send_text("\x03")
    keep_going = rig.say("universe")
    assert keep_going, "Ctrl+C in the questions must not close sepia"
    assert len(rig.local.calls) == 1, "Nothing new may be painted"
    assert rig.repl.scene is before, "The scene must stay as it was"
    assert "Cancelled, nothing painted" in rig.printed(), rig.printed()


def test_repl_config_flips_both_switches_and_remembers_them(rig: Rig, terminal) -> None:
    keys, _ = terminal
    keys.send_text(f"\r{DOWN} \x1b")
    rig.say("/config")
    assert rig.repl.director.ask is True, "Clarifying questions must be on"
    assert rig.repl.director.mature is True, "Mature pictures must be on"
    kept = _choices()
    assert kept["ask"] is True and kept["mature"] is True, f"Kept {kept}"
    assert "Clarifying questions on" in rig.printed(), rig.printed()
    assert "Mature pictures on" in rig.printed(), rig.printed()


def test_repl_config_closed_unchanged_says_nothing(rig: Rig, terminal) -> None:
    keys, _ = terminal
    keys.send_text("\x1b")
    rig.say("/config")
    assert not config.choices_file().exists(), "Nothing may be remembered"
    assert "Clarifying questions" not in rig.printed(), rig.printed()


# --- references --------------------------------------------------------------------


def test_repl_request_with_a_link_paints_after_the_linked_picture(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = _reference()
    asked: list[Any] = []
    monkeypatch.setattr(
        repl, "find_reference", lambda links: asked.append(links) or found
    )
    rig.say("a cat like https://example.com/a.png")
    assert asked == [("https://example.com/a.png",)], f"Looked up {asked}"
    assert rig.local.calls[0][4] is found, "The painter must get the likeness"
    assert rig.repl.scene.likeness is found, "The scene keeps the likeness"
    assert rig.repl.scene.requests == ["a cat like"], "The link is not a request"
    assert "after a picture from example.com" in rig.printed(), rig.printed()
    call = rig.client.beta.messages.stream.call_args
    content = call.kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image", "Claude must see the linked picture"


def test_repl_bare_link_shows_the_picture_as_it_is(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = _reference()
    monkeypatch.setattr(repl, "find_reference", lambda links: found)
    rig.say("https://example.com/a.png")
    assert rig.client.beta.messages.stream.call_count == 0, "Claude is not needed"
    assert rig.local.calls == [], "Nothing is painted"
    assert rig.repl.scene.image is not None, "The picture must enter the scene"
    assert rig.repl.scene.image.size == paint_size(rig.repl.canvas.aspect)
    assert rig.repl.scene.prompts == [""], "No prompt for a shown picture"
    assert (rig.folder / "01.png").exists(), "The shown picture is kept too"
    assert "Showing the picture you linked." in rig.printed(), rig.printed()
    assert "shown as found · example.com" in rig.printed(), rig.printed()


def test_repl_unusable_bare_link_warns_and_stops(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repl, "find_reference", lambda links: None)
    rig.say("https://example.com/a.png")
    assert "no usable picture" in rig.printed(), rig.printed()
    assert rig.client.beta.messages.stream.call_count == 0, "Nothing to direct"
    assert rig.repl.scene.is_empty, "No picture"


def test_repl_unusable_link_with_words_warns_and_still_paints(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repl, "find_reference", lambda links: None)
    rig.say("a cat https://example.com/a.png")
    assert "no usable picture" in rig.printed(), rig.printed()
    assert len(rig.local.calls) == 1, "The words alone still make a picture"
    assert rig.local.calls[0][4] is None, "No likeness"


def test_repl_named_subject_is_searched_and_painted_from_its_look(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = _reference("https://wiki.example.org/yunara.png")
    asked: list[Any] = []

    def search(subject, links, key, *, mature=False):
        asked.append((subject, tuple(links), key, mature))
        return found, 1

    monkeypatch.setattr(repl, "find_subject", search)
    rig.repl.search_key = "brave"
    rig.repl.director.mature = True
    rig.direct(subject="Yunara", references=["https://a.example/p"])
    rig.say("yunara in a lake")
    assert asked == [("Yunara", ("https://a.example/p",), "brave", True)], asked
    assert rig.client.beta.messages.stream.call_count == 2, "Claude sees it again"
    assert rig.local.calls[0][4] is found, "The painter must copy the look"
    assert rig.repl.usage.image_searches == 1, "The search must be counted"
    assert rig.repl.ledger.read().total.image_searches == 1, "And kept for all time"
    assert rig.repl.usage.referenced == 1, "A referenced picture is counted"
    assert "after a picture from wiki.example.org" in rig.printed(), rig.printed()


def test_repl_named_subject_with_show_presents_the_found_picture(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = _reference("https://wiki.example.org/yunara.png")
    monkeypatch.setattr(repl, "find_subject", lambda *a, **k: (found, 0))
    rig.direct(subject="Yunara", show=True, message="Here is Yunara.")
    rig.say("yunara")
    assert rig.local.calls == [], "A bare name is shown, not painted"
    assert rig.client.beta.messages.stream.call_count == 1, "One call to Claude"
    assert "Here is Yunara." in rig.printed(), rig.printed()
    assert "shown as found · wiki.example.org" in rig.printed(), rig.printed()


def test_repl_named_subject_not_found_says_so_and_paints_from_words(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repl, "find_subject", lambda *a, **k: (None, 1))
    rig.direct(subject="Yunara")
    rig.say("yunara")
    assert "Found no usable picture of Yunara" in rig.printed(), rig.printed()
    assert len(rig.local.calls) == 1 and rig.local.calls[0][4] is None
    assert rig.client.beta.messages.stream.call_count == 1, "No second call"
    assert rig.repl.usage.image_searches == 1, "The failed search still counts"


def test_repl_subject_not_found_without_a_name_uses_a_generic_one(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repl, "find_subject", lambda *a, **k: (None, 0))
    rig.direct(references=["https://a.example/p"])
    rig.say("someone")
    assert "picture of the subject" in rig.printed(), rig.printed()


# --- the picture window ------------------------------------------------------------


def test_repl_viewer_not_opened_twice_within_the_gap(rig: Rig) -> None:
    rig.host.opens_viewer = False
    rig.repl._ensure_viewer()
    rig.repl._ensure_viewer()
    assert len(rig.launched) == 1, f"Window opened {len(rig.launched)} times"
    rig.repl._ensure_viewer(force=True)
    assert len(rig.launched) == 2, "force must open a new window"


def test_repl_viewer_connected_is_left_alone(rig: Rig) -> None:
    rig.host.connected = True
    rig.repl._ensure_viewer(force=True)
    assert rig.launched == [], "A connected viewer needs no new window"


def test_repl_viewer_launch_failure_is_told_in_the_transcript(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(session_file: Path) -> None:
        raise LaunchError("no terminal")

    monkeypatch.setattr(repl, "open_viewer", refuse)
    rig.host.opens_viewer = False
    rig.repl._ensure_viewer()
    assert "Could not open the picture window: no terminal" in rig.printed()
    rig.repl._ensure_viewer()
    assert rig.host.accepting == 2, "A failed launch must not block the next try"


def test_repl_picture_is_resent_once_a_closed_window_is_reopened(rig: Rig) -> None:
    rig.host.connected = False
    rig.repl._show(rig.folder / "01.png")
    assert rig.launched == [rig.repl.session_file], "The window must reopen"
    assert [m["type"] for m in rig.host.sent] == ["image"], rig.host.sent


def test_repl_picture_not_resent_when_the_window_never_comes_back(rig: Rig) -> None:
    rig.host.opens_viewer = False
    rig.repl._show(rig.folder / "01.png")
    assert rig.host.sent == [], "Nobody to show it to"


@pytest.mark.parametrize(
    ("message", "size"),
    [
        ({"type": "size", "cols": 100, "rows": 30}, (100, 30)),
        ({"type": "size", "cols": 0, "rows": 30}, None),
        ({"type": "size", "cols": "9", "rows": 30}, None),
        ({"type": "size", "cols": 100}, None),
        ({"type": "other", "cols": 100, "rows": 30}, None),
    ],
)
def test_repl_viewer_size_message_resizes_the_canvas_only_when_valid(
    rig: Rig, message: dict[str, Any], size: tuple[int, int] | None
) -> None:
    before = rig.repl.canvas
    rig.host.on_message(message)
    expected = Canvas(*size) if size else before
    assert rig.repl.canvas == expected, f"{message}: canvas {rig.repl.canvas}"


# --- /undo and /again --------------------------------------------------------------


def test_repl_undo_brings_back_the_picture_before_and_its_scene(rig: Rig) -> None:
    rig.say("a lake")
    lake = rig.repl.scene
    rig.say("a river")
    rig.say("/undo")
    assert rig.repl.scene is lake, "The lake's scene must come back"
    shown = rig.host.sent[-1]
    assert shown["path"] == str(rig.folder / "01.png"), f"Viewer got {shown}"
    assert "Back to: a lake" in rig.printed(), rig.printed()


def test_repl_undo_after_add_lets_add_build_on_the_restored_picture(rig: Rig) -> None:
    rig.say("a lake")
    first = rig.repl.scene.image
    rig.direct(edit=True, prompt="a lake with swans")
    rig.say("/add swans")
    rig.say("/undo")
    rig.say("/add boats")
    assert rig.local.calls[2][3] is first, "/add must paint over the restored picture"
    assert rig.repl.scene.requests == ["a lake", "boats"], rig.repl.scene.requests


def test_repl_undo_past_the_first_picture_clears_the_window(rig: Rig) -> None:
    rig.say("a lake")
    rig.say("/undo")
    assert rig.repl.scene.is_empty, "Before the first picture there was none"
    assert rig.host.sent[-1] == {"type": "clear"}, f"Viewer got {rig.host.sent[-1]}"
    assert "Back to an empty window" in rig.printed(), rig.printed()


def test_repl_undo_with_nothing_left_says_so(rig: Rig) -> None:
    rig.say("/undo")
    assert "Nothing to undo" in rig.printed(), rig.printed()
    assert rig.host.sent == [], f"The viewer must hear nothing, got {rig.host.sent}"


def test_repl_undo_after_clear_brings_the_picture_back(rig: Rig) -> None:
    rig.say("a lake")
    rig.say("/clear")
    rig.say("/undo")
    assert rig.repl.scene.requests == ["a lake"], rig.repl.scene.requests
    assert rig.host.sent[-1]["type"] == "image", f"Viewer got {rig.host.sent[-1]}"


def test_repl_failed_new_request_keeps_the_picture_before(rig: Rig) -> None:
    rig.say("a lake")
    lake = rig.repl.scene
    rig.local.error = PainterError("out of memory")
    rig.say("a river")
    assert rig.repl.scene is lake, "A failed picture must not replace the scene"
    assert lake.requests == ["a lake"], f"The scene was emptied: {lake.requests}"
    assert lake.image is not None, "The old picture must stay for /save and /add"


@pytest.fixture
def fixed_seed(monkeypatch: pytest.MonkeyPatch) -> int:
    """The seed /again draws; the test knows it in advance."""
    monkeypatch.setattr(repl, "new_seed", lambda: 4242)
    return 4242


def test_repl_again_repaints_the_last_prompt_with_new_noise_without_claude(
    rig: Rig, fixed_seed: int
) -> None:
    rig.say("a lake")
    rig.say("/again")
    prompt, _, seed, reference, _ = rig.local.calls[1]
    assert prompt == "a lake at dawn", f"Painted {prompt!r}"
    assert seed == fixed_seed == rig.repl.scene.seed, f"Painted with seed {seed}"
    assert reference is None, "A new picture is painted over nothing"
    calls = rig.client.beta.messages.stream.call_count
    assert calls == 1, f"Claude must not be asked again, asked {calls} times"
    assert rig.repl.scene.requests == ["a lake"], "The request stays the same"
    shown = rig.host.sent[-1]
    assert shown["path"] == str(rig.folder / "02.png"), f"Viewer got {shown}"
    assert rig.repl.usage.pictures == {"local": 2}, rig.repl.usage.pictures
    assert "Painted again" in rig.printed(), rig.printed()
    assert rig.printed().count("local GPU · 1.5s") == 2, "Painter and time are shown"


def test_repl_again_after_add_paints_over_the_same_picture(
    rig: Rig, fixed_seed: int
) -> None:
    rig.say("a lake")
    first = rig.repl.scene.image
    rig.direct(edit=True, prompt="a lake with swans")
    rig.say("/add swans")
    rig.say("/again")
    prompt, _, _, reference, _ = rig.local.calls[2]
    assert prompt == "a lake with swans", f"Painted {prompt!r}"
    assert reference is first, "/again must paint over what /add painted over"


def test_repl_again_keeps_the_likeness(
    rig: Rig, fixed_seed: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = _reference()
    monkeypatch.setattr(repl, "find_reference", lambda links: found)
    rig.say("a cat like https://example.com/a.png")
    rig.say("/again")
    assert rig.local.calls[1][4] is found, "The painter must copy the same look"


def test_repl_again_can_be_undone(rig: Rig, fixed_seed: int) -> None:
    rig.say("a lake")
    lake = rig.repl.scene
    rig.say("/again")
    rig.say("/undo")
    assert rig.repl.scene is lake, "/undo must bring the first painting back"


def test_repl_again_on_a_shown_picture_explains_and_paints_nothing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repl, "find_reference", lambda links: _reference())
    rig.say("https://example.com/a.png")
    rig.say("/again")
    assert "shown as it is" in rig.printed(), rig.printed()
    assert rig.local.calls == [], "Nothing may be painted"


def test_repl_again_without_a_picture_says_so(rig: Rig) -> None:
    rig.say("/again")
    assert "Nothing to paint again yet" in rig.printed(), rig.printed()
    assert rig.local.calls == [], "Nothing may be painted"


def test_repl_again_paint_failure_keeps_the_picture(rig: Rig, fixed_seed: int) -> None:
    rig.say("a lake")
    lake = rig.repl.scene
    rig.local.error = PainterError("out of memory")
    rig.say("/again")
    assert rig.repl.scene is lake, "A failed picture must not replace the scene"
    assert "Could not paint the picture: out of memory" in rig.printed()


# --- /cam --------------------------------------------------------------------------

CAMERA_ON = {"type": "camera", "state": "on"}
KEPT = {"type": "camera", "state": "kept"}
CAMERA_OFF = {"type": "camera", "on": False}


@pytest.fixture
def camera(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> FakeHost:
    """The rig's viewer, with OpenCV installed; set its `answers` to script it.
    A camera that never answers gives up at once."""
    monkeypatch.setattr(repl, "camera_installed", lambda: True)
    monkeypatch.setattr(repl, "CAMERA_SECONDS", 0.05)
    return rig.host


def test_repl_cam_without_the_extra_explains_the_install(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repl, "camera_installed", lambda: False)
    rig.say("/cam")
    assert "sepia-cli[cam]" in rig.printed(), rig.printed()
    assert rig.host.sent == [], f"The viewer must hear nothing, got {rig.host.sent}"
    assert not rig.repl.camera_live, "The camera must stay off"


def test_repl_cam_turns_the_camera_on_in_the_window(rig: Rig, camera: FakeHost) -> None:
    camera.answers = [CAMERA_ON]
    rig.say("/cam")
    assert rig.launched == [rig.repl.session_file], "The window must open for it"
    assert camera.sent[-1] == {"type": "camera", "on": True}, f"Sent {camera.sent}"
    assert rig.repl.camera_live, "The prompt must know the camera is live"
    assert "Camera on" in rig.printed(), rig.printed()


def test_repl_cam_failure_explains_where_to_allow_the_camera(
    rig: Rig, camera: FakeHost
) -> None:
    camera.answers = [{"type": "camera", "error": "no camera answered"}]
    rig.say("/cam")
    assert "The camera did not work: no camera answered" in rig.printed()
    hint = {"win32": "Privacy & security", "darwin": "Privacy & Security"}
    if sys.platform in hint:
        assert hint[sys.platform] in rig.printed(), "Say where to allow the camera"
    assert not rig.repl.camera_live, "A camera that failed is not live"


def test_repl_cam_without_an_answer_in_time_gives_up_and_stops_it(
    rig: Rig, camera: FakeHost
) -> None:
    rig.say("/cam")
    assert "did not answer in time" in rig.printed(), rig.printed()
    assert camera.sent[-1] == CAMERA_OFF, "A camera that opens late must be stopped"
    assert not rig.repl.camera_live, "No answer, no live camera"


def test_repl_cam_without_the_window_says_so(rig: Rig, camera: FakeHost) -> None:
    camera.opens_viewer = False
    rig.say("/cam")
    assert "picture window" in rig.printed(), rig.printed()
    assert not rig.repl.camera_live, "No window, no camera"


def test_repl_cam_again_keeps_the_frame_as_the_picture(
    rig: Rig, camera: FakeHost
) -> None:
    camera.answers = [CAMERA_ON, KEPT]
    rig.say("/cam")
    rig.say("/cam")
    path = rig.folder / "01.png"
    keep, shown = camera.sent[-2:]
    assert keep == {"type": "camera", "keep": str(path)}, f"Sent {keep}"
    assert shown["type"] == "image" and shown["path"] == str(path), f"Sent {shown}"
    scene = rig.repl.scene
    assert scene.requests == ["a frame from the camera"], scene.requests
    assert scene.prompts == [""], "A kept frame is shown as it is, not painted"
    assert scene.image is not None and scene.path == path, "The frame is the picture"
    assert not rig.repl.camera_live, "Keeping a frame stops the camera"
    assert "Kept this frame" in rig.printed(), rig.printed()
    assert rig.client.beta.messages.stream.call_count == 0, "Claude is not needed"


def test_repl_cam_keep_failure_says_why_and_keeps_the_scene(
    rig: Rig, camera: FakeHost
) -> None:
    camera.answers = [CAMERA_ON, {"type": "camera", "error": "no frame to keep"}]
    rig.say("/cam")
    rig.say("/cam")
    assert "The camera did not work: no frame to keep" in rig.printed()
    assert rig.repl.scene.is_empty, "No frame, no picture"
    assert not rig.repl.camera_live, "The viewer stopped the camera"


def test_repl_kept_frame_can_be_undone(rig: Rig, camera: FakeHost) -> None:
    rig.say("a lake")
    lake = rig.repl.scene
    camera.answers = [CAMERA_ON, KEPT]
    rig.say("/cam")
    rig.say("/cam")
    rig.say("/undo")
    assert rig.repl.scene is lake, "/undo must bring the painting back"


def test_repl_cam_off_stops_without_keeping(rig: Rig, camera: FakeHost) -> None:
    camera.answers = [CAMERA_ON]
    rig.say("/cam")
    rig.say("/cam off")
    assert camera.sent[-1] == CAMERA_OFF, f"Sent {camera.sent[-1]}"
    assert not rig.repl.camera_live, "The camera must be off"
    assert rig.repl.scene.is_empty, "Nothing is kept"
    assert "Camera off" in rig.printed(), rig.printed()


def test_repl_add_while_live_keeps_the_frame_then_paints_over_it(
    rig: Rig, camera: FakeHost
) -> None:
    camera.answers = [CAMERA_ON, KEPT]
    rig.say("/cam")
    rig.direct(edit=True, prompt="a portrait with a viking helmet")
    rig.say("/add a viking helmet")
    painted_over = rig.local.calls[0][3]
    assert painted_over is not None, "/add must paint over the kept frame"
    assert painted_over.size == (64, 40), "The frame the viewer kept is the base"
    expected = ["a frame from the camera", "a viking helmet"]
    assert rig.repl.scene.requests == expected, rig.repl.scene.requests


def test_repl_save_while_live_keeps_the_frame_then_saves_it(
    rig: Rig, camera: FakeHost, tmp_path: Path
) -> None:
    camera.answers = [CAMERA_ON, KEPT]
    rig.say("/cam")
    rig.say("/save")
    saved = list((tmp_path / "pictures").glob("*.png"))
    assert len(saved) == 1, f"Saved {saved}"
    assert rig.repl.scene.requests == ["a frame from the camera"], "Kept first"


def test_repl_request_while_live_stops_the_camera_first(
    rig: Rig, camera: FakeHost
) -> None:
    camera.answers = [CAMERA_ON]
    rig.say("/cam")
    rig.say("a lake")
    kinds = [message.get("on", message["type"]) for message in camera.sent]
    assert kinds.index(False) < kinds.index("image"), f"Sent in order {kinds}"
    assert not rig.repl.camera_live, "A new picture ends the live camera"


@pytest.mark.parametrize("command", ["/again", "/undo", "/clear"])
def test_repl_picture_commands_while_live_stop_the_camera(
    rig: Rig, camera: FakeHost, command: str
) -> None:
    camera.answers = [CAMERA_ON]
    rig.say("/cam")
    rig.say(command)
    assert CAMERA_OFF in camera.sent, f"{command} must stop the camera: {camera.sent}"
    assert not rig.repl.camera_live, f"{command} ends the live camera"


def test_repl_settings_while_live_leave_the_camera_on(
    rig: Rig, camera: FakeHost
) -> None:
    camera.answers = [CAMERA_ON]
    rig.say("/cam")
    rig.say("/style fill")
    assert rig.repl.camera_live, "/style changes the live view, it does not end it"
    assert CAMERA_OFF not in camera.sent, f"Sent {camera.sent}"


def test_repl_status_shows_the_live_camera(rig: Rig, camera: FakeHost) -> None:
    camera.answers = [CAMERA_ON]
    rig.say("/cam")
    assert "· camera ·" in rig.repl._status(), rig.repl._status()


def test_repl_camera_lost_later_marks_it_off(rig: Rig, camera: FakeHost) -> None:
    camera.answers = [CAMERA_ON]
    rig.say("/cam")
    rig.host.on_message({"type": "camera", "error": "the camera stopped"})
    assert not rig.repl.camera_live, "A lost camera is not live any more"


# --- /save -------------------------------------------------------------------------


def test_repl_save_without_a_picture_says_so(rig: Rig, tmp_path: Path) -> None:
    rig.say("/save")
    assert "Nothing to save yet" in rig.printed(), rig.printed()
    assert not (tmp_path / "pictures").exists(), "No folder for nothing"


def test_repl_save_writes_the_window_as_a_png(rig: Rig, tmp_path: Path) -> None:
    rig.say("a lake")
    rig.say("/save")
    saved = list((tmp_path / "pictures").glob("*.png"))
    assert len(saved) == 1, f"Saved {saved}"
    assert "Saved to" in rig.printed(), rig.printed()
    with Image.open(saved[0]) as picture:
        cols, rows = rig.repl.canvas.cols, rig.repl.canvas.rows
        assert picture.size == (cols * 12, rows * 24), f"PNG is {picture.size}"


def test_repl_save_failure_is_reported(rig: Rig, tmp_path: Path) -> None:
    (tmp_path / "pictures").write_text("a file where the folder should be")
    rig.say("a lake")
    rig.say("/save")
    assert "Could not save the picture" in rig.printed(), rig.printed()


# --- /api and /local ---------------------------------------------------------------


def test_repl_api_without_cloudflare_says_how_to_add_it(rig: Rig) -> None:
    rig.say("/api")
    assert "Cloudflare is not set up" in rig.printed(), rig.printed()
    assert rig.repl.paint_with == "local", "Painting must stay local"
    assert not config.choices_file().exists(), "Nothing to remember"


def test_repl_api_switches_back_and_ends_a_stop_after_the_free_day(rig: Rig) -> None:
    primary = StubPainter("api", PainterError("spent", out_of_credit=True))
    chain = _with_cloudflare(rig, primary)
    rig.say("a lake")
    primary.error = None
    rig.repl.paint_with = "local"
    rig.say("/api")
    assert rig.repl.paint_with == "api", "Cloudflare must paint again"
    assert _choices()["painter"] == "api", "The choice must be kept"
    assert "Painting with Cloudflare" in rig.printed(), rig.printed()
    rig.say("a river")
    assert chain.last_error is None, "The primary must have been tried again"
    assert len(primary.calls) == 2, "Cloudflare was skipped after being spent"


def test_repl_local_with_the_model_ready_loads_it_in_the_background(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repl, "local_model_ready", lambda model: True)
    rig.repl.paint_with = "api"
    rig.say("/local")
    assert rig.local.loads == 1, "The model must start loading"
    assert rig.repl.paint_with == "local", "Painting must move here"
    assert _choices()["painter"] == "local", "The choice must be kept"
    assert "Painting on this machine only" in rig.printed(), rig.printed()


def test_repl_local_without_the_extra_explains_the_install(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repl, "local_model_ready", lambda model: False)
    monkeypatch.setattr(repl, "local_installed", lambda: False)
    rig.repl.paint_with = "api"
    rig.say("/local")
    assert "sepia-cli[local]" in rig.printed(), rig.printed()
    assert rig.repl.paint_with == "api", "The painter must not change"
    assert rig.local.loads == 0, "Nothing to load"


def test_repl_local_download_declined_keeps_the_painter(
    rig: Rig, terminal, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys, _ = terminal
    keys.send_text("2")  # "no"
    downloads: list[str] = []
    monkeypatch.setattr(repl, "local_model_ready", lambda model: False)
    monkeypatch.setattr(repl, "local_installed", lambda: True)
    monkeypatch.setattr(repl, "download_local_model", downloads.append)
    rig.repl.paint_with = "api"
    rig.say("/local")
    assert downloads == [], "Nothing may be downloaded"
    assert "Not downloaded" in rig.printed(), rig.printed()
    assert rig.repl.paint_with == "api", "The painter must not change"


def test_repl_local_download_accepted_downloads_then_loads(
    rig: Rig, terminal, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys, _ = terminal
    keys.send_text("1")  # "yes"
    downloads: list[str] = []
    monkeypatch.setattr(repl, "local_model_ready", lambda model: False)
    monkeypatch.setattr(repl, "local_installed", lambda: True)
    monkeypatch.setattr(
        repl, "download_local_model", lambda model: downloads.append(model) or "path"
    )
    rig.say("/local")
    assert downloads == [rig.repl.settings.image_model], f"Downloaded {downloads}"
    assert rig.local.loads == 1, "The model must load after the download"
    assert rig.repl.paint_with == "local", "Painting must move here"


def test_repl_local_download_failure_is_reported_and_keeps_the_painter(
    rig: Rig, terminal, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys, _ = terminal
    keys.send_text("1")

    def fail(model: str) -> str:
        raise PainterError("disk full")

    monkeypatch.setattr(repl, "local_model_ready", lambda model: False)
    monkeypatch.setattr(repl, "local_installed", lambda: True)
    monkeypatch.setattr(repl, "download_local_model", fail)
    rig.repl.paint_with = "api"
    rig.say("/local")
    assert "Could not download the local model: disk full" in rig.printed()
    assert rig.local.loads == 0, "Nothing to load"
    assert rig.repl.paint_with == "api", "The painter must not change"


# --- /keys -------------------------------------------------------------------------


def test_repl_keys_cloudflare_saves_both_values_and_starts_painting_with_it(
    rig: Rig, terminal, env_file: Path
) -> None:
    keys, _ = terminal
    keys.send_text("account-1\rtoken-1\r")
    rig.say("/keys cloudflare")
    saved = env_file.read_text(encoding="utf-8").splitlines()
    assert saved == ["CLOUDFLARE_ACCOUNT_ID=account-1", "CLOUDFLARE_API_TOKEN=token-1"]
    assert os.environ["CLOUDFLARE_API_TOKEN"] == "token-1", "Keys must hold at once"
    assert isinstance(rig.repl.api, FallbackPainter), "The chain must be built"
    assert rig.repl.paint_with == "api", "A Cloudflare key just set is meant to paint"
    assert _choices()["painter"] == "api", "The painter must be kept"
    assert "Saved the cloudflare key" in rig.printed(), rig.printed()
    assert "token-1" not in rig.printed(), "A key must never be printed"


def test_repl_keys_anthropic_replaces_the_director_and_keeps_its_settings(
    rig: Rig, terminal, env_file: Path
) -> None:
    keys, _ = terminal
    keys.send_text("sk-new\r")
    old = rig.repl.director
    old.model, old.effort, old.mature = "claude-opus-5-5", "low", True
    rig.say("/keys anthropic")
    new = rig.repl.director
    assert new is not old, "The director needs the new key's client"
    assert (new.model, new.effort, new.mature) == ("claude-opus-5-5", "low", True)
    assert "ANTHROPIC_API_KEY=sk-new" in env_file.read_text(encoding="utf-8")


def test_repl_keys_brave_key_in_the_environment_is_picked_up(
    rig: Rig, terminal, env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys, _ = terminal
    keys.send_text("sk-new\r")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-1")
    rig.say("/keys anthropic")
    assert rig.repl.search_key == "brave-1", rig.repl.search_key


def test_repl_keys_half_set_cloudflare_leaves_only_the_local_painter(
    rig: Rig, terminal, env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys, _ = terminal
    keys.send_text("sk-new\r")
    _with_cloudflare(rig, StubPainter("api"))  # painting with Cloudflare until now
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account-1")  # no token
    rig.say("/keys anthropic")
    assert rig.repl.api is None, "A half-set Cloudflare key cannot paint"
    assert rig.repl.painter is rig.local, "The local painter paints"
    assert "local GPU" in rig.repl._status(), "The status must name what paints"


@pytest.mark.parametrize("typed", ["\r", "\x03", "\x04"])
def test_repl_keys_nothing_typed_changes_nothing(
    rig: Rig, terminal, env_file: Path, typed: str
) -> None:
    keys, _ = terminal
    keys.send_text(typed)
    rig.say("/keys anthropic")
    assert "No key changed" in rig.printed(), rig.printed()
    assert not env_file.exists(), "Nothing may be saved"
    assert "ANTHROPIC_API_KEY" not in os.environ, "Nothing may be set"


def test_repl_keys_menu_shows_each_keys_state_and_picks_one(
    rig: Rig, terminal, env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys, screen = terminal
    monkeypatch.setenv("ANTHROPIC_API_KEY", "set-already")
    keys.send_text(f"{DOWN}\r")  # the menu: cloudflare
    keys.send_text("a\rt\r")  # the two hidden prompts
    rig.say("/keys")
    assert "CLOUDFLARE_API_TOKEN=t" in env_file.read_text(encoding="utf-8")
    assert "not set · " in screen.getvalue(), "Cloudflare is not set"


def test_repl_keys_menu_cancelled_does_nothing(
    rig: Rig, terminal, env_file: Path
) -> None:
    keys, _ = terminal
    keys.send_text("\x03")
    rig.say("/keys")
    assert not env_file.exists(), "Nothing may be saved"
    assert "No key changed" not in rig.printed(), "A closed menu is silent"


def test_repl_painter_follows_the_choice_only_with_a_chain(rig: Rig) -> None:
    rig.repl.paint_with = "api"
    assert rig.repl.painter is rig.local, "No chain, so local paints"
    chain = _with_cloudflare(rig, StubPainter("api"))
    assert rig.repl.painter is chain, "/api uses the chain"
    rig.repl.paint_with = "local"
    assert rig.repl.painter is rig.local, "/local uses the local painter"


def test_repl_wait_shows_a_labelled_spinner_while_the_work_runs(rig: Rig) -> None:
    shown = io.StringIO()
    rig.repl.console = Console(file=shown, force_terminal=True, width=100)

    def slow() -> str:
        time.sleep(0.2)  # long enough for the spinner to turn at least once
        return "done"

    result = rig.repl._wait(slow, "painting")
    assert result == "done", "The work's result must come back"
    assert "painting" in shown.getvalue(), f"No spinner label in {shown.getvalue()!r}"


# --- the status line and the screen ------------------------------------------------


def test_repl_status_shows_model_painter_art_and_window(rig: Rig) -> None:
    status = rig.repl._status()
    assert status == "  /help · haiku-5-5 (high) · local GPU · ink/classic · ○ window"
    rig.host.connected = True
    rig.repl.director.mature = True
    _with_cloudflare(rig, StubPainter("api"))
    rig.repl.style = "fill"
    status = rig.repl._status()
    assert "· mature" in status and "● window" in status, status
    assert "cloudflare · fill/classic" in status, status


def test_repl_status_api_chosen_without_a_chain_shows_the_local_painter(
    rig: Rig,
) -> None:
    rig.repl.paint_with = "api"  # chosen, but there is no usable Cloudflare key
    status = rig.repl._status()
    assert "local GPU" in status, f"The local model paints, but got {status!r}"


def test_repl_status_asks_for_a_second_ctrl_c_after_the_first(rig: Rig) -> None:
    rig.repl.interrupts.press()
    assert "Press Ctrl+C again to exit" in rig.repl._status(), "Hint must show"


def test_repl_draw_screen_clears_only_a_real_terminal(rig: Rig) -> None:
    rig.repl._draw_screen()
    assert ui.CLEAR not in rig.printed(), "A pipe must not be cleared"
    real = Console(file=io.StringIO(), force_terminal=True, width=100)
    rig.repl.console = real
    rig.repl._draw_screen()
    assert ui.CLEAR in cast(io.StringIO, real.file).getvalue(), "Must clear"


def test_repl_redraw_waits_for_the_size_to_settle_then_draws_anew(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    sizes = iter([(100, 30), (90, 30), (80, 24), (80, 24)])
    last = [os.terminal_size((80, 24))]

    def terminal_size(*args: object) -> os.terminal_size:
        last[0] = os.terminal_size(next(sizes, (80, 24)))
        return last[0]

    monkeypatch.setattr(repl.shutil, "get_terminal_size", terminal_size)
    rig.repl.transcript.say(Text("kept line"))
    rig.forget_printed()
    rig.repl._redraw()
    assert rig.repl._drawn_size == (80, 24), f"Drawn at {rig.repl._drawn_size}"
    assert "Welcome to sepia" in rig.printed(), "The welcome box must be redrawn"
    assert "kept line" in rig.printed(), "The transcript must be replayed"


# --- the loop ----------------------------------------------------------------------


def test_repl_run_handles_lines_until_exit_and_says_goodbye(rig: Rig, terminal) -> None:
    keys, _ = terminal
    keys.send_text("a lake\r/exit\r")
    code = rig.repl.run()
    assert code == 0, f"Exit code {code}"
    assert len(rig.local.calls) == 1, "The request must be painted"
    assert f"{ui.PROMPT}a lake" in rig.printed(), "The request must be echoed"
    assert rig.host.sent[-1] == {"type": "bye"}, f"Last message {rig.host.sent[-1]}"
    assert rig.host.closed, "The channel must be closed"
    history = (config.config_dir() / "history").read_text(encoding="utf-8")
    assert "a lake" in history, "The request must reach the prompt history"


def test_repl_run_empty_lines_are_ignored(rig: Rig, terminal) -> None:
    keys, _ = terminal
    keys.send_text("\r/exit\r")
    rig.repl.run()
    assert rig.client.beta.messages.stream.call_count == 0, "Nothing to direct"
    echoed = rig.repl.transcript._said
    assert len(echoed) == 1, f"Only /exit may be echoed, got {echoed}"


def test_repl_run_clear_redraws_the_welcome_box(rig: Rig, terminal) -> None:
    keys, _ = terminal
    keys.send_text("/clear\r/exit\r")
    rig.repl.run()
    assert rig.printed().count("Welcome to sepia") == 2, "Opened, then cleared"


def test_repl_run_ctrl_d_closes_sepia(rig: Rig, terminal) -> None:
    keys, _ = terminal
    keys.send_text("\x04")
    rig.host.connected = True
    assert rig.repl.run() == 0, "Ctrl+D in an empty bar must close sepia"
    assert rig.host.sent[-1] == {"type": "bye"}, "The viewer must be told"


def test_repl_run_ctrl_c_during_a_request_closes_sepia(rig: Rig, terminal) -> None:
    keys, _ = terminal
    keys.send_text("a lake\r")

    def interrupted(*args: object) -> Painting:
        raise KeyboardInterrupt

    rig.local.paint = interrupted  # type: ignore[method-assign]
    assert rig.repl.run() == 0, "Ctrl+C while working must close sepia"
    assert rig.host.closed, "The channel must be closed"


class ScriptedBar:
    """A chat bar that answers from a script: a string is a line, an exception is
    raised. (Resizing a pipe-driven terminal mid-read is timing, not behavior.)"""

    def __init__(
        self,
        script: list[object],
        clock: Clock | None = None,
        on_read: Callable[[], None] = lambda: None,
    ) -> None:
        self.script = script
        self.on_read = on_read
        self.clock = clock
        self.drafts: list[str] = []

    def read(self, draft: str = "") -> str:
        self.drafts.append(draft)
        self.on_read()
        if self.clock is not None:
            self.clock.now += 5.0
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return str(step)

    def still(self, width: int) -> list[str]:
        return []


def _script(
    monkeypatch: pytest.MonkeyPatch,
    script: list[object],
    clock: Clock | None = None,
    on_read: Callable[[], None] = lambda: None,
) -> ScriptedBar:
    bar = ScriptedBar(script, clock, on_read)
    monkeypatch.setattr(repl, "ChatBar", lambda **kwargs: bar)
    return bar


def test_repl_run_resized_while_typing_reads_again_with_the_draft(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    bar = _script(monkeypatch, [Resized("half a thou"), "/exit"])
    assert rig.repl.run() == 0, "The loop must end at /exit"
    assert bar.drafts == ["", "half a thou"], f"Drafts {bar.drafts}"


def test_repl_run_redraws_when_the_window_changed_between_lines(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:

    redrawn: list[bool] = []

    def shrink() -> None:
        if rig.repl._drawn_size != (1, 1) and not redrawn:
            redrawn.append(True)
            rig.repl._drawn_size = os.terminal_size((1, 1))  # drawn at another size

    _script(monkeypatch, [KeyboardInterrupt(), "/exit"], on_read=shrink)
    rig.repl.run()
    assert rig.repl._drawn_size != (1, 1), "The screen must be drawn at the new size"
    assert rig.printed().count("Welcome to sepia") == 2, "Opened, then redrawn"


def test_repl_run_two_quick_ctrl_c_close_sepia_with_a_line_between_handled(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    rig.repl.interrupts = Interrupts(window=2.0, clock=clock)
    _script(monkeypatch, [KeyboardInterrupt(), "/help", KeyboardInterrupt()])
    assert rig.repl.run() == 0, "Two Ctrl+C within the window close sepia"
    assert "/charset" in rig.printed(), "The line between them was handled"


def test_repl_run_ctrl_c_twice_far_apart_does_not_close(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    rig.repl.interrupts = Interrupts(window=2.0, clock=clock)
    bar = _script(monkeypatch, [KeyboardInterrupt()] * 2 + ["/exit"], clock)
    rig.repl.run()
    assert bar.script == [], "Both Ctrl+C presses must have been survived"


# --- starting up -------------------------------------------------------------------


def test_first_run_ctrl_c_at_a_key_prompt_stops(terminal, env_file) -> None:
    keys, _ = terminal
    keys.send_text("\x03")
    done = repl._first_run(Console(file=io.StringIO()), ui.Words())
    assert not done, "Ctrl+C must stop the setup"
    assert not env_file.exists(), "Nothing typed, nothing saved"


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`run_repl` up to the loop: the loop itself is replaced by a recorder, the
    local painter by a stub; the rest (settings, choices, director, ledger, session
    folder) is real."""
    seen: dict[str, Any] = {"local": StubPainter("local")}
    monkeypatch.setattr(repl, "Host", FakeHost)
    monkeypatch.setattr(repl, "load_environment", lambda: None)
    monkeypatch.setattr(repl, "local_model_ready", lambda model: True)

    def build(cloudflare, model_id, local=None):
        seen["cloudflare"] = cloudflare
        chain = FallbackPainter(StubPainter("api"), seen["local"])
        return (chain if cloudflare else None), seen["local"]

    def loop(self: Repl) -> int:
        seen["repl"] = self
        return 7

    monkeypatch.setattr(repl, "build_painter", build)
    monkeypatch.setattr(Repl, "run", loop)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    return seen


def test_run_repl_builds_the_window_from_settings_and_choices(
    started: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEPIA_EFFORT", "low")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "b")
    config.remember(model="claude-opus-5-5", style="fill", painter="local")
    code = repl.run_repl()
    window: Repl = started["repl"]
    assert code == 7, "run_repl returns what the loop returns"
    assert window.director.model == "claude-opus-5-5", "Choices beat the default"
    assert window.director.effort == "low", "SEPIA_EFFORT sets the rest"
    assert window.style == "fill", "The remembered style is used"
    assert window.paint_with == "local", "The remembered painter is used"
    assert started["cloudflare"] == ("a", "t"), "Cloudflare keys reach the painter"
    assert window.search_key == "b", "The search key reaches the window"
    assert window.folder.parent == config.config_dir() / "sessions", window.folder
    assert window.folder.is_dir(), "The session folder must exist"
    assert started["local"].loads == 1, "A downloaded model loads at once"
    assert (config.config_dir() / "usage.json").exists(), "Ledger must be started"


def test_run_repl_with_a_bad_setting_prints_it_and_returns_2(
    started: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("SEPIA_EFFORT", "extreme")
    assert repl.run_repl() == 2, "A bad setting is a usage error"
    assert "SEPIA_EFFORT" in capsys.readouterr().out, "The setting must be named"
    assert "repl" not in started, "The loop must not start"


def test_run_repl_half_set_cloudflare_returns_2(
    started: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    assert repl.run_repl() == 2, "Both Cloudflare values are needed"
    assert "CLOUDFLARE_API_TOKEN" in capsys.readouterr().out


def test_run_repl_without_a_key_asks_and_stops_when_none_is_given(
    started: dict[str, Any], terminal, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys, _ = terminal
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    keys.send_text("\r")
    assert repl.run_repl() == 1, "No key, no sepia"
    assert "repl" not in started, "The loop must not start"
