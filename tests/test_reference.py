import io
import json
import socket
import urllib.parse
from unittest.mock import MagicMock

import pytest
from PIL import Image

from sepia import reference
from sepia.reference import (
    IMAGE_RESULTS,
    IMAGE_SEARCH,
    find_reference,
    find_subject,
    image_search,
    preview_image,
    split_links,
)

PAGE = "https://wiki.example.org/en-us/Yunara"
PICTURE = "https://images.example.org/Yunara.png"


def _png(size: tuple[int, int] = (400, 300), color: object = (200, 40, 220)) -> bytes:
    mode = "RGBA" if isinstance(color, tuple) and len(color) == 4 else "RGB"
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, "PNG")  # type: ignore[arg-type]
    return buffer.getvalue()


def _page(meta: str) -> bytes:
    return f"<html><head><title>x</title>{meta}</head><body></body></html>".encode()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("waterfall", ("waterfall", ())),
        (f"yunara {PICTURE}", ("yunara", (PICTURE,))),
        (PICTURE, ("", (PICTURE,))),
        (f"paint this: {PICTURE}.", ("paint this:", (PICTURE,))),
        (
            "at night https://en.wikipedia.org/wiki/Mercury_(planet)",
            ("at night", ("https://en.wikipedia.org/wiki/Mercury_(planet)",)),
        ),
    ],
)
def test_split_links_separates_words_from_pasted_links(
    text: str, expected: tuple[str, tuple[str, ...]]
) -> None:
    got = split_links(text)
    assert got == expected, f"Expected {expected}, got {got}"


def test_split_links_link_in_parentheses_drops_the_closing_one() -> None:
    _, links = split_links(f"a castle (like {PICTURE})")
    assert links == (PICTURE,), f"Got {links}"


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


@pytest.mark.parametrize("host", ["www.google.com", "www.google.com.tr"])
def test_find_reference_google_image_result_follows_its_imgurl(web, host: str) -> None:
    # What a share.google link from Google Images lands on: a page with no preview
    # picture, the picture's own address in its query.
    query = urllib.parse.urlencode({"imgurl": PICTURE, "imgrefurl": PAGE, "tbnid": "x"})
    result = f"https://{host}/imgres?{query}"
    web[result] = (_page(""), "text/html")
    web[PICTURE] = (_png(), "image/png")
    found = find_reference([result])
    assert found is not None and found.url == PICTURE, f"Got {found}"


def test_find_reference_imgurl_on_another_site_is_not_followed(web) -> None:
    query = urllib.parse.urlencode({"imgurl": PICTURE})
    elsewhere = f"https://example.org/imgres?{query}"
    web[elsewhere] = (_page(""), "text/html")
    web[PICTURE] = (_png(), "image/png")
    assert find_reference([elsewhere]) is None, "Only Google's result page is read"


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


ORIGINAL = "https://art.example.org/yunara-splash.jpg"
THUMBNAIL = "https://imgs.search.brave.com/yunara-splash"


def _search_url(query: str) -> str:
    params = urllib.parse.urlencode({"q": query, "count": IMAGE_RESULTS})
    return f"{IMAGE_SEARCH}?{params}"


def _results(*items: dict[str, object]) -> bytes:
    return json.dumps({"type": "images", "results": list(items)}).encode()


SPLASH = {"properties": {"url": ORIGINAL}, "thumbnail": {"src": THUMBNAIL}}


def test_image_search_lists_originals_then_brave_copies(web) -> None:
    other = {"properties": {"url": "http://plain.example.org/x.jpg"}, "thumbnail": {}}
    web[_search_url("Yunara")] = (_results(SPLASH, other, "junk"), "application/json")
    links = image_search("Yunara", "key")
    assert links == [ORIGINAL, THUMBNAIL], f"Expected https links only, got {links}"


def test_image_search_sends_the_key_as_a_header_only(
    web, monkeypatch: pytest.MonkeyPatch
) -> None:
    web[_search_url("Yunara")] = (_results(SPLASH), "application/json")
    sent: list[object] = []
    opener = reference.urllib.request.build_opener()
    original = opener.open.side_effect

    def record(request, timeout):
        sent.append(request)
        return original(request, timeout)

    opener.open.side_effect = record
    image_search("Yunara", "secret-key")
    request = sent[0]
    assert request.get_header("X-subscription-token") == "secret-key", "Key missing"
    assert "secret-key" not in request.full_url, "The key must not be in the URL"


def test_image_search_failure_returns_nothing(web) -> None:
    assert image_search("Yunara", "key") == [], "A failed search gives no links"


def test_find_subject_with_key_takes_the_top_search_picture(web) -> None:
    web[_search_url("Yunara")] = (_results(SPLASH), "application/json")
    web[ORIGINAL] = (_png(), "image/png")
    web[PICTURE] = (_png(), "image/png")
    found, searches = find_subject("Yunara", [PICTURE], "key")
    assert found is not None and found.url == ORIGINAL, f"Got {found}"
    assert searches == 1, f"Expected one search, got {searches}"


def test_find_subject_refused_original_falls_back_to_brave_copy(web) -> None:
    web[_search_url("Yunara")] = (_results(SPLASH), "application/json")
    web[THUMBNAIL] = (_png((500, 400)), "image/jpeg")
    found, _ = find_subject("Yunara", [], "key")
    assert found is not None and found.url == THUMBNAIL, f"Got {found}"


def test_find_subject_nothing_usable_in_search_uses_claudes_links(web) -> None:
    web[PICTURE] = (_png(), "image/png")
    found, searches = find_subject("Yunara", [PICTURE], "key")
    assert found is not None and found.url == PICTURE, f"Got {found}"
    assert searches == 1, "The search still ran"


def test_find_subject_without_key_uses_claudes_links_only(web) -> None:
    web[PICTURE] = (_png(), "image/png")
    found, searches = find_subject("Yunara", [PICTURE], None)
    assert found is not None and found.url == PICTURE, f"Got {found}"
    assert searches == 0, f"No key means no search, got {searches}"


def test_find_reference_transparent_picture_keeps_its_cutout(web) -> None:
    web[PICTURE] = (_png(color=(0, 0, 0, 0)), "image/png")
    found = find_reference([PICTURE])
    assert found is not None and found.cutout is not None, "Cutout missing"
    assert found.cutout.getpixel((0, 0))[3] == 0, "Transparency was lost"


def test_find_reference_opaque_picture_has_no_cutout(web) -> None:
    web[PICTURE] = (_png(), "image/png")
    found = find_reference([PICTURE])
    assert found is not None and found.cutout is None, f"Got {found}"


def test_find_reference_skips_a_preview_drawn_from_svg(web) -> None:
    logo = "https://upload.example.org/thumb/Tower_logo.svg/960px-Tower_logo.svg.png"
    web[PAGE] = (_page(f'<meta property="og:image" content="{logo}">'), "text/html")
    web[logo] = (_png(), "image/png")
    assert find_reference([PAGE]) is None, "An SVG logo is not the subject"
