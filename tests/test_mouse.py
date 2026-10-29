import sys
import types

import pytest

from sepia import mouse
from sepia.mouse import MOUSE_OFF, MOUSE_ON, MouseParser


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        (["\x1b[<35;10;5M"], (9, 4)),
        (["\x1b[<35;1;1M\x1b[<35;20;8M"], (19, 7)),
        (["\x1b[<35;3", ";4M"], (2, 3)),
        (["hello"], None),
    ],
)
def test_mouse_parser_reports_the_latest_cell(chunks, expected) -> None:
    parser = MouseParser()
    results = [parser.feed(chunk) for chunk in chunks]
    assert results[-1] == expected, f"{chunks!r}: expected {expected}, got {results}"


def test_mouse_parser_release_report_counts_as_a_position() -> None:
    assert MouseParser().feed("\x1b[<0;4;6m") == (3, 5), "A button release has a cell"


def test_mouse_parser_report_split_in_three_is_completed() -> None:
    parser = MouseParser()
    results = [parser.feed(part) for part in ("\x1b[<3", "5;12", ";9M")]
    assert results == [None, None, (11, 8)], f"Got {results}"


def test_mouse_parser_keeps_a_trailing_partial_report_after_a_whole_one() -> None:
    parser = MouseParser()
    assert parser.feed("\x1b[<35;2;2M\x1b[<35;7") == (1, 1), "Whole report lost"
    assert parser.feed(";9M") == (6, 8), "The split report was not completed"


def test_mouse_parser_ignores_typed_keys_around_reports() -> None:
    parser = MouseParser()
    assert parser.feed("ab\x1b[<35;5;5Mcd") == (4, 4), "Keys must not hide the report"
    assert parser.feed("cd") is None, "Keys alone must report nothing"


def test_mouse_parser_report_is_not_reported_twice() -> None:
    parser = MouseParser()
    parser.feed("\x1b[<35;5;5M")
    assert parser.feed("") is None, "A handled report must not come back"


def test_mouse_parser_unfinished_escape_that_never_completes_is_dropped() -> None:
    parser = MouseParser()
    assert parser.feed("\x1b[<" + "1" * 100) is None, "No report yet"
    # The runaway tail was cut, so its start is gone and ';5;5M' completes nothing.
    assert parser.feed(";5;5M") is None, "A noisy tail must not form a report"
    assert parser.feed("\x1b[<35;3;3M") == (2, 2), "The parser must recover"


def test_mouse_parser_escape_that_is_not_a_report_is_discarded() -> None:
    parser = MouseParser()
    parser.feed("\x1b[A")  # an arrow key
    assert parser.feed("<35;5;5M") is None, "Arrow key bytes joined a later report"


def test_mouse_modes_are_switched_on_and_off_in_reverse_order() -> None:
    assert MOUSE_ON == "\x1b[?1003h\x1b[?1006h", f"Got {MOUSE_ON!r}"
    assert MOUSE_OFF == "\x1b[?1006l\x1b[?1003l", f"Got {MOUSE_OFF!r}"


class _FakeMsvcrt(types.ModuleType):
    """A console buffer: `kbhit` is true while keys remain."""

    def __init__(self, typed: str) -> None:
        super().__init__("msvcrt")
        self.keys = list(typed)

    def kbhit(self) -> bool:
        return bool(self.keys)

    def getwch(self) -> str:
        return self.keys.pop(0)


@pytest.mark.skipif(sys.platform != "win32", reason="reads the Windows console")
def test_read_input_returns_everything_buffered_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = _FakeMsvcrt("\x1b[<35;10;5M")
    monkeypatch.setitem(sys.modules, "msvcrt", console)
    assert mouse.read_input() == "\x1b[<35;10;5M", "Buffered keys were not returned"
    assert console.keys == [], "The buffer must be drained"


@pytest.mark.skipif(sys.platform != "win32", reason="reads the Windows console")
def test_read_input_empty_console_returns_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "msvcrt", _FakeMsvcrt(""))
    assert mouse.read_input() == "", "Nothing typed must give an empty string"
