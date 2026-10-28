"""Look and words of the prompt window: wordmark, palette, replies, strings."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sepia import __version__

if TYPE_CHECKING:
    from sepia.usage import Usage

# Purple-pink, left to right across the wordmark, and one deep purple for its shadow.
BANDS = ("#f9a8d4", "#f472b6", "#e879f9", "#c084fc", "#a78bfa")
SHADOW = "#4c1d95"
ACCENT = "#e879f9"
MUTED = "#8b8b9a"
WARN = "#fb7185"
GOOD = "#c084fc"
SPINNER = "✻✽✶✳✢·"
PROMPT = " › "
POINTER = "❯"
"""Marks the highlighted option in a menu."""
CHECK = "✔"
"""Marks the option that is in use."""
CLEAR = "\x1b[2J\x1b[3J\x1b[H"
"""Screen and scrollback, then home: what starting Claude Code does to a shell. Clearing
the screen alone leaves the old lines one scroll away in Windows Terminal."""
FRAME = "#5b5b6b"

BLOCK = "█"
"""The cell the letters are made of; every other glyph of the mark is shadow."""

# The figlet font ANSI Shadow, six rows like the wordmarks of the owner's other
# terminal tools (spiyweb, proofpath), so the family reads as one. The font has
# capitals only; the name stays lowercase everywhere else.
WORDMARK: tuple[str, ...] = (
    "███████╗███████╗██████╗ ██╗ █████╗ ",
    "██╔════╝██╔════╝██╔══██╗██║██╔══██╗",
    "███████╗█████╗  ██████╔╝██║███████║",
    "╚════██║██╔══╝  ██╔═══╝ ██║██╔══██║",
    "███████║███████╗██║     ██║██║  ██║",
    "╚══════╝╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝",
)


def wordmark() -> Text:
    """The mark: letters banded pink to purple left to right, shadow in one color."""
    width = max(len(line) for line in WORDMARK)
    text = Text(no_wrap=True)
    for index, line in enumerate(WORDMARK):
        for column, char in enumerate(line.ljust(width)):
            if char == " ":
                text.append(char)
            elif char == BLOCK:
                text.append(char, BANDS[column * len(BANDS) // width])
            else:
                text.append(char, SHADOW)
        if index < len(WORDMARK) - 1:
            text.append("\n")
    return text


STRINGS: dict[str, str] = {
    "welcome": "Welcome to sepia",
    "tagline": "draw with words",
    "window": "pictures open in a second window",
    "help_hint": "/help for commands",
    "tip": 'Tip: describe a scene, then build on it: "waterfall", "/add mountains"',
    "placeholder": "describe a picture · /add to build on it",
    "directing": "Working on it… (writing the prompt)",
    "painting": "Working on it… (painting · {source})",
    "looking": "Working on it… (finding a reference picture)",
    "reference": "after a picture from {host}",
    "opening": "Opening the picture window…",
    "add_usage": "Say what to add: /add snowy mountains",
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
    "source.keyless": "pollinations (free)",
    "source.local": "local GPU",
    "pick_hint": "↑↓ to move · Enter to choose · Esc to cancel",
    "pick_style": "How should the picture be drawn?",
    "pick_charset": "Which characters should draw it?",
    "style.ink": "colored symbols on the terminal's background, made for dark themes",
    "style.fill": "also paints each cell's background, so it shows on any theme",
    "charset.classic": "the full ASCII-art alphabet, the finest shading for photos",
    "charset.symbols": "punctuation only, a lighter and sparser look",
    "usage_title": "Usage",
    "usage_scope": "this session",
    "usage_claude": "Claude",
    "usage_pictures": "Pictures",
    "usage_input": "input {tokens} tokens",
    "usage_output": "output {tokens} tokens",
    "usage_searches": "{n} web searches",
    "usage_requests": "{n} requests",
    "usage_painted": "{n} pictures · {seconds}s",
    "usage_referenced": "{n} after a reference picture",
    "usage_unpriced": "{n} requests on a model without a known price are left out",
    "usage_note": "Estimated from list prices; Pollinations bills its own account.",
}

COMMANDS: Sequence[tuple[str, str]] = (
    ("/add <text>", "add to the current picture instead of starting a new one"),
    ("/clear", "clear the screen and start a fresh picture"),
    ("/style [ink|fill]", "choose how the picture is drawn"),
    ("/charset [classic|symbols]", "choose the characters that draw it"),
    ("/usage", "show what this session used: Claude and the image models"),
    ("/help", "show this list"),
    ("/exit", "close sepia and its window (also Ctrl+D)"),
)


class Words:
    """The interface's strings, with values filled in."""

    def __call__(self, key: str, **values: object) -> str:
        return STRINGS[key].format(**values)

    @property
    def commands(self) -> Sequence[tuple[str, str]]:
        return COMMANDS


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


