import re

import pytest

from sepia.picker import choose, show, toggles
from sepia.ui import POINTER

OPTIONS = (("ink", "colored symbols"), ("fill", "painted cells"), ("both", "x"))
ROWS = (
    ("ask", "Clarifying questions", "ask before painting", True),
    ("mature", "Mature pictures", "sexy and dark", False),
)
DOWN, UP = "\x1b[B", "\x1b[A"


def _toggles() -> dict[str, bool]:
    return toggles("Settings", ROWS, "Esc to close")


def _choose(current: str = "fill") -> str | None:
    return choose("Picture style", OPTIONS, current, "Enter to choose")


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("\r", "fill"),
        (f"{DOWN}\r", "both"),
        (f"{DOWN}{DOWN}\r", "ink"),
        (f"{UP}\r", "ink"),
        ("3", "both"),
    ],
)
def test_choose_moves_from_the_current_option_and_picks(
    terminal, keys: str, expected: str
) -> None:
    pipe, _ = terminal
    pipe.send_text(keys)
    picked = _choose()
    assert picked == expected, f"{keys!r}: expected {expected}, got {picked}"


def test_choose_ctrl_c_cancels(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text(f"{DOWN}\x03")
    assert _choose() is None, "Ctrl+C must leave the setting as it was"


@pytest.mark.parametrize("key", ["\x1b", "\r", "q", "\x03"])
def test_show_closes_on_esc_enter_q_or_ctrl_c(terminal, key: str) -> None:
    pipe, _ = terminal
    pipe.send_text(key)
    show("\x1b[1m Usage\x1b[0m", "Esc to close")  # returns only once closed


def test_show_draws_the_panel_and_hint_then_erases_it(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text("\x1b")
    show("\x1b[1m Usage\x1b[0m · this session\n Claude", "Esc to close")
    drawn = screen.getvalue()
    plain = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|[\r\n]", "", drawn)
    missing = [
        p for p in ("Usage", "this session", "Claude", "Esc to close") if p not in plain
    ]
    assert not missing, f"{missing} missing from {plain!r}"
    assert drawn.rstrip().endswith("\x1b[J") or "\x1b[J" in drawn[-40:], (
        f"The panel must erase itself when closed, got tail {drawn[-40:]!r}"
    )


def test_choose_draws_title_options_summaries_and_hint(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text("\r")
    _choose()
    drawn = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|[\r\n]", "", screen.getvalue())
    pieces = ["Picture style", f"{POINTER} 2. fill", "painted cells", "Enter to choose"]
    missing = [piece for piece in pieces if piece not in drawn]
    assert not missing, f"{missing} missing from {drawn!r}"


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("\x1b", {"ask": True, "mature": False}),
        ("\r\x1b", {"ask": False, "mature": False}),
        (f"{DOWN} \x1b", {"ask": True, "mature": True}),
        ("2\x1b", {"ask": True, "mature": True}),
        (f"\r\r{UP}{UP} q", {"ask": False, "mature": False}),
        (f"{UP}\r\x03", {"ask": True, "mature": True}),
    ],
)
def test_toggles_flips_values_and_returns_them_when_closed(
    terminal, keys: str, expected: dict[str, bool]
) -> None:
    pipe, _ = terminal
    pipe.send_text(keys)
    values = _toggles()
    assert values == expected, f"{keys!r}: expected {expected}, got {values}"


def test_toggles_draws_labels_values_summaries_and_hint(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text("\x1b")
    _toggles()
    drawn = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|[\r\n]", "", screen.getvalue())
    pieces = [
        "Settings",
        f"{POINTER} Clarifying questions   on   ask before painting",
        "Mature pictures        off  sexy and dark",
        "Esc to close",
    ]
    missing = [piece for piece in pieces if piece not in drawn]
    assert not missing, f"{missing} missing from {drawn!r}"
