"""What sepia used: Claude's tokens and searches, and the pictures painted.

`Usage` holds running totals. `Ledger` keeps the all-time totals in a JSON file that
every sepia window adds to, with an estimate of what was used before it existed.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from sepia.director import Direction
from sepia.painter import Painting

PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-fable-5-1": (10.00, 50.00),
    "claude-fable-5": (10.00, 50.00),
}
"""Anthropic's list prices in dollars per million input and output tokens (October
2026), including the models a server-side fallback can answer with. Haiku 5.5 costs
more above 100K-token prompts, which sepia never sends."""
SEARCH_PRICE = 0.01
"""Dollars per web search, whatever the model."""
EARLIER_TOKENS = (6_600, 700)
"""Input and output tokens of a typical request before tracking began: the system
prompt, the search tool and the request in, thinking and the reply out (measured on
Haiku 5.5 at low effort, without a search)."""
SESSION_FORMAT = "%Y%m%d-%H%M%S-%f"
"""Session folder names, as `repl.new_session_dir` makes them."""


@dataclass
class Usage:
    """Running totals; /clear starts a new picture, not a new tally."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    search_cost: float = 0.0
    unpriced: int = 0
    """Requests served by a model without a known price; their tokens are left out
    of `cost`."""
    pictures: dict[str, int] = field(default_factory=dict)
    """Pictures painted per source: "api", "keyless" or "local"."""
    paint_seconds: float = 0.0
    referenced: int = 0
    """Pictures painted after a reference picture."""
    image_searches: int = 0
    """Brave image searches for named subjects; Brave bills its own account."""

    @property
    def cost(self) -> float:
        """Estimated dollars, from list prices."""
        return self.input_cost + self.output_cost + self.search_cost

    def add_direction(self, direction: Direction) -> None:
        self.requests += 1
        self.input_tokens += direction.input_tokens
        self.output_tokens += direction.output_tokens
        self.searches += direction.searches
        self.search_cost += direction.searches * SEARCH_PRICE
        price = PRICES.get(direction.model)
        if price is None:
            self.unpriced += 1
            return
        per_input, per_output = price
        self.input_cost += direction.input_tokens * per_input / 1_000_000
        self.output_cost += direction.output_tokens * per_output / 1_000_000

    def add_image_searches(self, searches: int) -> None:
        self.image_searches += searches

    def add_painting(self, painting: Painting, referenced: bool) -> None:
        self.pictures[painting.source] = self.pictures.get(painting.source, 0) + 1
        self.paint_seconds += painting.seconds
        self.referenced += referenced


@dataclass(frozen=True)
class Earlier:
    """What was used before tracking began, estimated once from the prompt history
    and the session folders that are still kept."""

    requests: int = 0
    pictures: int = 0
    cost: float = 0.0


class AllTime(BaseModel):
    """Everything since tracking began, plus the estimate of what came before."""

    since: datetime
    total: Usage = Field(default_factory=Usage)
    earlier: Earlier = Field(default_factory=Earlier)


class Ledger:
    """The all-time totals in a JSON file; each change is read, applied and written
    at once, so several sepia windows add to the same totals."""

    def __init__(self, path: Path, earlier: Callable[[], Earlier]) -> None:
        self._path = path
        self._earlier = earlier

    def read(self) -> AllTime:
        """The totals so far. The first read starts the file and estimates, once,
        what was used before it."""
        record = self._load()
        return record if record is not None else AllTime(since=datetime.now())

    def add(self, change: Callable[[Usage], None]) -> None:
        record = self._load()
        if record is None:
            return  # Unreadable right now; skip one change rather than lose them all.
        change(record.total)
        self._write(record)

    def _load(self) -> AllTime | None:
        """The stored totals; None when the file is there but cannot be read."""
        try:
            data = self._path.read_bytes()
        except FileNotFoundError:
            record = AllTime(since=datetime.now(), earlier=self._earlier())
        except OSError:
            return None
        else:
            try:
                return AllTime.model_validate_json(data)
            except ValueError:
                # Corrupt: start over, but without the estimate, since the history
                # now also holds requests that were already tracked.
                record = AllTime(since=datetime.now())
        self._write(record)
        return record

    def _write(self, record: AllTime) -> None:
        temporary = self._path.with_suffix(".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temporary, self._path)
        except OSError:
            pass  # The totals are a convenience; a full disk must not stop painting.


def estimate_earlier(history: Path, sessions: Path, model: str) -> Earlier:
    """What was used before tracking began.

    Requests are the prompt-history entries that went to Claude: everything but
    commands, except /add with text. Pictures are the ones saved in the session
    folders still kept, plus one per request older than the oldest of them, whose
    folders were pruned. The cost assumes typical tokens per request on `model`.
    """
    times = [stamp for stamp, text in _history(history) if _is_request(text)]
    kept = _session_starts(sessions)
    oldest = min(kept, default=None)
    pruned = sum(1 for stamp in times if oldest is None or stamp < oldest)
    saved = sum(len(list(folder.glob("*.png"))) for folder in kept.values())
    per_input, per_output = PRICES.get(model, (0.0, 0.0))
    tokens_in, tokens_out = EARLIER_TOKENS
    per_request = (tokens_in * per_input + tokens_out * per_output) / 1_000_000
    return Earlier(
        requests=len(times), pictures=saved + pruned, cost=len(times) * per_request
    )


def _history(path: Path) -> list[tuple[datetime, str]]:
    """Entries of a prompt_toolkit `FileHistory`: a "# <time>" line, then each line
    of the entry after a "+"."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    entries: list[tuple[datetime, list[str]]] = []
    for line in lines:
        if line.startswith("# "):
            try:
                entries.append((datetime.fromisoformat(line[2:].strip()), []))
            except ValueError:
                continue
        elif line.startswith("+") and entries:
            entries[-1][1].append(line[1:])
    return [(stamp, "\n".join(text).strip()) for stamp, text in entries]


def _is_request(text: str) -> bool:
    """Whether a history entry went to Claude, as `repl.parse_command` reads it."""
    if not text:
        return False
    if not text.startswith("/"):
        return True
    name, _, argument = text[1:].partition(" ")
    return name.strip().lower() == "add" and bool(argument.strip())


def _session_starts(root: Path) -> dict[datetime, Path]:
    try:
        folders = [path for path in root.iterdir() if path.is_dir()]
    except OSError:
        return {}
    starts: dict[datetime, Path] = {}
    for folder in folders:
        try:
            starts[datetime.strptime(folder.name, SESSION_FORMAT)] = folder
        except ValueError:
            continue
    return starts