def bar_rule(width: int) -> str:
    """A line above or below the chat bar's input; open ends, as in Claude Code."""
    return "─" * width


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


USAGE_BAR = 40
"""Width of a usage bar in cells, as in Claude Code's /usage."""
EMPTY = "░"
SOURCE_COLORS = {"api": ACCENT, "local": GOOD, "keyless": MUTED}


def usage_view(words: Words, usage: "Usage", model: str, width: int) -> Group:
    """This session's usage as Claude Code shows its own: per service a heading, a
    bar and a legend. Each bar shows what its total is made of."""
    size = max(min(width - 26, USAGE_BAR), 10)
    title = Text.assemble((f" {words('usage_title')}", "bold"))
    title.append(f" · {words('usage_scope')}", style=MUTED)

    claude = [
        (usage.input_cost, ACCENT),
        (usage.output_cost, BANDS[3]),
        (usage.search_cost, BANDS[4]),
    ]
    claude_legend = _legend(
        [
            (words("usage_input", tokens=_count(usage.input_tokens)), ACCENT),
            (words("usage_output", tokens=_count(usage.output_tokens)), BANDS[3]),
            (words("usage_searches", n=usage.searches), BANDS[4]),
        ],
        words("usage_requests", n=usage.requests),
    )
    sources = [
        (source, usage.pictures.get(source, 0))
        for source in ("api", "local", "keyless")
    ]
    pictures_legend = _legend(
        [
            (f"{words(f'source.{source}')} {count}", SOURCE_COLORS[source])
            for source, count in sources
        ],
        words("usage_referenced", n=usage.referenced),
    )
    painted = words(
        "usage_painted",
        n=sum(usage.pictures.values()),
        seconds=f"{usage.paint_seconds:.1f}",
    )
    lines: list[RenderableType] = [
        title,
        Text(""),
        _heading(words("usage_claude"), model.removeprefix("claude-")),
        _bar(claude, size, f"${usage.cost:.4f}"),
        claude_legend,
    ]
    if usage.unpriced:
        lines.append(Text(f" {words('usage_unpriced', n=usage.unpriced)}", MUTED))
    lines += [
        Text(""),
        _heading(words("usage_pictures"), ""),
        _bar(
            [(float(count), SOURCE_COLORS[source]) for source, count in sources],
            size,
            painted,
        ),
        pictures_legend,
        Text(""),
        Text(f" {words('usage_note')}", style="dim"),
    ]
    return Group(*lines)


def _heading(name: str, detail: str) -> Text:
    text = Text.assemble((f" {name}", "bold"))
    if detail:
        text.append(f"  {detail}", style=MUTED)
    return text


def _bar(parts: Sequence[tuple[float, str]], size: int, label: str) -> Text:
    """A bar `size` cells wide, split in proportion to `parts`; empty without any."""
    total = sum(value for value, _ in parts)
    text = Text(" ")
    used = 0
    if total > 0:
        for value, color in parts:
            cells = round(value / total * size)
            cells = min(cells, size - used)
            text.append("█" * cells, style=color)
            used += cells
    text.append(EMPTY * (size - used), style=FRAME)
    text.append(f"  {label}")
    return text


def _legend(items: Sequence[tuple[str, str]], tail: str) -> Text:
    text = Text(" ")
    for label, color in items:
        text.append("■ ", style=color)
        text.append(f"{label}  ", style=MUTED)
    text.append(f"· {tail}", style=MUTED)
    return text


def _count(n: int) -> str:
    """12345 -> 12.3k, the way token counts read best."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.1f}M"
