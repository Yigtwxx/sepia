"""What this session used: Claude's tokens and searches, and the pictures painted."""

from dataclasses import dataclass, field

from sepia.director import Direction
from sepia.painter import Painting

PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-fable-5-1": (10.00, 50.00),
}
"""Anthropic's list prices in dollars per million input and output tokens (October
2026). Haiku 5.5 costs more above 100K-token prompts, which sepia never sends."""
SEARCH_PRICE = 0.01
"""Dollars per web search."""


@dataclass
class Usage:
    """Running totals for the session; /clear starts a new picture, not a new tally."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    search_cost: float = 0.0
    unpriced: int = 0
    """Requests served by a model without a known price, left out of `cost`."""
    pictures: dict[str, int] = field(default_factory=dict)
    """Pictures painted per source: "api", "keyless" or "local"."""
    paint_seconds: float = 0.0
    referenced: int = 0
    """Pictures painted after a reference picture."""

    @property
    def cost(self) -> float:
        """Estimated dollars, from list prices."""
        return self.input_cost + self.output_cost + self.search_cost

    def add_direction(self, direction: Direction) -> None:
        self.requests += 1
        self.input_tokens += direction.input_tokens
        self.output_tokens += direction.output_tokens
        self.searches += direction.searches
        price = PRICES.get(direction.model)
        if price is None:
            self.unpriced += 1
            return
        per_input, per_output = price
        self.input_cost += direction.input_tokens * per_input / 1_000_000
        self.output_cost += direction.output_tokens * per_output / 1_000_000
        self.search_cost += direction.searches * SEARCH_PRICE

    def add_painting(self, painting: Painting, referenced: bool) -> None:
        self.pictures[painting.source] = self.pictures.get(painting.source, 0) + 1
        self.paint_seconds += painting.seconds
        self.referenced += referenced
