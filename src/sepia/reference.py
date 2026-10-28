"""Find a picture of a named subject on the web, so the painter can copy its look.

The image models know no names: asked for a game character they paint a stranger,
however well the prompt describes her. With a Brave Search key, the top results of
an image search come first, the pictures a search engine shows for the name.
Otherwise, or when none is usable, the director's links follow: pages about the
subject (a wiki article, or a direct image link), of which this module takes the
preview picture (`og:image`). The first real picture of usable size wins.
"""

import io
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from http.client import HTTPMessage
from typing import IO

from PIL import Image, UnidentifiedImageError

from sepia import __version__

TIMEOUT_SECONDS = 15
MAX_BYTES = 10 * 1024 * 1024
"""Larger pages and pictures are dropped rather than read."""
MIN_SIDE = 256
"""Smaller pictures are icons and thumbnails, too coarse to copy a look from."""
USER_AGENT = f"sepia-cli/{__version__} (https://github.com/Yigtwxx/sepia)"
"""Wikimedia and others refuse clients that don't say who they are."""
LINK = re.compile(r"https?://\S+")
TRAILING = ".,;:!?'\""
"""Punctuation after a pasted link that belongs to the sentence, not the link."""
IMAGE_SEARCH = "https://api.search.brave.com/res/v1/images/search"
IMAGE_RESULTS = 5
"""Search results tried, best first; a site that refuses downloads skips to the next."""
PREVIEW_KEYS = (
    "og:image",
    "og:image:url",
    "og:image:secure_url",
    "twitter:image",
    "twitter:image:src",
)


@dataclass(frozen=True)
class Reference:
    """A picture of the subject: its public address for the web painter, which
    fetches it itself, and the decoded picture for the local one."""

    url: str
    image: Image.Image
    cutout: Image.Image | None = None
    """The picture with its transparency, when it has any, so a picture shown as it
    is can stand on the terminal's black instead of a wiki page's white."""


class UnusableLink(Exception):
    """This link gave no usable picture."""


def split_links(text: str) -> tuple[str, tuple[str, ...]]:
    """The words of a request and the links pasted into it: "yunara <link>" is the
    words "yunara" and a picture the person chose to paint from."""
    links = tuple(_trim(match) for match in LINK.findall(text))
    words = " ".join(LINK.sub(" ", text).split())
    return words, links


def _trim(link: str) -> str:
    """`link` without the sentence's punctuation; a closing parenthesis stays when
    the link opened one, as in a wiki's .../Mercury_(planet)."""
    while link and (
        link[-1] in TRAILING or (link[-1] == ")" and link.count(")") > link.count("("))
    ):
        link = link[:-1]
    return link


def find_reference(links: Sequence[str]) -> Reference | None:
    """The first usable picture behind `links`, or None when none has one."""
    for link in links:
        try:
            return _picture(link, follow_page=True)
        except UnusableLink:
            continue
    return None


def find_subject(
    subject: str, links: Sequence[str], search_key: str | None
) -> tuple[Reference | None, int]:
    """The best picture of a named subject, and the image searches it took.

    With a key, Brave's top image results for `subject` come first, as a search
    engine shows them; the pages Claude linked follow when none is usable.
    """
    searches = 0
    if search_key and subject:
        searches = 1
        found = find_reference(image_search(subject, search_key))
        if found is not None:
            return found, searches
    return find_reference(links), searches


def image_search(query: str, key: str) -> list[str]:
    """Picture links for `query` from Brave's image search, best first: each
    result's original picture, then Brave's 500-pixel copy of it, which loads even
    where the original's site refuses. Empty when the search fails."""
    params = urllib.parse.urlencode({"q": query, "count": IMAGE_RESULTS})
    request = urllib.request.Request(
        f"{IMAGE_SEARCH}?{params}",
        headers={"Accept": "application/json", "X-Subscription-Token": key},
    )
    try:
        with urllib.request.build_opener().open(
            request, timeout=TIMEOUT_SECONDS
        ) as reply:
            data = json.loads(reply.read(MAX_BYTES))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []
    links: list[str] = []
    results = data.get("results") if isinstance(data, dict) else None
    for result in results if isinstance(results, list) else []:
        if not isinstance(result, dict):
            continue
        for part, key_name in (("properties", "url"), ("thumbnail", "src")):
            section = result.get(part)
            link = section.get(key_name) if isinstance(section, dict) else None
            if isinstance(link, str) and link.startswith("https://"):
                links.append(link)
    return links


def preview_image(html: str, base: str) -> str | None:
    """The page's preview picture (og:image, else twitter:image) as a full URL."""
    parser = _MetaParser()
    parser.feed(html)
    for key in PREVIEW_KEYS:
        if key in parser.meta:
            return urllib.parse.urljoin(base, parser.meta[key])
    return None


class CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to where a link itself may go."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        _check(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _picture(url: str, follow_page: bool) -> Reference:
    data, kind, final = _download(url)
    if kind.startswith("image/"):
        image, cutout = _decode(data)
        return Reference(final, image, cutout)
    if kind == "text/html" and follow_page:
        found = preview_image(data.decode("utf-8", errors="replace"), final)
        # A preview drawn from an SVG file is a logo, map or diagram, not the subject.
        if found and ".svg" not in urllib.parse.urlsplit(found).path.lower():
            return _picture(found, follow_page=False)
    raise UnusableLink(url)


def _download(url: str) -> tuple[bytes, str, str]:
    """Body, content type and final address of `url`."""
    _check(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(CheckedRedirects)
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as reply:
            data: bytes = reply.read(MAX_BYTES + 1)
            kind: str = reply.headers.get_content_type()
            final: str = reply.geturl()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise UnusableLink(url) from exc
    if len(data) > MAX_BYTES:
        raise UnusableLink(url)
    return data, kind, final


def _check(url: str) -> None:
    """Only https, and only to hosts on the public internet: a link taken from a
    web page must not reach this machine or its network."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise UnusableLink(url)
    try:
        addresses = socket.getaddrinfo(parts.hostname, parts.port or 443)
    except (OSError, UnicodeError, ValueError) as exc:
        raise UnusableLink(url) from exc
    if not addresses or not all(
        ipaddress.ip_address(str(info[4][0])).is_global for info in addresses
    ):
        raise UnusableLink(url)


def _decode(data: bytes) -> tuple[Image.Image, Image.Image | None]:
    """The picture as RGB, transparent parts made white as on a wiki page, and the
    picture with its transparency when it has any."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UnusableLink("not a picture") from exc
    if min(image.size) < MIN_SIDE:
        raise UnusableLink("too small")
    layer = image.convert("RGBA")
    white = Image.new("RGBA", layer.size, (255, 255, 255, 255))
    flat = Image.alpha_composite(white, layer).convert("RGB")
    opaque = layer.getchannel("A").getextrema() == (255, 255)
    return flat, (None if opaque else layer)


class _MetaParser(HTMLParser):
    """Collects the first value of each `<meta property|name=... content=...>`."""

    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        fields = dict(attrs)
        key = (fields.get("property") or fields.get("name") or "").lower()
        content = (fields.get("content") or "").strip()
        if key and content:
            self.meta.setdefault(key, content)
