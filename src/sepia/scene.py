"""The picture being built up over a session."""

import secrets
from dataclasses import dataclass, field

from PIL import Image

from sepia.ascii_art import CELL_HEIGHT, CELL_WIDTH
from sepia.reference import Reference


@dataclass(frozen=True)
class Canvas:
    """The viewer window, measured in terminal cells."""

    cols: int
    rows: int

    @property
    def aspect(self) -> float:
        """Width over height of the window in pixels (cells are twice as tall)."""
        return (self.cols * CELL_WIDTH) / (self.rows * CELL_HEIGHT)


def _new_seed() -> int:
    return secrets.randbelow(2**31)


@dataclass
class Scene:
    """Every request so far, the prompts they became, and the latest picture.

    The seed stays fixed for the whole scene, so a repainted picture keeps its
    composition instead of starting from fresh noise. The latest reference picture
    stays too, so /add keeps a named character's look.
    """

    requests: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    image: Image.Image | None = None
    seed: int = field(default_factory=_new_seed)
    likeness: Reference | None = None

    @property
    def is_empty(self) -> bool:
        return self.image is None

    def record(
        self,
        request: str,
        prompt: str,
        image: Image.Image,
        likeness: Reference | None = None,
    ) -> None:
        self.requests.append(request)
        self.prompts.append(prompt)
        self.image = image
        self.likeness = likeness

    def reset(self) -> None:
        self.requests.clear()
        self.prompts.clear()
        self.image = None
        self.likeness = None
        self.seed = _new_seed()
