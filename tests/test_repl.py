import io
import os
import time
from pathlib import Path

import pytest
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sepia.repl import (
    Command,
    Interrupts,
    Transcript,
    named_option,
    new_session_dir,
    parse_command,
)


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
