import threading
from multiprocessing import AuthenticationError
from pathlib import Path

import pytest

from sepia.ipc import Host, Session, connect


@pytest.fixture
def host_inbox():
    inbox: list[dict] = []
    received = threading.Event()

    def on_message(message: dict) -> None:
        inbox.append(message)
        received.set()

    host = Host(on_message)
    yield host, inbox, received
    host.close()


def test_session_save_and_load_round_trip(tmp_path: Path) -> None:
    session = Session(port=50123, authkey=b"\x01\x02secret")
    path = tmp_path / "nested" / "session.json"
    session.save(path)
    loaded = Session.load(path)
    assert loaded == session, f"Expected {session}, got {loaded}"


def test_host_viewer_exchange_json_both_ways(host_inbox) -> None:
    host, inbox, received = host_inbox
    host.accept_in_background()
    viewer = connect(host.session)
    assert host.wait_connected(5), "Viewer never connected"

    assert host.send({"type": "scene", "svg": "<svg/>"}), "Send to viewer failed"
    assert viewer.poll(5), "Viewer got nothing"
    got = viewer.receive()
    assert got == {"type": "scene", "svg": "<svg/>"}, f"Viewer got {got}"

    viewer.send({"type": "size", "cols": 120, "rows": 40})
    assert received.wait(5), "Host got nothing"
    assert inbox == [{"type": "size", "cols": 120, "rows": 40}], f"Host got {inbox}"
    viewer.close()


def test_host_send_after_viewer_closes_returns_false(host_inbox) -> None:
    host, _, _ = host_inbox
    host.accept_in_background()
    viewer = connect(host.session)
    assert host.wait_connected(5), "Viewer never connected"
    viewer.close()
    for _ in range(50):  # the reader thread notices the closed socket
        if not host.connected:
            break
        threading.Event().wait(0.05)
    assert not host.send({"type": "bye"}), "Send to a closed viewer must fail"
    assert not host.connected, "Host still thinks the viewer is connected"


def test_host_send_without_viewer_returns_false(host_inbox) -> None:
    host, _, _ = host_inbox
    assert not host.send({"type": "scene"}), "Send without a viewer must fail"


def test_connect_with_wrong_key_is_rejected(host_inbox) -> None:
    host, _, _ = host_inbox
    host.accept_in_background()
    impostor = Session(port=host.session.port, authkey=b"wrong-key")
    with pytest.raises(AuthenticationError):
        connect(impostor)
    assert not host.connected, "An impostor must not count as a viewer"
    viewer = connect(host.session)  # the real viewer can still get in afterwards
    assert host.wait_connected(5), "Host stopped accepting after a failed handshake"
    viewer.close()
