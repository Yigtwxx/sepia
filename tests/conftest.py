import io
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.input.base import PipeInput
from prompt_toolkit.output.vt100 import Vt100_Output

from sepia import config
from sepia.ascii_art import CELL_HEIGHT, CELL_WIDTH

Canvas = Callable[..., np.ndarray]
KEY_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "BRAVE_SEARCH_API_KEY",
)


@pytest.fixture(autouse=True)
def private_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own config folder: keys, choices and history written by
    the code under test never reach the real one."""
    folder = tmp_path / "config"
    monkeypatch.setattr(config, "config_dir", lambda: folder)
    return folder


@pytest.fixture
def env_file(monkeypatch: pytest.MonkeyPatch) -> Path:
    """The user config `.env`, in the test's own folder, with no key set."""
    for variable in KEY_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    return config.user_env_file()


@pytest.fixture
def make_message() -> Callable[..., SimpleNamespace]:
    """Factory for objects shaped like the SDK's final streamed message."""

    def make(
        reply: dict[str, object] | str | None = None,
        stop_reason: str = "end_turn",
        searches: int | None = None,
    ) -> SimpleNamespace:
        text = reply if isinstance(reply, str) else json.dumps(reply or {})
        server = (
            None if searches is None else SimpleNamespace(web_search_requests=searches)
        )
        return SimpleNamespace(
            model="claude-haiku-5-5",
            stop_reason=stop_reason,
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=text),
            ],
            usage=SimpleNamespace(
                input_tokens=1200, output_tokens=3400, server_tool_use=server
            ),
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
def web(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[bytes, str]]:
    """A fake public internet for `sepia.reference`: map url -> (body, type).

    Every host resolves to a public address; unknown urls answer 404.
    """
    import socket
    import urllib.error
    import urllib.request

    pages: dict[str, tuple[bytes, str]] = {}

    def open_url(request: urllib.request.Request, timeout: float) -> MagicMock:
        url = request.full_url
        if url not in pages:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]
        body, kind = pages[url]
        reply = MagicMock()
        reply.__enter__.return_value = reply
        reply.read.side_effect = lambda limit=-1: body if limit < 0 else body[:limit]
        reply.headers.get_content_type.return_value = kind
        reply.geturl.return_value = url
        return reply

    opener = MagicMock()
    opener.open.side_effect = open_url
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: opener)
    public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: public)
    return pages


@pytest.fixture
def terminal() -> Iterator[tuple[PipeInput, io.StringIO]]:
    """A fake 80x24 terminal: keystrokes go in through the pipe, drawing comes out."""
    screen = io.StringIO()
    with create_pipe_input() as keys:
        output = Vt100_Output(screen, lambda: Size(rows=24, columns=80), term="xterm")
        with create_app_session(input=keys, output=output):
            yield keys, screen


@pytest.fixture
def resizable_terminal() -> Iterator[tuple[PipeInput, list[Size]]]:
    """Like `terminal`, but a test resizes it by replacing `sizes[0]`."""
    sizes = [Size(rows=24, columns=80)]
    with create_pipe_input() as keys:
        output = Vt100_Output(io.StringIO(), lambda: sizes[0], term="xterm")
        with create_app_session(input=keys, output=output):
            yield keys, sizes
