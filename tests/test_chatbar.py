import io
import re
from collections.abc import Iterator

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.input.base import PipeInput
from prompt_toolkit.output.vt100 import Vt100_Output

from sepia.chatbar import ChatBar
from sepia.ui import PROMPT

COMMANDS = (("/new", "start a fresh picture"), ("/help", "show this list"))


@pytest.fixture
def terminal() -> Iterator[tuple[PipeInput, io.StringIO]]:
    """A fake 80x24 terminal: keystrokes go in through the pipe, drawing comes out."""
    screen = io.StringIO()
    with create_pipe_input() as keys:
        output = Vt100_Output(screen, lambda: Size(rows=24, columns=80), term="xterm")
        with create_app_session(input=keys, output=output):
            yield keys, screen


def _bar() -> ChatBar:
    return ChatBar(InMemoryHistory(), COMMANDS, "describe a picture", lambda: "status")


def test_chatbar_read_returns_the_submitted_line(terminal) -> None:
    keys, _ = terminal
    keys.send_text("waterfall\r")
    line = _bar().read()
    assert line == "waterfall", f"Expected 'waterfall', got {line!r}"


def test_chatbar_read_ctrl_c_raises_keyboard_interrupt(terminal) -> None:
    keys, _ = terminal
    keys.send_text("half typed\x03")
    with pytest.raises(KeyboardInterrupt):
        _bar().read()


def test_chatbar_read_ctrl_d_on_empty_bar_raises_eof(terminal) -> None:
    keys, _ = terminal
    keys.send_text("\x04")
    with pytest.raises(EOFError):
        _bar().read()


def test_chatbar_draws_frame_input_and_status_as_one_block(terminal) -> None:
    keys, screen = terminal
    keys.send_text("x\r")
    _bar().read()
    drawn = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|[\r\n]", "", screen.getvalue())
    pieces = ["╭", "╮", "│", PROMPT, "describe a picture", "│", "╰", "╯", "status"]
    positions = [drawn.find(piece) for piece in pieces]
    assert -1 not in positions, f"Missing a piece of the bar in {drawn!r}"
    order = [
        drawn.index("╭"),
        drawn.index(PROMPT),
        drawn.index("╰"),
        drawn.index("status"),
    ]
    assert order == sorted(order), f"Bar pieces out of order in {drawn!r}"


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("/c", "lear"), ("/he", "lp"), ("/help", None), ("hello", None), ("/new x", None)],
)
def test_command_suggest_completes_slash_commands_inline(
    typed: str, expected: str | None
) -> None:
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.document import Document

    from sepia.chatbar import CommandSuggest

    suggest = CommandSuggest(["/new", "/clear", "/help"])
    suggestion = suggest.get_suggestion(Buffer(), Document(typed))
    got = suggestion.text if suggestion else None
    assert got == expected, f"{typed!r}: expected {expected!r}, got {got!r}"


def test_chatbar_tab_accepts_the_command_suggestion(terminal) -> None:
    keys, _ = terminal
    keys.send_text("/cl\t\r")
    line = ChatBar(
        InMemoryHistory(), (("/clear", "x"),), "describe", lambda: "status"
    ).read()
    assert line == "/clear", f"Expected '/clear', got {line!r}"
