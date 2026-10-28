"""Look and words of the prompt window: wordmark, palette, replies, strings."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sepia import __version__

if TYPE_CHECKING:
    from sepia.usage import AllTime, Earlier, Usage

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
    "effort_set": "Effort: {effort}, from the next picture on",
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
    "pick_effort": "How long should Claude think about each picture?",
    "style.ink": "colored symbols on the terminal's background, made for dark themes",
    "style.fill": "also paints each cell's background, so it shows on any theme",
    "charset.classic": "the full ASCII-art alphabet, the finest shading for photos",
    "charset.symbols": "punctuation only, a lighter and sparser look",
    "effort.low": "the quickest reply and the most literal idea",
    "effort.medium": "a little more thought",
    "effort.high": "time to find an idea for the picture (the default)",
    "effort.xhigh": "longer thought, a slower reply",
    "effort.max": "as much thought as Claude wants: the slowest and costliest",
    "usage_title": "Usage",
    "usage_session": "this session",
    "usage_all_time": "all time · since {since}",
    "usage_claude": "Claude",
    "usage_pictures": "Pictures",
    "usage_input": "input {tokens} tokens",
    "usage_output": "output {tokens} tokens",
    "usage_searches": "{n} web searches",
    "usage_requests": "{n} requests",
    "usage_painted": "{n} pictures · {seconds}s",
    "usage_count": "{n} pictures",
    "usage_referenced": "{n} after a reference picture",
    "usage_earlier_claude": "before tracking: about {n} requests, ${cost}"
    " (estimated from your prompt history)",
    "usage_earlier_pictures": "before tracking: about {n} pictures"
    " (estimated from your saved sessions and prompt history)",
    "usage_unpriced": "{n} requests on a model without a known price are left out",
    "usage_scale": "Session bars are drawn against all time; "
    "their gray rest is earlier use.",
    "usage_note": "Estimated from list prices; Pollinations bills its own account.",
}

COMMANDS: Sequence[tuple[str, str]] = (
    ("/add <text>", "add to the current picture instead of starting a new one"),
    ("/clear", "clear the screen and start a fresh picture"),
    ("/style [ink|fill]", "choose how the picture is drawn"),
    ("/charset [classic|symbols]", "choose the characters that draw it"),
    ("/effort [low|medium|high|xhigh|max]", "choose how long Claude thinks"),
    ("/usage", "show what Claude and the image models used, now and in all"),
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
TRACK = "#3a3a46"
"""The empty part of a usage bar: a gray track, so the bar's whole length shows."""
EARLIER = BANDS[0]
"""What was used before tracking began, in the all-time bars."""
DEEP = "#7c3aed"
"""A third part of a bar, darker than the other two so the three stay apart."""
SOURCES = ("api", "local", "keyless")
SOURCE_COLORS = {"api": ACCENT, "local": GOOD, "keyless": DEEP}


def usage_view(
    words: Words, session: "Usage", all_time: "AllTime", model: str, width: int
) -> Group:
    """Usage laid out like Claude Code's /usage: this session, then all time, each
    service with a heading, a bar and a legend. A bar's colors show what its total
    is made of. The session bars are drawn against the all-time totals, so their
    gray rest is earlier use."""
    size = max(min(width - 26, USAGE_BAR), 10)
    total, earlier = all_time.total, all_time.earlier
    pictures = sum(total.pictures.values()) + earlier.pictures
    since = words("usage_all_time", since=f"{all_time.since:%d %b %Y}")
    lines: list[RenderableType] = [
        _title(words, words("usage_session")),
        Text(""),
        *_claude_lines(words, session, size, model, whole=total.cost + earlier.cost),
        Text(""),
        *_picture_lines(words, session, size, whole=float(pictures)),
        Text(""),
        _title(words, since),
        Text(""),
        *_claude_lines(words, total, size, "", earlier=earlier),
        Text(""),
        *_picture_lines(words, total, size, earlier=earlier),
        Text(""),
        Text(f" {words('usage_scale')}", style="dim"),
        Text(f" {words('usage_note')}", style="dim"),
    ]
    return Group(*lines)


