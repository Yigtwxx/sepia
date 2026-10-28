import os
import time
from pathlib import Path

import pytest

from sepia.repl import Command, new_session_dir, parse_command, toggle


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
    ("current", "requested", "expected"),
    [
        ("ink", "fill", "fill"),
        ("ink", "", "fill"),
        ("fill", "", "ink"),
        ("ink", "x", "fill"),
    ],
)
def test_toggle_picks_requested_or_next_option(
    current: str, requested: str, expected: str
) -> None:
    result = toggle(current, ("ink", "fill"), requested)
    assert result == expected, f"Expected {expected}, got {result}"


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
