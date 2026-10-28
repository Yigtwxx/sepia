import io
import sys
import urllib.error
import urllib.parse
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from sepia import painter
from sepia.painter import (
    ApiPainter,
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


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", SIZE, (10, 200, 30)).save(buffer, "JPEG")
    return buffer.getvalue()


def _reply(data: bytes, content_type: str) -> MagicMock:
    reply = MagicMock()
    reply.__enter__.return_value = reply
    reply.read.return_value = data
    reply.headers.get_content_type.return_value = content_type
    return reply


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


def test_api_painter_keyless_request_is_private_without_auth() -> None:
    request = ApiPainter().request("a red apple", SIZE, 7)
    url = urllib.parse.urlparse(request.full_url)
    query = urllib.parse.parse_qs(url.query)
    assert request.full_url.startswith(painter.KEYLESS_URL), request.full_url
    assert url.path.endswith("a%20red%20apple"), f"Prompt not in path: {url.path}"
    assert query["private"] == ["true"], "Keyless prompts must stay out of the feed"
    assert (query["width"], query["seed"]) == (["64"], ["7"]), f"Got {query}"
    assert request.get_header("Authorization") is None, "Keyless must not send auth"


def test_api_painter_keyed_request_sends_bearer_and_model() -> None:
    request = ApiPainter(key="pk-test", model="m/x").request("apple", SIZE, 1)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
    assert request.full_url.startswith(painter.KEYED_URL), request.full_url
    assert request.get_header("Authorization") == "Bearer pk-test", "Missing bearer"
    assert query["model"] == ["m/x"], f"Got {query}"


def test_api_painter_paint_returns_decoded_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = _reply(_jpeg_bytes(), "image/jpeg")
    monkeypatch.setattr(painter.urllib.request, "urlopen", lambda *a, **k: reply)
    painting = ApiPainter().paint("apple", SIZE, 1)
    assert painting.source == "keyless", f"Got {painting.source}"
    assert painting.image.size == SIZE, f"Got {painting.image.size}"


@pytest.mark.parametrize(("code", "limited"), [(429, True), (402, True), (500, False)])
def test_api_painter_http_error_raises_with_rate_limit_flag(
    monkeypatch: pytest.MonkeyPatch, code: int, limited: bool
) -> None:
    error = urllib.error.HTTPError("u", code, "x", {}, None)  # type: ignore[arg-type]
    monkeypatch.setattr(painter.urllib.request, "urlopen", MagicMock(side_effect=error))
    with pytest.raises(PainterError) as exc:
        ApiPainter().paint("apple", SIZE, 1)
    assert exc.value.rate_limited is limited, f"HTTP {code}: {exc.value.rate_limited}"


def test_api_painter_non_image_reply_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = _reply(b'{"error": "x"}', "application/json")
    monkeypatch.setattr(painter.urllib.request, "urlopen", lambda *a, **k: reply)
    with pytest.raises(PainterError, match="not an image"):
        ApiPainter().paint("apple", SIZE, 1)


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


@pytest.mark.parametrize("key", [None, "pk-test"])
def test_build_painter_chains_keyed_api_only_with_a_key(key: str | None) -> None:
    chain, local = build_painter(key, prefer_local=False)
    keyed = isinstance(chain._fallback, FallbackPainter)
    assert keyed is (key is not None), f"key={key!r}: nested chain={keyed}"
    assert local.model_id == painter.DEFAULT_IMAGE_MODEL, "Wrong local model"


@pytest.mark.parametrize(
    ("prefer_local", "second", "third"),
    [(True, "local", "keyless"), (False, "keyless", "local")],
)
def test_build_painter_orders_local_before_keyless_when_downloaded(
    prefer_local: bool, second: str, third: str
) -> None:
    chain, local = build_painter("pk-test", prefer_local=prefer_local)
    rest = chain._fallback
    assert isinstance(rest, FallbackPainter), "Expected a nested chain"
    names = {id(local): "local"}
    order = [names.get(id(p), "keyless") for p in (rest._primary, rest._fallback)]
    assert order == [second, third], f"Expected {second} then {third}, got {order}"


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


def test_api_painter_keyed_request_sends_the_reference_link() -> None:
    request = ApiPainter(key="pk-test").request("x", SIZE, 1, LIKENESS)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
    assert query["image"] == [LIKENESS.url], f"Reference link missing: {query}"


def test_api_painter_keyless_request_leaves_the_reference_out() -> None:
    request = ApiPainter().request("x", SIZE, 1, LIKENESS)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
    assert "image" not in query, f"Keyless endpoint ignores references: {query}"


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


def test_api_painter_keyed_paint_reports_the_api_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = _reply(_jpeg_bytes(), "image/jpeg")
    monkeypatch.setattr(painter.urllib.request, "urlopen", lambda *a, **k: reply)
    painting = ApiPainter(key="pk-test").paint("apple", SIZE, 1)
    assert painting.source == "api", f"Got {painting.source}"
