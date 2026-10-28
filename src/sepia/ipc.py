"""Authenticated JSON messages between the prompt window and the viewer window.

The prompt listens on a random loopback port; the viewer connects with a one-time key
read from a session file only the current user can read. `multiprocessing.connection`
does the HMAC handshake. Messages travel as JSON bytes and are never unpickled, so a
peer can send data but never code.
"""

import contextlib
import json
import secrets
import stat
import threading
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any, Protocol

HOST = "127.0.0.1"

Message = dict[str, Any]


class _Connection(Protocol):
    """The part of `multiprocessing.connection.Connection` sepia uses."""

    def send_bytes(self, buf: bytes) -> None: ...
    def recv_bytes(self) -> bytes: ...
    def poll(self, timeout: float | None = ...) -> bool: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class Session:
    """Where the viewer finds the prompt and how it proves who it is."""

    port: int
    authkey: bytes

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"port": self.port, "authkey": self.authkey.hex()}
        path.write_text(json.dumps(data), encoding="utf-8")
        with contextlib.suppress(OSError):  # Windows ignores POSIX modes
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @classmethod
    def load(cls, path: Path) -> "Session":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(port=int(data["port"]), authkey=bytes.fromhex(data["authkey"]))


class Channel:
    """One end of an open link."""

    def __init__(self, connection: _Connection) -> None:
        self._connection = connection
        self._send_lock = threading.Lock()

    def send(self, message: Message) -> None:
        """Send `message`; raises `OSError` or `EOFError` once the peer is gone."""
        data = json.dumps(message).encode("utf-8")
        with self._send_lock:
            self._connection.send_bytes(data)

    def poll(self, timeout: float = 0.0) -> bool:
        return self._connection.poll(timeout)

    def receive(self) -> Message:
        """Next message; raises `EOFError` or `OSError` once the peer is gone."""
        message = json.loads(self._connection.recv_bytes().decode("utf-8"))
        if not isinstance(message, dict):
            raise ValueError("expected a JSON object")
        return message

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._connection.close()


def connect(session: Session) -> Channel:
    """Viewer side: open the link described by `session`."""
    return Channel(Client((HOST, session.port), authkey=session.authkey))


class Host:
    """Prompt side: waits for one viewer at a time and relays what it reports.

    `on_message` runs on a background thread for every message the viewer sends.
    """

    def __init__(self, on_message: Callable[[Message], None]) -> None:
        self._on_message = on_message
        authkey = secrets.token_bytes(32)
        self._listener = Listener((HOST, 0), authkey=authkey)
        self.session = Session(port=int(self._listener.address[1]), authkey=authkey)
        self._channel: Channel | None = None
        self._connected = threading.Event()
        self._lock = threading.Lock()
        self._accepting = False

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def accept_in_background(self) -> None:
        """Start waiting for a viewer unless one is connected or already awaited."""
        with self._lock:
            if self._accepting or self.connected:
                return
            self._accepting = True
        threading.Thread(target=self._accept, name="sepia-accept", daemon=True).start()

    def wait_connected(self, timeout: float) -> bool:
        return self._connected.wait(timeout)

    def send(self, message: Message) -> bool:
        """Deliver `message` to the viewer; False when no viewer is connected."""
        channel = self._channel
        if channel is None:
            return False
        try:
            channel.send(message)
        except (OSError, EOFError):
            self._drop(channel)
            return False
        return True

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
        with contextlib.suppress(OSError):
            self._listener.close()

    def _accept(self) -> None:
        while True:
            try:
                channel = Channel(self._listener.accept())
                break
            except (AuthenticationError, EOFError):
                continue  # a peer without the key; keep waiting for the real viewer
            except OSError:  # the listener was closed
                with self._lock:
                    self._accepting = False
                return
        with self._lock:
            self._channel = channel
            self._accepting = False
        self._connected.set()
        self._read(channel)

    def _read(self, channel: Channel) -> None:
        while True:
            try:
                message = channel.receive()
            except (OSError, EOFError, ValueError):
                self._drop(channel)
                return
            self._on_message(message)

    def _drop(self, channel: Channel) -> None:
        with self._lock:
            if self._channel is not channel:
                return
            self._channel = None
            self._connected.clear()
        channel.close()
