import io
import re

import pytest

from sepia import ui
from sepia.director import Answer, Option, Question
from sepia.questions import Asked, ask

COLUMNS = 80
ESCAPE = re.compile(r"\[([0-9;?]*)([A-Za-z])")
DOWN, LEFT, RIGHT = "\x1b[B", "\x1b[D", "\x1b[C"
SUBJECT = Question(
    "Subject",
    "What should it show?",
    False,
    (
        Option("A galaxy", "spiral arms"),
        Option("A black hole", "a bright disk"),
        Option("A nebula", "colored gas"),
    ),
)
MOOD = Question(
    "Mood",
    "Which moods fit?",
    True,
    (
        Option("Calm", "still"),
        Option("Dramatic", "strong contrast"),
        Option("Mysterious", "hidden shapes"),
    ),
)


def _ask(*questions: Question) -> Asked:
    return ask(questions, ui.Words())


def _answer(question: Question, *choices: str) -> Answer:
    return Answer(question.header, question.text, choices)


def _rows(screen: io.StringIO) -> list[str]:
    """The rows of text on the fake terminal after the run. prompt_toolkit redraws
    only the cells that changed, so the raw output is replayed onto a grid; erasing
    is ignored, which keeps what was last drawn for the asserts to find."""
    grid: dict[tuple[int, int], str] = {}
    row = col = 0
    raw = screen.getvalue()
    index = 0
    while index < len(raw):
        char = raw[index]
        index += 1
        if char == "\x1b":
            match = ESCAPE.match(raw, index)
            if match is None:
                continue
            index = match.end()
            number = int(match.group(1) or 1) if match.group(1).isdigit() else 1
            move = match.group(2)
            if move == "A":
                row -= number
            elif move == "B":
                row += number
            elif move == "C":
                col += number
            elif move == "D":
                col -= number
        elif char == "\r":
            col = 0
        elif char == "\n":
            row += 1
        elif char == "\x08":
            col -= 1
        else:
            grid[(row, col)] = char
            col += 1
    lines = []
    for number in sorted({at[0] for at in grid}):
        width = max(at[1] for at in grid if at[0] == number)
        lines.append("".join(grid.get((number, at), " ") for at in range(width + 1)))
    return lines


def _drawn(screen: io.StringIO) -> str:
    """All the rows drawn, joined by newlines."""
    return "\n".join(_rows(screen))


@pytest.mark.parametrize(
    ("keys", "choice"),
    [("\r", "A galaxy"), (f"{DOWN}\r", "A black hole"), ("3", "A nebula")],
)
def test_ask_single_question_picks_and_finishes(
    terminal, keys: str, choice: str
) -> None:
    pipe, _ = terminal
    pipe.send_text(keys)
    asked = _ask(SUBJECT)
    expected = Asked((_answer(SUBJECT, choice),))
    assert asked == expected, f"{keys!r}: got {asked}"


