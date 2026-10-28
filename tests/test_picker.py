import re

import pytest

from sepia.picker import choose
from sepia.ui import POINTER

OPTIONS = (("ink", "colored symbols"), ("fill", "painted cells"), ("both", "x"))
DOWN, UP = "\x1b[B", "\x1b[A"


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


def test_choose_draws_title_options_summaries_and_hint(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text("\r")
    _choose()
    drawn = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|[\r\n]", "", screen.getvalue())
    pieces = ["Picture style", f"{POINTER} 2. fill", "painted cells", "Enter to choose"]
    missing = [piece for piece in pieces if piece not in drawn]
    assert not missing, f"{missing} missing from {drawn!r}"
