"""The picture being built up over a session."""

import dataclasses
import secrets
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from sepia.ascii_art import CELL_HEIGHT, CELL_WIDTH
from sepia.reference import Reference

UNDO_LIMIT = 20
"""Earlier scenes kept for /undo; each holds a picture of about 2 MB."""


@dataclass(frozen=True)
class Canvas:
    """The viewer window, measured in terminal cells."""

    cols: int
    rows: int

    @property
    def aspect(self) -> float:
        """Width over height of the window in pixels (cells are twice as tall)."""
        return (self.cols * CELL_WIDTH) / (self.rows * CELL_HEIGHT)


def new_seed() -> int:
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
    seed: int = field(default_factory=new_seed)
    likeness: Reference | None = None
    path: Path | None = None
    """Where the picture is kept in the session folder; the viewer reads it there."""
    base: Image.Image | None = None
    """The picture the latest one was painted over (/add), so /again paints over it
    too."""

    @property
    def is_empty(self) -> bool:
        return self.image is None

    def record(
        self,
        request: str,
        prompt: str,
        image: Image.Image,
        likeness: Reference | None = None,
        *,
        path: Path | None = None,
        base: Image.Image | None = None,
    ) -> None:
        self.requests.append(request)
        self.prompts.append(prompt)
        self.image = image
        self.likeness = likeness
        self.path = path
        self.base = base

    def copy(self) -> "Scene":
        """A scene to change while this one stays as it was. The lists are new;
        the pictures are shared, since nothing changes a picture in place."""
        return dataclasses.replace(
            self, requests=list(self.requests), prompts=list(self.prompts)
        )


class History:
    """Earlier scenes, newest last, for /undo; the oldest go beyond `limit`."""

    def __init__(self, limit: int = UNDO_LIMIT) -> None:
        self._scenes: deque[Scene] = deque(maxlen=limit)

    def __len__(self) -> int:
        return len(self._scenes)

    def push(self, scene: Scene) -> None:
        self._scenes.append(scene)

    def pop(self) -> Scene | None:
        """The newest scene, taken out; None when there is none left."""
        return self._scenes.pop() if self._scenes else None
