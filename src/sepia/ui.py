"""Look and words of the prompt window: wordmark, palette, replies, strings."""

import locale
import os
from collections.abc import Sequence
from typing import Literal

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text

from sepia import __version__

# Purple-pink, left to right across the wordmark, and one deep purple for its shadow.
BANDS = ("#f9a8d4", "#f472b6", "#e879f9", "#c084fc", "#a78bfa")
SHADOW = "#4c1d95"
ACCENT = "#e879f9"
MUTED = "#8b8b9a"
WARN = "#fb7185"
GOOD = "#c084fc"
SPINNER = "✻✽✶✳✢·"
PROMPT = " › "

# Lowercase letters on a pixel grid: rows 0-1 hold the dot of the i, rows 2-6 the
# x-height, rows 7-8 the descender of the p. Each pixel prints two columns wide.
_GLYPHS: dict[str, tuple[str, ...]] = {
    "s": (
        ".....",
        ".....",
        ".####",
        "#....",
        ".###.",
        "....#",
        "####.",
        ".....",
        ".....",
    ),
    "e": (
        ".....",
        ".....",
        ".###.",
        "#...#",
        "#####",
        "#....",
        ".####",
        ".....",
        ".....",
    ),
    "p": (
        ".....",
        ".....",
        "####.",
        "#...#",
        "#...#",
        "#...#",
        "####.",
        "#....",
        "#....",
    ),
    "i": ("#", ".", "#", "#", "#", "#", "#", ".", "."),
    "a": (
        ".....",
        ".....",
        ".###.",
        "....#",
        ".####",
        "#...#",
        ".####",
        ".....",
        ".....",
    ),
}
_GAP = 1


