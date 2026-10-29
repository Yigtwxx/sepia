import base64
import io
import json
import sys
import threading
import urllib.error
import urllib.request
from contextlib import nullcontext
from email.parser import BytesParser
from email.policy import HTTP
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from sepia import painter
from sepia.painter import (
    CloudflarePainter,
    FallbackPainter,
    PainterError,
    Painting,
    build_painter,
    image_size,
    select_device,
)
from sepia.reference import Reference

SIZE = (64, 48)
LIKENESS = Reference("https://img.example.org/Yunara.png", Image.new("RGB", (8, 8)))
ACCOUNT, TOKEN = "0123456789abcdef0123456789abcdef", "cf-test-token"


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", SIZE, (10, 200, 30)).save(buffer, "JPEG")
    return buffer.getvalue()


def _reply(data: bytes) -> MagicMock:
    reply = MagicMock()
    reply.__enter__.return_value = reply
    reply.read.return_value = data
    return reply


def _cloudflare_reply(image: bytes) -> MagicMock:
    """What Workers AI answers: the picture as base64 inside the result."""
    body = {"result": {"image": base64.b64encode(image).decode()}, "success": True}
    return _reply(json.dumps(body).encode())


def _form(request: urllib.request.Request) -> dict[str, bytes]:
    """The multipart fields of `request`, by name."""
    data = request.data
    assert isinstance(data, bytes), f"Expected a bytes body, got {type(data)}"
    head = f"Content-Type: {request.get_header('Content-type')}\r\n\r\n".encode()
    message = BytesParser(policy=HTTP).parsebytes(head + data)
    return {
        str(part.get_param("name", header="content-disposition")): part.get_payload(
            decode=True
        )
        for part in message.iter_parts()  # type: ignore[attr-defined]
    }


def _http_error(code: int, body: object = None) -> urllib.error.HTTPError:
    data = json.dumps(body).encode() if body is not None else b""
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(data))  # type: ignore[arg-type]


class _StubPainter:
    def __init__(self, error: PainterError | None = None) -> None:
        self.error = error
        self.calls = 0
        self.likeness: Reference | None = None

    def paint(self, prompt, size, seed, reference=None, likeness=None) -> Painting:
        self.calls += 1
        self.likeness = likeness
        if self.error is not None:
            raise self.error
        return Painting(Image.new("RGB", size), "local", 0.0)


@pytest.mark.parametrize("aspect", [1.5, 1.0, 0.5, 3.0])
def test_image_size_keeps_aspect_and_multiples_of_16(aspect: float) -> None:
    width, height = image_size(aspect)
    assert width % 16 == 0 and height % 16 == 0, (
        f"Not multiples of 16: {width}x{height}"
    )
    assert width / height == pytest.approx(aspect, rel=0.05), f"{width}x{height}"


def test_cloudflare_painter_request_posts_the_form_to_the_account_model() -> None:
    request = CloudflarePainter(ACCOUNT, TOKEN).request("a red apple", SIZE, 7)
    form = _form(request)
    expected = painter.CLOUDFLARE_URL.format(
        account=ACCOUNT, model=painter.CLOUDFLARE_MODEL
    )
    assert request.full_url == expected, f"Got {request.full_url}"
    assert request.get_method() == "POST", "Workers AI takes a POST"
    assert request.get_header("Authorization") == f"Bearer {TOKEN}", "Missing bearer"
    fields = {name: form[name] for name in ("prompt", "seed")}
    assert fields == {"prompt": b"a red apple", "seed": b"7"}, f"Got {fields}"
    pictures = [name for name in form if name.startswith("input_image")]
    assert not pictures, f"A new picture sends no input pictures: {pictures}"


@pytest.mark.parametrize(
    ("size", "expected"),
    [((1024, 640), (b"1024", b"640")), ((3000, 100), (b"1920", b"256"))],
)
def test_cloudflare_painter_request_keeps_sides_in_the_api_range(
    size: tuple[int, int], expected: tuple[bytes, bytes]
) -> None:
    form = _form(CloudflarePainter(ACCOUNT, TOKEN).request("x", size, 1))
    got = (form["width"], form["height"])
    assert got == expected, f"{size}: sent {got}"


def test_cloudflare_painter_request_sends_previous_picture_then_reference() -> None:
    previous = Image.new("RGB", (1024, 640), (1, 2, 3))
    cloudflare = CloudflarePainter(ACCOUNT, TOKEN)
    form = _form(cloudflare.request("x", SIZE, 1, previous, LIKENESS))
    first = Image.open(io.BytesIO(form["input_image_0"]))
    second = Image.open(io.BytesIO(form["input_image_1"]))
    assert max(first.size) == painter.INPUT_SIDE, f"Not shrunk to fit: {first.size}"
    assert first.getpixel((0, 0)) == (1, 2, 3), "input_image_0 must be the previous"
    assert second.size == LIKENESS.image.size, f"Reference resized: {second.size}"


