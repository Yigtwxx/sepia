"""The picture being built up over a session."""

from dataclasses import dataclass, field

from sepia.ascii_art import CELL_HEIGHT, CELL_WIDTH

VIEWBOX_WIDTH = 1200
"""SVG user units across the canvas; the height follows the viewer's shape."""


@dataclass(frozen=True)
class Canvas:
    """The viewer window, measured in terminal cells."""

    cols: int
    rows: int

    def viewbox(self) -> tuple[int, int]:
        """SVG width and height with the same shape as the window in pixels."""
        pixel_ratio = (self.rows * CELL_HEIGHT) / (self.cols * CELL_WIDTH)
        return VIEWBOX_WIDTH, max(round(VIEWBOX_WIDTH * pixel_ratio), 1)


@dataclass
class Scene:
    """Every request so far and the SVG they produced."""

    requests: list[str] = field(default_factory=list)
    svg: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.svg is None

    def record(self, request: str, svg: str) -> None:
        self.requests.append(request)
        self.svg = svg

    def reset(self) -> None:
        self.requests.clear()
        self.svg = None
