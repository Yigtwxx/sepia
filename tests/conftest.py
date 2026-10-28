from collections.abc import Callable

import numpy as np
import pytest

from sepia.ascii_art import CELL_HEIGHT, CELL_WIDTH

Canvas = Callable[..., np.ndarray]


@pytest.fixture
def make_canvas() -> Canvas:
    """Factory for solid RGB images sized for a `cols` x `rows` symbol grid."""

    def make(cols: int, rows: int, value: int = 0) -> np.ndarray:
        shape = (rows * CELL_HEIGHT, cols * CELL_WIDTH, 3)
        return np.full(shape, value, dtype=np.uint8)

    return make


@pytest.fixture
def wide_svg() -> str:
    """A 2:1 red drawing with a blue square in its middle."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
        '<rect width="100" height="50" fill="#ff0000"/>'
        '<rect x="40" y="15" width="20" height="20" fill="#0000ff"/>'
        "</svg>"
    )
