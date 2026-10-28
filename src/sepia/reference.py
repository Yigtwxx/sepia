"""Find a picture of a named subject on the web, so the painter can copy its look.

The image models know no names: asked for a game character they paint a stranger,
however well the prompt describes her. The director links pages about the subject
(a wiki article, or a direct image link); this module takes each page's preview
picture (`og:image`) and keeps the first one that is a real picture of usable size.
"""

import io
import ipaddress
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
        return Reference(final, _decode(data))
    if kind == "text/html" and follow_page:
        found = preview_image(data.decode("utf-8", errors="replace"), final)
        if found:
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


def _decode(data: bytes) -> Image.Image:
    """The picture as RGB; transparent parts become white, as on a wiki page."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UnusableLink("not a picture") from exc
    if min(image.size) < MIN_SIDE:
        raise UnusableLink("too small")
    layer = image.convert("RGBA")
    white = Image.new("RGBA", layer.size, (255, 255, 255, 255))
    return Image.alpha_composite(white, layer).convert("RGB")


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
