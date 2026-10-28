import io
import socket
from unittest.mock import MagicMock

import pytest
from PIL import Image

from sepia import reference
from sepia.reference import find_reference, preview_image

PAGE = "https://wiki.example.org/en-us/Yunara"
PICTURE = "https://images.example.org/Yunara.png"


def _png(size: tuple[int, int] = (400, 300), color: object = (200, 40, 220)) -> bytes:
    mode = "RGBA" if isinstance(color, tuple) and len(color) == 4 else "RGB"
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, "PNG")  # type: ignore[arg-type]
    return buffer.getvalue()


def _page(meta: str) -> bytes:
    return f"<html><head><title>x</title>{meta}</head><body></body></html>".encode()


def test_preview_image_prefers_og_image_and_resolves_relative_links() -> None:
    html = (
        '<meta name="twitter:image" content="https://cdn.example.org/t.png">'
        '<meta property="og:image" content="/images/Yunara.png?v=1&amp;w=2">'
    )
    found = preview_image(html, PAGE)
    expected = "https://wiki.example.org/images/Yunara.png?v=1&w=2"
    assert found == expected, f"Expected {expected}, got {found}"


def test_preview_image_falls_back_to_twitter_image() -> None:
    html = '<meta name="twitter:image" content="https://cdn.example.org/t.png">'
    found = preview_image(html, PAGE)
    assert found == "https://cdn.example.org/t.png", f"Got {found}"


def test_preview_image_page_without_preview_returns_none() -> None:
    found = preview_image("<html><head><title>x</title></head></html>", PAGE)
    assert found is None, f"Expected None, got {found}"


def test_find_reference_image_link_returns_the_picture(web) -> None:
    web[PICTURE] = (_png(), "image/png")
    found = find_reference([PICTURE])
    assert found is not None, "A direct image link must be used"
    assert found.url == PICTURE, f"Got {found.url}"
    assert found.image.size == (400, 300), f"Got {found.image.size}"
    assert found.image.mode == "RGB", f"Got {found.image.mode}"


def test_find_reference_page_link_follows_its_preview_picture(web) -> None:
    web[PAGE] = (_page(f'<meta property="og:image" content="{PICTURE}">'), "text/html")
    web[PICTURE] = (_png(), "image/png")
    found = find_reference([PAGE])
    assert found is not None and found.url == PICTURE, f"Got {found}"


def test_find_reference_skips_logos_and_icons_and_takes_the_next_link(web) -> None:
    logo, icon = "https://a.example.org/logo.svg", "https://b.example.org/icon.png"
    web[PAGE] = (_page(f'<meta property="og:image" content="{logo}">'), "text/html")
    web[logo] = (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")
    web[icon] = (_png((32, 32)), "image/png")
    web[PICTURE] = (_png(), "image/png")
    found = find_reference([PAGE, icon, "https://gone.example.org/x", PICTURE])
    assert found is not None and found.url == PICTURE, f"Got {found}"


def test_find_reference_nothing_usable_returns_none(web) -> None:
    web[PAGE] = (_page(""), "text/html")
    assert find_reference([]) is None, "No links means no reference"
    assert find_reference([PAGE]) is None, "A page without a picture gives none"


def test_find_reference_transparent_picture_gets_a_white_background(web) -> None:
    web[PICTURE] = (_png(color=(0, 0, 0, 0)), "image/png")
    found = find_reference([PICTURE])
    assert found is not None, "A transparent render is still usable"
    pixel = found.image.getpixel((0, 0))
    assert pixel == (255, 255, 255), f"Expected white, got {pixel}"


def test_find_reference_too_large_download_is_skipped(
    web, monkeypatch: pytest.MonkeyPatch
) -> None:
    web[PICTURE] = (_png(), "image/png")
    monkeypatch.setattr(reference, "MAX_BYTES", 100)
    assert find_reference([PICTURE]) is None, "Oversized downloads must be dropped"


@pytest.mark.parametrize(
    ("link", "address"),
    [
        ("http://images.example.org/Yunara.png", "93.184.216.34"),
        (PICTURE, "127.0.0.1"),
        (PICTURE, "192.168.1.20"),
    ],
)
def test_find_reference_refuses_plain_http_and_private_hosts(
    web, monkeypatch: pytest.MonkeyPatch, link: str, address: str
) -> None:
    web[link] = (_png(), "image/png")
    resolved = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: resolved)
    assert find_reference([link]) is None, f"{link} at {address} must be refused"


def test_checked_redirects_refuse_a_redirect_to_a_private_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: private)
    handler = reference.CheckedRedirects()
    with pytest.raises(reference.UnusableLink):
        handler.redirect_request(
            MagicMock(), MagicMock(), 302, "Found", MagicMock(), "https://intranet/x"
        )
