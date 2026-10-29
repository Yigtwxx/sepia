import re

import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.formatted_text import fragment_list_to_text
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import default_ui_style, merge_styles

from sepia import ui
from sepia.chatbar import STYLE, BottomBar, ChatBar, CommandMenu, Resized
from sepia.ui import POINTER, PROMPT

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


def test_chatbar_read_draft_is_kept_in_the_bar(terminal) -> None:
    keys, _ = terminal
    keys.send_text("fall\r")
    line = _bar().read(draft="water")
    assert line == "waterfall", f"Typing must continue the draft, got {line!r}"


def test_chatbar_read_window_resize_raises_resized_with_the_draft(
    resizable_terminal,
) -> None:
    keys, sizes = resizable_terminal
    keys.send_text("half typed")

    def status() -> str:
        sizes[0] = Size(rows=30, columns=60)  # the window changes after the first draw
        return "status"

    bar = ChatBar(InMemoryHistory(), COMMANDS, "describe a picture", status)
    with pytest.raises(Resized) as raised:
        bar.read()
    assert raised.value.draft == "half typed", f"Got {raised.value.draft!r}"


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


MENU = (
    ("/clear", "start over"),
    ("/charset [classic|symbols]", "choose the characters"),
    ("/help", "show this list"),
)


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("/c", ["/clear", "/charset"]),
        ("/", ["/clear", "/charset", "/help"]),
        ("/help", ["/help"]),
        ("hello", []),
        ("/charset x", []),
    ],
)
def test_command_menu_matches_commands_starting_with_the_text(
    typed: str, expected: list[str]
) -> None:
    names = [name for name, _ in CommandMenu(MENU).matches(typed)]
    assert names == expected, f"{typed!r}: expected {expected}, got {names}"


def test_command_menu_move_wraps_around_the_matches() -> None:
    menu = CommandMenu(MENU)
    menu.move("/c", -1)
    assert menu.choice("/c") == "/charset", f"Up from the first: {menu.choice('/c')}"
    menu.move("/c", 1)
    assert menu.choice("/c") == "/clear", f"Down from the last: {menu.choice('/c')}"


def test_command_menu_lines_sit_on_the_bottom_rows_with_the_pointer() -> None:
    menu = CommandMenu(MENU)
    menu.chosen = 1
    text = fragment_list_to_text(menu.lines("/c", 3))
    rows = text.split("\n")
    assert rows[0] == "", f"Fewer matches than rows leave the top blank: {rows}"
    assert rows[2].startswith(f" {POINTER} /charset"), f"Pointer misplaced: {rows}"
    assert "start over" in rows[1] and POINTER not in rows[1], f"Got {rows}"


def test_command_menu_lines_have_no_background_and_a_purple_choice() -> None:
    # The app's style sits on prompt_toolkit's own, where "menu" is grey.
    style = merge_styles([default_ui_style(), STYLE])
    backgrounds = {
        text.strip(): style.get_attrs_for_style_str(fragment_style).bgcolor
        for fragment_style, text, *_ in CommandMenu(MENU).lines("/", 3)
        if text.strip()
    }
    painted = {text: color for text, color in backgrounds.items() if color}
    assert not painted, f"Menu text drawn on a background: {painted}"
    chosen = style.get_attrs_for_style_str("class:commands.chosen").color
    assert chosen == ui.ACCENT.lstrip("#"), f"Highlight is {chosen}, not the accent"


def test_command_menu_lines_scroll_to_keep_the_choice_in_view() -> None:
    menu = CommandMenu(MENU)
    menu.chosen = 2
    rows = fragment_list_to_text(menu.lines("/", 2)).split("\n")
    assert "/charset" in rows[0], f"Expected the row before the choice: {rows}"
    assert rows[1].startswith(f" {POINTER} /help"), f"/help must be in view: {rows}"


def test_bottom_bar_make_room_lifts_the_transcript_and_moves_the_bar_up() -> None:
    written: list[str] = []
    bar = BottomBar(written.append, lambda: 24)
    granted = bar.make_room(3)
    expected = [
        "\x1b8\n\n\n\x1b[3A\x1b7",  # transcript end: feed three lines, save it again
        "\x1b[1;17r\x1b[18;1H\x1b[J\x1b[18;1H",  # smaller region, bar from row 18
    ]
    assert granted == 3, f"Expected 3 rows, got {granted}"
    assert written == expected, f"Got {written}"


def test_bottom_bar_make_room_zero_gives_the_rows_back() -> None:
    written: list[str] = []
    bar = BottomBar(written.append, lambda: 24)
    bar.make_room(3)
    written.clear()
    bar.make_room(0)
    assert written == ["\x1b[1;20r\x1b[18;1H\x1b[J\x1b[21;1H"], f"Got {written}"


def test_bottom_bar_make_room_leaves_the_transcript_one_row() -> None:
    bar = BottomBar(lambda _: None, lambda: 10)
    granted = bar.make_room(50)
    assert granted == 5, f"10 rows - 4 for the bar - 1 kept: expected 5, got {granted}"


def test_chatbar_menu_asks_for_rows_as_matches_change_and_gives_them_back(
    terminal,
) -> None:
    keys, _ = terminal
    keys.send_text("/c\r")
    asked: list[int] = []

    def make_room(rows: int) -> int:
        asked.append(rows)
        return rows

    bar = ChatBar(InMemoryHistory(), MENU, "describe", lambda: "status", make_room)
    line = bar.read()
    assert line == "/clear", f"Enter runs the highlighted match, got {line!r}"
    assert asked == [3, 2, 0], f"Expected rows for '/', then '/c', then none: {asked}"


def test_chatbar_down_then_enter_runs_the_next_match(terminal) -> None:
    keys, _ = terminal
    keys.send_text("/c\x1b[B\r")
    line = ChatBar(InMemoryHistory(), MENU, "describe", lambda: "status").read()
    assert line == "/charset", f"Expected the second match, got {line!r}"


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
