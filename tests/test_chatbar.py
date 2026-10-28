import re

import pytest
from prompt_toolkit.history import InMemoryHistory

from sepia.chatbar import ChatBar
from sepia.ui import PROMPT

COMMANDS = (("/new", "start a fresh picture"), ("/help", "show this list"))


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


def test_chatbar_draws_open_rules_input_and_status_as_one_block(terminal) -> None:
    keys, screen = terminal
    keys.send_text("x\r")
    _bar().read()
    drawn = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|[\r\n]", "", screen.getvalue())
    rule = "─" * 80
    first = drawn.find(rule)
    order = [
        first,
        drawn.find(PROMPT),
        drawn.find(rule, first + len(rule)),
        drawn.find("status"),
    ]
    assert -1 not in order, f"Missing a piece of the bar in {drawn!r}"
    assert order == sorted(order), f"Bar pieces out of order in {drawn!r}"
    corners = [c for c in "╭╮╰╯│" if c in drawn]
    assert not corners, f"The rules must have open ends, found {corners}"


def test_chatbar_still_is_the_empty_bar_row_by_row(terminal) -> None:
    rows = _bar().still(20)
    plain = [re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", row) for row in rows]
    typed_row = f"{PROMPT}describe a picture"[:20]
    expected = ["─" * 20, typed_row, "─" * 20, "status"]
    assert plain == expected, f"Expected {expected}, got {plain}"


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


def test_chatbar_enter_on_a_partial_command_runs_the_suggested_one(terminal) -> None:
    keys, _ = terminal
    keys.send_text("/us\r")
    commands = (("/add <text>", "x"), ("/usage", "y"), ("/help", "z"))
    line = ChatBar(InMemoryHistory(), commands, "describe", lambda: "status").read()
    assert line == "/usage", f"Expected the first suggestion, got {line!r}"


def test_chatbar_enter_on_a_full_command_keeps_it(terminal) -> None:
    keys, _ = terminal
    keys.send_text("/help\r")
    line = ChatBar(InMemoryHistory(), (("/help", "z"),), "d", lambda: "s").read()
    assert line == "/help", f"Got {line!r}"