def _claude_lines(
    words: Words,
    usage: "Usage",
    size: int,
    model: str,
    *,
    whole: float | None = None,
    earlier: "Earlier | None" = None,
) -> list[RenderableType]:
    parts = [
        (usage.input_cost, ACCENT),
        (usage.output_cost, BANDS[3]),
        (usage.search_cost, DEEP),
    ]
    items = [
        (words("usage_input", tokens=_count(usage.input_tokens)), ACCENT),
        (words("usage_output", tokens=_count(usage.output_tokens)), BANDS[3]),
        (words("usage_searches", n=usage.searches), DEEP),
    ]
    requests, cost = usage.requests, usage.cost
    notes: list[RenderableType] = []
    if earlier is not None and earlier.requests:
        parts.append((earlier.cost, EARLIER))
        requests += earlier.requests
        cost += earlier.cost
        label = words(
            "usage_earlier_claude", n=earlier.requests, cost=f"{earlier.cost:.4f}"
        )
        notes.append(_note(label, EARLIER))
    if usage.unpriced:
        notes.append(Text(f" {words('usage_unpriced', n=usage.unpriced)}", MUTED))
    return [
        _heading(words("usage_claude"), model.removeprefix("claude-")),
        _bar(parts, size, f"${cost:.4f}", whole),
        _legend(items, words("usage_requests", n=requests)),
        *notes,
    ]


def _picture_lines(
    words: Words,
    usage: "Usage",
    size: int,
    *,
    whole: float | None = None,
    earlier: "Earlier | None" = None,
) -> list[RenderableType]:
    counts = [(source, usage.pictures.get(source, 0)) for source in SOURCES]
    parts = [(float(count), SOURCE_COLORS[source]) for source, count in counts]
    items = [
        (f"{words(f'source.{source}')} {count}", SOURCE_COLORS[source])
        for source, count in counts
    ]
    painted = sum(usage.pictures.values())
    notes: list[RenderableType] = []
    if earlier is None:
        seconds = f"{usage.paint_seconds:.1f}"
        label = words("usage_painted", n=painted, seconds=seconds)
    else:
        if earlier.pictures:
            parts.append((float(earlier.pictures), EARLIER))
            painted += earlier.pictures
            note = words("usage_earlier_pictures", n=earlier.pictures)
            notes.append(_note(note, EARLIER))
        label = words("usage_count", n=painted)
    return [
        _heading(words("usage_pictures"), ""),
        _bar(parts, size, label, whole),
        _legend(items, words("usage_referenced", n=usage.referenced)),
        *notes,
    ]


def _title(words: Words, scope: str) -> Text:
    title = Text.assemble((f" {words('usage_title')}", "bold"))
    title.append(f" · {scope}", style=MUTED)
    return title


def _heading(name: str, detail: str) -> Text:
    text = Text.assemble((f" {name}", "bold"))
    if detail:
        text.append(f"  {detail}", style=MUTED)
    return text


def _bar(
    parts: Sequence[tuple[float, str]],
    size: int,
    label: str,
    whole: float | None = None,
) -> Text:
    """A bar `size` cells wide on a gray track. The parts' total, measured against
    `whole`, sets how much of it is colored (all of it by default), and each part
    takes its share of that; any use at all shows at least one cell."""
    total = sum(value for value, _ in parts)
    whole = total if whole is None else max(whole, total)
    filled = 0
    if total > 0:
        filled = min(size, max(1, round(total / whole * size)))
    text = Text(" ")
    edge = 0.0
    drawn = 0
    for value, color in parts:
        edge += value
        # Rounding the running edge, not each part, keeps the cells adding up.
        end = round(edge / total * filled) if total > 0 else 0
        text.append(BLOCK * (end - drawn), style=color)
        drawn = end
    text.append(BLOCK * (size - drawn), style=TRACK)
    text.append(f"  {label}")
    return text


def _legend(items: Sequence[tuple[str, str]], tail: str) -> Text:
    text = Text(" ")
    for label, color in items:
        text.append("■ ", style=color)
        text.append(f"{label}  ", style=MUTED)
    text.append(f"· {tail}", style=MUTED)
    return text


def _note(label: str, color: str) -> Text:
    return Text.assemble(" ", ("■ ", color), (label, MUTED))


def _count(n: int) -> str:
    """12345 -> 12.3k, the way token counts read best."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.1f}M"
