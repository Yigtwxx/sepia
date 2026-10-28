import json
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from sepia.ascii_art import CELL_HEIGHT, CELL_WIDTH

Canvas = Callable[..., np.ndarray]


@pytest.fixture
def make_message() -> Callable[..., SimpleNamespace]:
    """Factory for objects shaped like the SDK's final streamed message."""

    def make(
        reply: dict[str, str] | str | None = None, stop_reason: str = "end_turn"
    ) -> SimpleNamespace:
        text = reply if isinstance(reply, str) else json.dumps(reply or {})
        return SimpleNamespace(
            stop_reason=stop_reason,
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=text),
            ],
            usage=SimpleNamespace(input_tokens=1200, output_tokens=3400),
        )

    return make


@pytest.fixture
def fake_client() -> MagicMock:
    """Stands in for `anthropic.Anthropic`; set the final message per test."""
    return MagicMock()


@pytest.fixture
def set_final_message(fake_client: MagicMock) -> Callable[[SimpleNamespace], None]:
    """Make `fake_client` stream back `message` as the final message."""

    def set_message(message: SimpleNamespace) -> None:
        stream = fake_client.beta.messages.stream.return_value.__enter__.return_value
        stream.get_final_message.return_value = message

    return set_message


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
