import pytest
from PIL import Image

from sepia.director import Direction
from sepia.painter import Painting
from sepia.usage import SEARCH_PRICE, Usage


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