def test_ask_several_choices_toggle_with_space_and_finish_with_enter(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text(f" {DOWN}{DOWN} \r")
    asked = _ask(MOOD)
    expected = Asked((_answer(MOOD, "Calm", "Mysterious"),))
    assert asked == expected, f"Got {asked}"


def test_ask_several_choices_toggled_off_leave_the_question_unanswered(
    terminal,
) -> None:
    pipe, _ = terminal
    pipe.send_text("11\r")
    assert _ask(MOOD) == Asked(), "Nothing chosen is the same as skipping"


def test_ask_other_row_takes_typed_words_as_the_answer(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text("4a dying star 2\x7f\r")
    asked = _ask(SUBJECT)
    expected = Asked((_answer(SUBJECT, "a dying star"),))
    assert asked == expected, f"Got {asked}"


def test_ask_other_row_empty_does_not_pick(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text("4\r\x1b")
    assert _ask(SUBJECT) == Asked(), "Enter on an empty Other row must not pick"


def test_ask_several_choices_keep_typed_words_beside_the_options(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text(" 4neon\r")
    asked = _ask(MOOD)
    expected = Asked((_answer(MOOD, "Calm", "neon"),))
    assert asked == expected, f"Got {asked}"


def test_ask_escape_skips_with_no_answers(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text(f"{DOWN}\x1b")
    assert _ask(SUBJECT, MOOD) == Asked(), "Esc must paint the guess"


def test_ask_ctrl_c_cancels(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text("\x03")
    assert _ask(SUBJECT, MOOD) == Asked(cancelled=True), "Ctrl+C must cancel"


def test_ask_several_questions_go_on_to_the_paint_page(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text("2 \r\r")  # black hole → Mood, Calm, next → Paint, paint
    asked = _ask(SUBJECT, MOOD)
    expected = Asked((_answer(SUBJECT, "A black hole"), _answer(MOOD, "Calm")))
    assert asked == expected, f"Got {asked}"


def test_ask_switching_back_changes_an_answer(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text(f"1{LEFT}2{RIGHT}\r")  # galaxy, back, black hole, → Paint, paint
    asked = _ask(SUBJECT, MOOD)
    expected = Asked((_answer(SUBJECT, "A black hole"),))
    assert asked == expected, f"Only the changed answer must be sent, got {asked}"


def test_ask_paint_with_nothing_answered_skips(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text(f"{RIGHT}{RIGHT}\r")
    assert _ask(SUBJECT, MOOD) == Asked(), "Painting with no answers is a skip"


def test_ask_draws_tabs_options_other_and_hint(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text("\x1b")
    _ask(SUBJECT, MOOD)
    drawn = _drawn(screen)
    pieces = [
        "☐ Subject",
        "☐ Mood",
        f"{ui.CHECK} Paint",
        "What should it show?",
        f"{ui.POINTER} 1. A galaxy      spiral arms",
        "Other…",
        "↑↓ to move · Enter to pick · ←→ to switch · Esc to paint my guess",
    ]
    missing = [piece for piece in pieces if piece not in drawn]
    assert not missing, f"{missing} missing from {drawn!r}"


def test_ask_draws_boxes_for_several_choices(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text(" \x1b")
    _ask(MOOD)
    drawn = _drawn(screen)
    pieces = [
        "Which moods fit? Pick any.",
        f"[{ui.CHECK}] Calm",
        "[ ] Dramatic",
        "Space to toggle · Enter to paint · Esc to paint my guess",
    ]
    missing = [piece for piece in pieces if piece not in drawn]
    assert not missing, f"{missing} missing from {drawn!r}"


def test_ask_draws_the_paint_page_with_unanswered_dashes(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text(f"2{RIGHT}\x1b")
    _ask(SUBJECT, MOOD)
    drawn = _drawn(screen)
    pieces = ["Ready to paint", "Subject  A black hole", "Mood     —"]
    missing = [piece for piece in pieces if piece not in drawn]
    assert not missing, f"{missing} missing from {drawn!r}"


def test_ask_cuts_long_lines_to_the_terminal_width(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text("\x1b")
    long = Question(
        "Size", "How big?", False, (Option("Huge", "x" * 200), Option("Tiny", "y"))
    )
    _ask(long)
    rows = [row for row in _rows(screen) if "1. Huge" in row]
    assert rows, f"The long option's row is missing from {_drawn(screen)!r}"
    row = rows[0].rstrip()
    assert row.endswith("x…"), f"A cut row must end in an ellipsis: {row!r}"
    assert len(row) <= COLUMNS - 1, f"Row is {len(row)} columns wide: {row!r}"


def test_ask_other_row_keeps_the_end_of_a_long_answer_in_view(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text("4" + "a" * 117 + "END\x1b")
    _ask(SUBJECT)
    rows = [row for row in _rows(screen) if "4. Other: " in row]
    assert rows, f"The Other row is missing from {_drawn(screen)!r}"
    row = rows[0].rstrip()
    prefix = f" {ui.POINTER} 4. Other: …"
    assert row.startswith(prefix), f"Prefix and left ellipsis expected: {row!r}"
    assert row.endswith(f"END{ui.BLOCK}"), f"Cursor must stay in view: {row!r}"
    assert len(row) <= COLUMNS - 1, f"Row is {len(row)} columns wide: {row!r}"


def test_ask_other_row_keeps_the_box_and_cursor_for_several_choices(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text("4" + "a" * 117 + "END\x1b")
    _ask(MOOD)
    rows = [row for row in _rows(screen) if "4. [" in row]
    assert rows, f"The Other row is missing from {_drawn(screen)!r}"
    row = rows[0].rstrip()
    assert row.startswith(f" {ui.POINTER} 4. [{ui.CHECK}] Other: …"), f"Got {row!r}"
    assert row.endswith(f"END{ui.BLOCK}"), f"Cursor must stay in view: {row!r}"
    assert len(row) <= COLUMNS - 1, f"Row is {len(row)} columns wide: {row!r}"


def test_ask_superscript_digit_is_not_a_shortcut(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text("\u00b2\r")
    asked = _ask(SUBJECT)
    expected = Asked((_answer(SUBJECT, "A galaxy"),))
    assert asked == expected, f"A superscript must be ignored, got {asked}"


def test_ask_pasted_text_goes_into_the_other_row_as_one_line(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text("4\x1b[200~a dying\nstar	now\x1b[201~\r")
    asked = _ask(SUBJECT)
    expected = Asked((_answer(SUBJECT, "a dying star now"),))
    assert asked == expected, f"Got {asked}"


def test_ask_paste_outside_the_other_row_is_ignored(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text("\x1b[200~junk\x1b[201~\r")
    asked = _ask(SUBJECT)
    expected = Asked((_answer(SUBJECT, "A galaxy"),))
    assert asked == expected, f"Got {asked}"
