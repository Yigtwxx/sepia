"""Look and words of the prompt window: wordmark, palette, replies, strings."""

from collections.abc import Sequence

from rich.console import Group, RenderableType
from rich.panel import Panel
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
}

COMMANDS: Sequence[tuple[str, str]] = (
    ("/new", "start a fresh picture"),
    ("/clear", "clear the screen and start a fresh picture"),
    ("/style [ink|fill]", "switch how the picture is drawn"),
    ("/charset [classic|symbols]", "switch the character set"),
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


def bar_top(width: int) -> str:
    return "╭" + "─" * max(width - 2, 0) + "╮"


def bar_bottom(width: int) -> str:
    return "╰" + "─" * max(width - 2, 0) + "╯"


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