def test_cloudflare_painter_paint_decodes_the_base64_picture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = _cloudflare_reply(_jpeg_bytes())
    monkeypatch.setattr(painter.urllib.request, "urlopen", lambda *a, **k: reply)
    painting = CloudflarePainter(ACCOUNT, TOKEN).paint("apple", SIZE, 1)
    assert painting.source == "api", f"Got {painting.source}"
    assert painting.image.size == SIZE, f"Got {painting.image.size}"


@pytest.mark.parametrize(
    "body", [b'{"result": {}}', b"not json", b'{"result": {"image": "!!"}}']
)
def test_cloudflare_painter_reply_without_a_picture_raises(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    reply = _reply(body)
    monkeypatch.setattr(painter.urllib.request, "urlopen", lambda *a, **k: reply)
    with pytest.raises(PainterError, match="no readable picture"):
        CloudflarePainter(ACCOUNT, TOKEN).paint("apple", SIZE, 1)


USED_UP_CODE = {"errors": [{"code": 4006, "message": "4006: daily"}]}
USED_UP_TEXT = {"errors": [{"message": "you have used up your daily free allocation"}]}
FLAGGED = {
    "errors": [
        {
            "code": 3030,
            "message": "AiError: AiError: Your output has been flagged. Please choose "
            "another prompt / input image combination (1c1884e3)",
        }
    ]
}


@pytest.mark.parametrize(
    ("code", "body", "limited", "used_up", "words"),
    [
        (429, None, True, False, "HTTP 429"),
        (500, None, False, False, "HTTP 500"),
        (401, None, False, False, "rejected the API token"),
        (429, USED_UP_CODE, False, True, "free neurons are used up"),
        (400, USED_UP_TEXT, False, True, "free neurons are used up"),
        (400, FLAGGED, False, False, "safety filter flagged the picture"),
    ],
)
def test_cloudflare_painter_http_error_raises_with_limit_and_credit_flags(
    monkeypatch: pytest.MonkeyPatch,
    code: int,
    body: object,
    limited: bool,
    used_up: bool,
    words: str,
) -> None:
    error = _http_error(code, body)
    monkeypatch.setattr(painter.urllib.request, "urlopen", MagicMock(side_effect=error))
    with pytest.raises(PainterError) as exc:
        CloudflarePainter(ACCOUNT, TOKEN).paint("apple", SIZE, 1)
    flags = (exc.value.rate_limited, exc.value.out_of_credit)
    assert flags == (limited, used_up), (
        f"HTTP {code}: (rate_limited, out_of_credit)={flags}"
    )
    assert words in str(exc.value), f"Expected {words!r} in {exc.value}"
    assert TOKEN not in str(exc.value), "The token must never reach a message"


def test_fallback_painter_uses_primary_when_it_works() -> None:
    primary, fallback = _StubPainter(), _StubPainter()
    FallbackPainter(primary, fallback).paint("x", SIZE, 1)
    assert (primary.calls, fallback.calls) == (1, 0), "Fallback must stay idle"


def test_fallback_painter_failure_falls_back_and_retries_primary_next_time() -> None:
    primary, fallback = _StubPainter(PainterError("down")), _StubPainter()
    chain = FallbackPainter(primary, fallback)
    chain.paint("x", SIZE, 1)
    chain.paint("x", SIZE, 1)
    assert (primary.calls, fallback.calls) == (2, 2), "A plain failure has no cooldown"


def test_fallback_painter_rate_limit_skips_primary_during_cooldown() -> None:
    primary = _StubPainter(PainterError("slow down", rate_limited=True))
    fallback = _StubPainter()
    chain = FallbackPainter(primary, fallback, cooldown=60)
    chain.paint("x", SIZE, 1)
    chain.paint("x", SIZE, 1)
    assert (primary.calls, fallback.calls) == (1, 2), "Primary must rest after 429"


def test_fallback_painter_out_of_credit_skips_primary_for_the_session() -> None:
    primary = _StubPainter(PainterError("used up", out_of_credit=True))
    fallback = _StubPainter()
    # No cooldown: a rate limit would retry at once, running out of credit must not.
    chain = FallbackPainter(primary, fallback, cooldown=0)
    for _ in range(3):
        chain.paint("x", SIZE, 1)
    assert (primary.calls, fallback.calls) == (1, 3), "Primary must stay off"


def test_fallback_painter_retry_primary_ends_an_out_of_credit_stop() -> None:
    primary = _StubPainter(PainterError("used up", out_of_credit=True))
    chain = FallbackPainter(primary, _StubPainter())
    chain.paint("x", SIZE, 1)
    chain.retry_primary()
    chain.paint("x", SIZE, 1)
    assert primary.calls == 2, f"/api must try the primary again: {primary.calls}"


def test_build_painter_without_cloudflare_paints_locally_only() -> None:
    api, local = build_painter(None)
    assert api is None, f"Expected no API chain, got {api}"
    assert local.model_id == painter.DEFAULT_IMAGE_MODEL, "Wrong local model"


def test_build_painter_with_cloudflare_falls_back_to_the_local_model() -> None:
    api, local = build_painter((ACCOUNT, TOKEN))
    assert api is not None, "Expected an API chain"
    assert isinstance(api._primary, CloudflarePainter), f"Got {api._primary}"
    assert api._fallback is local, "The local model must back Cloudflare up"


def test_build_painter_given_local_painter_keeps_it() -> None:
    loaded = painter.LocalPainter()
    api, local = build_painter((ACCOUNT, TOKEN), local=loaded)
    assert local is loaded, "A loaded local model must not be built again"
    assert api is not None and api._fallback is loaded, "It must back Cloudflare up"


@pytest.mark.parametrize(
    ("cuda", "mps", "expected"),
    [(True, True, "cuda"), (False, True, "mps"), (False, False, "cpu")],
)
def test_select_device_prefers_cuda_then_mps_then_cpu(
    monkeypatch: pytest.MonkeyPatch, cuda: bool, mps: bool, expected: str
) -> None:
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: cuda),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert select_device() == expected, f"cuda={cuda} mps={mps}"


