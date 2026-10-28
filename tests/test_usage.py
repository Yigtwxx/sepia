from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from sepia.director import Direction
from sepia.painter import Painting
from sepia.usage import (
    EARLIER_TOKENS,
    SEARCH_PRICE,
    Earlier,
    Ledger,
    Usage,
    estimate_earlier,
)


def _direction(model: str = "claude-haiku-5-5", searches: int = 1) -> Direction:
    return Direction(
        message="m",
        prompt="p",
        edit=False,
        references=(),
        model=model,
        searches=searches,
        input_tokens=1_000_000,
        output_tokens=100_000,
    )


def _painting(source: str = "api", seconds: float = 2.5) -> Painting:
    return Painting(Image.new("RGB", (2, 2)), source, seconds)  # type: ignore[arg-type]


def test_usage_add_direction_sums_tokens_searches_and_list_price() -> None:
    usage = Usage()
    usage.add_direction(_direction())
    usage.add_direction(_direction(searches=0))
    got = (usage.requests, usage.input_tokens, usage.output_tokens, usage.searches)
    assert got == (2, 2_000_000, 200_000, 1), f"Got {got}"
    expected = 2 * (0.10 + 0.05) + SEARCH_PRICE
    assert usage.cost == pytest.approx(expected), f"Got {usage.cost}"
    assert usage.unpriced == 0, "Every model here has a list price"


def test_usage_unknown_model_is_counted_but_not_priced() -> None:
    usage = Usage()
    usage.add_direction(_direction(model="claude-future-9", searches=0))
    assert usage.requests == 1, "The request still counts"
    assert (usage.cost, usage.unpriced) == (0.0, 1), f"Got {usage.cost, usage.unpriced}"


def test_usage_add_painting_counts_sources_time_and_references() -> None:
    usage = Usage()
    usage.add_painting(_painting("api"), referenced=True)
    usage.add_painting(_painting("api"), referenced=False)
    usage.add_painting(_painting("local", 4.0), referenced=True)
    assert usage.pictures == {"api": 2, "local": 1}, f"Got {usage.pictures}"
    assert usage.paint_seconds == pytest.approx(9.0), f"Got {usage.paint_seconds}"
    assert usage.referenced == 2, f"Got {usage.referenced}"


def test_usage_unknown_model_still_prices_its_searches() -> None:
    usage = Usage()
    usage.add_direction(_direction(model="claude-future-9", searches=2))
    expected = 2 * SEARCH_PRICE
    assert usage.cost == pytest.approx(expected), f"Got {usage.cost}"


HISTORY = """
# 2026-10-29 01:00:18.894859
+waterfall

# 2026-10-29 01:01:00.000000
+/clear

# 2026-10-29 01:02:00.000000
+/add mountains

# 2026-10-29 01:03:00.000000
+/add

# 2026-10-29 01:04:00.000000
+/usage

# 2026-10-29 02:00:00.000000
+city

# 2026-10-29 02:01:00.000000
+two
+lines
"""


def _sepia_dir(tmp_path: Path) -> tuple[Path, Path]:
    """A history of four requests, and one kept session folder from 01:50 holding
    two pictures; the requests before it belong to pruned sessions."""
    history = tmp_path / "history"
    history.write_text(HISTORY, encoding="utf-8")
    sessions = tmp_path / "sessions"
    kept = sessions / "20261029-015000-000000"
    kept.mkdir(parents=True)
    for name in ("01.png", "02.png", "viewer.json"):
        (kept / name).write_bytes(b"")
    (sessions / "not-a-session").mkdir()
    return history, sessions


def test_estimate_earlier_counts_requests_but_not_commands(tmp_path: Path) -> None:
    history, sessions = _sepia_dir(tmp_path)
    earlier = estimate_earlier(history, sessions, "claude-haiku-5-5")
    assert earlier.requests == 4, f"Expected 4 requests, got {earlier.requests}"


def test_estimate_earlier_adds_pruned_requests_to_saved_pictures(
    tmp_path: Path,
) -> None:
    history, sessions = _sepia_dir(tmp_path)
    earlier = estimate_earlier(history, sessions, "claude-haiku-5-5")
    assert earlier.pictures == 4, f"Expected 2 saved + 2 pruned, got {earlier}"


def test_estimate_earlier_prices_typical_tokens_per_request(tmp_path: Path) -> None:
    history, sessions = _sepia_dir(tmp_path)
    earlier = estimate_earlier(history, sessions, "claude-haiku-5-5")
    tokens_in, tokens_out = EARLIER_TOKENS
    expected = 4 * (tokens_in * 0.10 + tokens_out * 0.50) / 1_000_000
    assert earlier.cost == pytest.approx(expected), f"Got {earlier.cost}"


def test_estimate_earlier_without_files_is_zero(tmp_path: Path) -> None:
    earlier = estimate_earlier(tmp_path / "none", tmp_path / "none", "m")
    assert earlier == Earlier(), f"Expected nothing, got {earlier}"


def test_ledger_first_read_estimates_earlier_use_once(tmp_path: Path) -> None:
    estimate = MagicMock(return_value=Earlier(requests=5, pictures=3, cost=0.5))
    path = tmp_path / "usage.json"
    Ledger(path, estimate).read()
    again = Ledger(path, estimate).read()
    assert estimate.call_count == 1, f"Estimated {estimate.call_count} times"
    assert again.earlier.requests == 5, f"Estimate not kept: {again.earlier}"


def test_ledger_add_keeps_totals_across_windows(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    first, second = Ledger(path, Earlier), Ledger(path, Earlier)
    first.add(lambda usage: usage.add_direction(_direction(searches=0)))
    second.add(lambda usage: usage.add_painting(_painting("local"), referenced=True))
    total = Ledger(path, Earlier).read().total
    got = (total.requests, total.pictures, total.referenced)
    assert got == (1, {"local": 1}, 1), f"Got {got}"


def test_ledger_corrupt_file_starts_over_without_estimate(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    path.write_text("{not json", encoding="utf-8")
    estimate = MagicMock(return_value=Earlier(requests=5))
    record = Ledger(path, estimate).read()
    assert record.total == Usage(), f"Expected fresh totals, got {record.total}"
    assert estimate.call_count == 0, "History now holds tracked requests too"