def wordmark(word: str = "sepia") -> Text:
    """The name in half-block pixels, banded purple to pink, with a drop shadow."""
    columns = [list(col) for col in _pixel_columns(word)]
    width = len(columns) * 2
    height = len(_GLYPHS["s"]) + 1
    grid: list[list[str | None]] = [[None] * width for _ in range(height)]
    for x, column in enumerate(columns):
        for y, on in enumerate(column):
            if on:
                for dx in (0, 1):
                    if grid[y + 1][2 * x + dx] is None:
                        grid[y + 1][2 * x + dx] = SHADOW
    for x, column in enumerate(columns):
        band = BANDS[min(len(BANDS) - 1, x * len(BANDS) // len(columns))]
        for y, on in enumerate(column):
            if on:
                grid[y][2 * x] = grid[y][2 * x + 1] = band
    if len(grid) % 2:
        grid.append([None] * width)
    text = Text(no_wrap=True)
    for top_row, bottom_row in zip(grid[0::2], grid[1::2], strict=True):
        for top, bottom in zip(top_row, bottom_row, strict=True):
            text.append(*_half_block(top, bottom))
        text.append("\n")
    text.rstrip()
    return text


def _pixel_columns(word: str) -> list[list[bool]]:
    columns: list[list[bool]] = []
    for index, letter in enumerate(word):
        rows = _GLYPHS[letter]
        for x in range(len(rows[0])):
            columns.append([row[x] == "#" for row in rows])
        if index < len(word) - 1:
            columns.extend([[False] * len(rows)] * _GAP)
    return columns


def _half_block(top: str | None, bottom: str | None) -> tuple[str, Style | str]:
    if top and bottom:
        return ("▀", Style(color=top, bgcolor=bottom)) if top != bottom else ("█", top)
    if top:
        return "▀", top
    if bottom:
        return "▄", bottom
    return " ", ""


Language = Literal["en", "tr"]

STRINGS: dict[Language, dict[str, str]] = {
    "en": {
        "welcome": "Welcome to sepia",
        "tagline": "draw with words",
        "window": "pictures open in a second window",
        "help_hint": "/help for commands",
        "tip": 'Tip: describe a scene, then add to it: "waterfall", then "mountains"',
        "placeholder": "describe a picture · / lists the commands",
        "directing": "Working on it… (writing the prompt)",
        "painting": "Working on it… (painting · {source})",
        "opening": "Opening the picture window…",
        "new_scene": "New scene. The next request starts a fresh picture.",
        "style_set": "Style: {style} · charset: {charset}",
        "no_window": "Could not open the picture window: {error}",
        "unknown": "No such command {command}",
        "help_title": "commands",
        "key_prompt": "Anthropic API key (stored in {path}): ",
        "key_missing": "sepia needs an Anthropic API key to write prompts.",
        "failure.auth": "Your Anthropic API key was rejected.",
        "failure.rate_limit": "Claude is busy right now; try again in a moment.",
        "failure.server": "Claude had a problem; try again.",
        "failure.connection": "Could not reach Claude; check your connection.",
        "failure.rejected": "Claude rejected that request.",
        "failure.refused": "Claude declined that request; try other words.",
        "failure.truncated": "The reply was cut off; try again.",
        "failure.invalid": "Claude's reply was malformed; try again.",
        "failure.paint": "Could not paint the picture: {error}",
        "source.api": "pollinations",
        "source.local": "local GPU",
    },
    "tr": {
        "welcome": "sepia'ya hoş geldin",
        "tagline": "kelimelerle çiz",
        "window": "resimler ikinci bir pencerede açılır",
        "help_hint": "komutlar için /help",
        "tip": 'İpucu: bir sahne yaz, sonra üstüne ekle: önce "şelale", sonra "dağlar"',
        "placeholder": "bir resim tarif et · / komutları listeler",
        "directing": "Üzerinde çalışıyorum… (prompt yazılıyor)",
        "painting": "Üzerinde çalışıyorum… (resim boyanıyor · {source})",
        "opening": "Resim penceresi açılıyor…",
        "new_scene": "Yeni sahne. Sıradaki istek yeni bir resimle başlar.",
        "style_set": "Stil: {style} · karakterler: {charset}",
        "no_window": "Resim penceresi açılamadı: {error}",
        "unknown": "Böyle bir komut yok: {command}",
        "help_title": "komutlar",
        "key_prompt": "Anthropic API key ({path} içine kaydedilir): ",
        "key_missing": "sepia prompt yazmak için bir Anthropic API key ister.",
        "failure.auth": "Anthropic API key reddedildi.",
        "failure.rate_limit": "Claude şu an yoğun; birazdan tekrar dene.",
        "failure.server": "Claude'da bir sorun oldu; tekrar dene.",
        "failure.connection": "Claude'a ulaşılamadı; bağlantını kontrol et.",
        "failure.rejected": "Claude bu isteği reddetti.",
        "failure.refused": "Claude bu isteği geri çevirdi; farklı anlatmayı dene.",
        "failure.truncated": "Cevap yarıda kesildi; tekrar dene.",
        "failure.invalid": "Claude'un cevabı bozuk geldi; tekrar dene.",
        "failure.paint": "Resim boyanamadı: {error}",
        "source.api": "pollinations",
        "source.local": "yerel GPU",
    },
}

COMMANDS: dict[Language, Sequence[tuple[str, str]]] = {
    "en": (
        ("/new", "start a fresh picture"),
        ("/style [ink|fill]", "switch how the picture is drawn"),
        ("/charset [classic|symbols]", "switch the character set"),
        ("/help", "show this list"),
        ("/exit", "close sepia and its window (also Ctrl+D)"),
    ),
    "tr": (
        ("/new", "yeni bir resme başla"),
        ("/style [ink|fill]", "resmin çizim stilini değiştir"),
        ("/charset [classic|symbols]", "karakter setini değiştir"),
        ("/help", "bu listeyi göster"),
        ("/exit", "sepia'yı ve penceresini kapat (Ctrl+D de olur)"),
    ),
}


def detect_language() -> Language:
    """`SEPIA_LANG` if set, else Turkish on a Turkish system, else English."""
    forced = os.environ.get("SEPIA_LANG", "").strip().lower()
    if forced in ("en", "tr"):
        return "tr" if forced == "tr" else "en"
    name = (locale.getlocale()[0] or os.environ.get("LANG", "")).lower()
    return "tr" if name.startswith(("tr", "turkish")) else "en"


class Words:
    """UI strings in one language."""

    def __init__(self, language: Language) -> None:
        self.language = language
        self._strings = STRINGS[language]

    def __call__(self, key: str, **values: object) -> str:
        return self._strings[key].format(**values)

    @property
    def commands(self) -> Sequence[tuple[str, str]]:
        return COMMANDS[self.language]


def welcome(words: Words, width: int) -> RenderableType:
    """The opening box: wordmark beside a short greeting, like spiyweb's."""
    lines = Text()
    lines.append(words("welcome"), style="bold")
    lines.append(f" {__version__}", style=MUTED)
    lines.append(f"  {words('tagline')}\n\n", style="dim")
    lines.append(f"{words('window')}\n", style=MUTED)
    lines.append(words("help_hint"), style="dim")
    mark = wordmark()
    body: RenderableType
    if width >= 90:
        grid = Table.grid(padding=(0, 3))
        grid.add_row(mark, Group(Text("\n"), lines))
        body = grid
    else:
        body = Group(mark, Text(""), lines)
    return Panel(body, border_style="dim", padding=(1, 2), expand=True)


def tip(words: Words) -> Text:
    text = Text(" ※ ", style=ACCENT)
    label, _, rest = words("tip").partition(":")
    text.append(f"{label}:", style="bold")
    text.append(rest, style=MUTED)
    return text


def echo(line: str) -> Text:
    """The submitted request, kept in the transcript."""
    return Text.assemble((PROMPT, f"bold {ACCENT}"), line)


def reply(message: str, detail: str = "", *, failed: bool = False) -> Text:
    """A reply from sepia: a bullet, the message, and an optional muted detail."""
    color = WARN if failed else ACCENT
    text = Text.assemble((" ⏺ ", color), (message, WARN if failed else ""))
    if detail:
        text.append(f"\n   {detail}", style=MUTED)
    return text


def help_table(words: Words) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_row(Text(f" {words('help_title')}", style="bold"), "")
    for usage, summary in words.commands:
        table.add_row(Text(f"   {usage}", style=ACCENT), Text(summary, style=MUTED))
    return table