def test_local_painter_without_extra_raises_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(painter, "local_installed", lambda: False)
    with pytest.raises(PainterError, match=r"sepia-cli\[local\]"):
        painter.LocalPainter().paint("x", SIZE, 1)


def test_download_local_model_failed_download_raises_painter_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> str:
        raise OSError("connection reset")

    monkeypatch.setattr(painter, "local_installed", lambda: True)
    hub = SimpleNamespace(snapshot_download=refuse)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    with pytest.raises(PainterError, match="could not download"):
        painter.download_local_model()


def test_local_painter_load_in_background_builds_on_another_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(painter, "local_installed", lambda: True)
    local = painter.LocalPainter()
    builders: list[str] = []

    def build() -> None:
        builders.append(threading.current_thread().name)
        local._pipe = MagicMock()

    monkeypatch.setattr(local, "_build", build)
    local.load_in_background().join(timeout=5)
    assert local.loaded, "The background load must leave the pipeline loaded"
    assert builders == ["sepia-load"], f"Built on {builders}, not the load thread"


def test_local_painter_load_in_background_failure_is_left_for_paint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(painter, "local_installed", lambda: False)
    uncaught: list[object] = []
    monkeypatch.setattr(threading, "excepthook", uncaught.append)
    local = painter.LocalPainter()
    local.load_in_background().join(timeout=5)
    assert not uncaught, f"A failed background load must stay quiet: {uncaught}"
    assert not local.loaded, "Nothing may be loaded after a failure"


def test_fallback_painter_passes_the_reference_to_the_painter_it_uses() -> None:
    primary, fallback = _StubPainter(PainterError("down")), _StubPainter()
    FallbackPainter(primary, fallback).paint("x", SIZE, 1, likeness=LIKENESS)
    assert primary.likeness is LIKENESS, "Primary must get the reference"
    assert fallback.likeness is LIKENESS, "Fallback must get the reference"


def test_local_painter_paints_from_previous_picture_and_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_torch = SimpleNamespace(
        Generator=MagicMock(), inference_mode=lambda: nullcontext()
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(painter, "local_installed", lambda: True)
    local = painter.LocalPainter()
    local._pipe = MagicMock()
    local._pipe.return_value.images = [Image.new("RGB", SIZE)]
    previous = Image.new("RGB", (8, 8), (1, 2, 3))
    local.paint("x", SIZE, 1, previous, LIKENESS)
    images = local._pipe.call_args.kwargs["image"]
    sources = [image.getpixel((0, 0)) for image in images]
    expected = [(1, 2, 3), LIKENESS.image.getpixel((0, 0))]
    assert sources == expected, f"Expected previous picture then reference: {sources}"
