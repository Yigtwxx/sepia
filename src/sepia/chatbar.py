"""The chat bar: an input line between two rules, pinned to the bottom rows.

`ChatBar` draws the whole bar as one block: top rule, the input, bottom rule and a
status line. (A `PromptSession` puts its bottom toolbar on the screen's last row,
which split the block in two.)

`BottomBar` keeps that block on the window's last rows. A terminal scroll region
covers every row above it, so the transcript starts under the welcome box and, once
it reaches the bar, scrolls the welcome box out of view while the bar never moves.
Typing "/" opens a menu of the matching commands on rows the bar borrows above it.
"""

import io
import shutil
from collections.abc import Callable, Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app_session
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Size
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import (
    FormattedText,
    StyleAndTextTuples,
    fragment_list_width,
)
from prompt_toolkit.history import History
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    ConditionalContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.processors import (
    AfterInput,
    BeforeInput,
    ConditionalProcessor,
)
from prompt_toolkit.output.vt100 import Vt100_Output
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.styles import Style

from sepia import ui

BAR_ROWS = 4
"""Top rule, input line, bottom rule, status line."""
REFRESH_SECONDS = 0.5
"""How often the bar redraws on its own: the status line follows the picture window
and the Ctrl+C hint, and a resized window is noticed."""

STYLE = Style.from_dict(
    {
        "frame": ui.FRAME,
        "prompt": f"bold {ui.ACCENT}",
        "placeholder": ui.MUTED,
        "status": ui.MUTED,
        # Not "menu": prompt_toolkit's own style gives that class a grey background.
        "commands.chosen": f"bold {ui.ACCENT}",
        "commands.chosen-summary": ui.ACCENT,
    }
)


class BottomBar:
    """Keeps the chat bar on the bottom rows while the transcript scrolls above it."""

    SAVE, RESTORE, RESET = "\x1b7", "\x1b8", "\x1b[r"

    def __init__(self, write: Callable[[str], None], rows: Callable[[], int]) -> None:
        self._write = write
        self._rows = rows
        self._extra = 0
        """Rows above the bar lent to the command menu."""

    def start(self) -> None:
        """Set the region; this also homes the cursor, where the transcript begins."""
        self._write(self._region())

    def to_bar(self) -> None:
        """Remember the transcript position and move to the bar's first row."""
        # Re-applying the region follows window resizes; it homes the cursor, so
        # the transcript position is saved first and put back afterwards.
        self._write(self.SAVE + self._region() + self.RESTORE + self.SAVE)
        self._write(f"\x1b[{self._top()};1H")

    def hold(self, rows: Sequence[str]) -> None:
        """Draw a still copy of the bar on its rows, one finished row at a time."""
        top = self._top()
        for offset, row in enumerate(rows):
            self._write(f"\x1b[{top + offset};1H\x1b[2K{row}")

    def to_transcript(self) -> None:
        self._write(self.RESTORE)

    def stop(self) -> None:
        """Give the whole screen back and clear the bar, leaving the cursor there."""
        self._write(f"{self.RESET}\x1b[{self._top()};1H\x1b[J")

    def make_room(self, rows: int) -> int:
        """Lend `rows` rows above the bar to the command menu, or take them back
        with 0, and leave the cursor on the bar's new first row, cleared to the
        bottom. Returns the rows lent; the transcript always keeps one.

        The transcript scrolls only as far as it reaches into the lent rows: line
        feeds from its end move down through empty rows and scroll once they meet
        the region's bottom. Its end is then saved again where it now is.
        """
        rows = max(0, min(rows, self._rows() - BAR_ROWS - 1))
        before = self._top()
        if rows > self._extra:
            more = rows - self._extra
            self._write(self.RESTORE + "\n" * more + f"\x1b[{more}A" + self.SAVE)
        self._extra = rows
        # Setting the region homes the cursor; clear from whichever top is higher.
        top = self._top()
        self._write(f"{self._region()}\x1b[{min(before, top)};1H\x1b[J\x1b[{top};1H")
        return rows

    def _top(self) -> int:
        return max(self._rows() - BAR_ROWS - self._extra + 1, 1)

    def _region(self) -> str:
        return f"\x1b[1;{max(self._rows() - BAR_ROWS - self._extra, 1)}r"


class Resized(Exception):
    """The window changed size while the bar was reading; `draft` is what was typed.

    The terminal reflows the lines above the bar to the new width, which breaks
    boxes and rules apart, so the prompt window draws itself anew and reads again.
    """

    def __init__(self, draft: str) -> None:
        super().__init__(draft)
        self.draft = draft


class CommandMenu:
    """The slash commands that start with what is typed, listed above the bar.

    It opens on "/" and closes at the first space: ↑↓ move the highlight, Tab
    completes the highlighted command and Enter runs it.
    """

    def __init__(self, commands: Sequence[tuple[str, str]]) -> None:
        self._commands = [(usage.split()[0], summary) for usage, summary in commands]
        self.chosen = 0
        """Index of the highlighted match."""

    def matches(self, text: str) -> list[tuple[str, str]]:
        """Name and summary of each command `text` is the start of."""
        if not text.startswith("/") or " " in text:
            return []
        return [command for command in self._commands if command[0].startswith(text)]

    def choice(self, text: str) -> str | None:
        """The highlighted command's name; None when nothing matches."""
        found = self.matches(text)
        return found[min(self.chosen, len(found) - 1)][0] if found else None

    def move(self, text: str, step: int) -> None:
        count = len(self.matches(text))
        if count:
            self.chosen = (self.chosen + step) % count

    def lines(self, text: str, rows: int) -> StyleAndTextTuples:
        """The menu on `rows` rows: the matches nearest the bar, scrolled to keep
        the highlight in view, under blank rows when fewer match."""
        found = self.matches(text)
        start = max(0, min(self.chosen - rows + 1, len(found) - rows))
        shown = found[start : start + rows]
        column = max((len(name) for name, _ in found), default=0)
        fragments: StyleAndTextTuples = [("", "\n" * (rows - len(shown)))]
        for index, (name, summary) in enumerate(shown, start):
            # The highlighted command in the accent color, the rest in plain text.
            chosen = index == self.chosen
            pointer = ui.POINTER if chosen else " "
            name_style = "class:commands.chosen" if chosen else ""
            summary_style = "class:commands.chosen-summary" if chosen else ""
            fragments.append((name_style, f" {pointer} {name:<{column}}"))
            fragments.append((summary_style, f"  {summary}"))
            if index < start + len(shown) - 1:
                fragments.append(("", "\n"))
        return fragments


class ChatBar:
    """Reads one line at a time inside the framed box."""

    def __init__(
        self,
        history: History,
        commands: Sequence[tuple[str, str]],
        placeholder: str,
        status: Callable[[], str],
        make_room: Callable[[int], int] = lambda rows: rows,
    ) -> None:
        self._history = history
        self._menu = CommandMenu(commands)
        self._placeholder = placeholder
        self._status = status
        self._make_room = make_room
        """Asks for rows above the bar for the menu: `BottomBar.make_room`."""
        self._menu_rows = 0

    def read(self, draft: str = "") -> str:
        """The submitted line, typed after `draft`. Raises KeyboardInterrupt on
        Ctrl+C and EOFError on Ctrl+D in an empty bar, like `input()`, and Resized
        when the window changes size."""
        try:
            result: str = self._application(draft).run()
        finally:
            if self._menu_rows:
                self._menu_rows = self._make_room(0)
        return result

    def still(self, width: int) -> list[str]:
        """The empty bar as rows of text with escape codes, `width` columns wide.

        The live bar erases itself when a line is submitted; drawing this copy in
        its place keeps the bar on screen while sepia works on the request.
        """
        room = max(width - len(ui.PROMPT), 0)
        rows: list[StyleAndTextTuples] = [
            [("class:frame", ui.bar_rule(width))],
            [
                ("class:prompt", ui.PROMPT),
                ("class:placeholder", self._placeholder[:room]),
            ],
            [("class:frame", ui.bar_rule(width))],
            [("class:status", self._status()[:width])],
        ]
        return [_escaped(row) for row in rows]

    def _application(self, draft: str) -> Application[str]:
        buffer = Buffer(
            history=self._history,
            multiline=False,
            document=Document(draft),
            accept_handler=lambda buf: _accept(buf),
        )
        empty = Condition(lambda: not buffer.text)
        field = Window(
            BufferControl(
                buffer,
                input_processors=[
                    BeforeInput(ui.PROMPT, style="class:prompt"),
                    ConditionalProcessor(
                        AfterInput(self._placeholder, style="class:placeholder"),
                        empty,
                    ),
                ],
            ),
            height=1,
            dont_extend_height=True,
        )
        menu = ConditionalContainer(
            Window(
                FormattedTextControl(
                    lambda: self._menu.lines(buffer.text, self._menu_rows)
                ),
                height=lambda: self._menu_rows,
                dont_extend_height=True,
            ),
            filter=Condition(lambda: self._menu_rows > 0),
        )
        body = HSplit(
            [
                menu,
                _line(ui.bar_rule, "class:frame"),
                field,
                _line(ui.bar_rule, "class:frame"),
                _line(lambda _: self._status(), "class:status"),
            ]
        )
        submitted = False

        def _fit_menu(buf: Buffer) -> None:
            # The bar grows upward: it is erased, given rows above it and redrawn
            # from its new first row.
            self._menu.chosen = 0
            wanted = len(self._menu.matches(buf.text))
            if submitted or wanted == self._menu_rows:
                return
            app.renderer.erase()
            self._menu_rows = self._make_room(wanted)
            app.invalidate()

        buffer.on_text_changed += _fit_menu

        def _accept(buf: Buffer) -> bool:
            # Enter on a partial command runs the highlighted one: /us -> /usage.
            nonlocal submitted
            submitted = True
            choice = self._menu.choice(buf.text)
            if choice is not None:
                buf.text = choice
            app.exit(result=buf.text)
            return True  # keep the text out of the buffer reset; history still saves

        keys = KeyBindings()
        choosing = Condition(lambda: len(self._menu.matches(buffer.text)) > 1)

        @keys.add("up", filter=choosing)
        def _up(event: KeyPressEvent) -> None:
            self._menu.move(buffer.text, -1)

        @keys.add("down", filter=choosing)
        def _down(event: KeyPressEvent) -> None:
            self._menu.move(buffer.text, 1)

        @keys.add("c-c")
        def _interrupt(event: KeyPressEvent) -> None:
            event.app.exit(exception=KeyboardInterrupt())

        @keys.add("c-d", filter=empty)
        def _end(event: KeyPressEvent) -> None:
            event.app.exit(exception=EOFError())

        @keys.add("tab")
        def _complete(event: KeyPressEvent) -> None:
            choice = self._menu.choice(buffer.text)
            if choice is not None:
                buffer.document = Document(choice)

        size = get_app_session().output.get_size()

        def _resized(app: Application[str]) -> None:
            if not app.is_done and app.output.get_size() != size:
                app.exit(exception=Resized(buffer.text))

        app: Application[str] = Application(
            layout=Layout(body, focused_element=field),
            key_bindings=keys,
            style=STYLE,
            full_screen=False,
            erase_when_done=True,
            mouse_support=False,
            refresh_interval=REFRESH_SECONDS,
            before_render=_resized,
        )
        return app


def _line(text: Callable[[int], str], style: str) -> Window:
    """A one-row window whose text is rebuilt for the current width on every draw."""

    def render() -> FormattedText:
        return FormattedText([(style, text(shutil.get_terminal_size().columns))])

    return Window(FormattedTextControl(render), height=1, dont_extend_height=True)


def _escaped(fragments: StyleAndTextTuples) -> str:
    """Styled fragments as text with escape codes, in the live bar's colors."""
    text = io.StringIO()
    width = fragment_list_width(fragments)
    print_formatted_text(
        FormattedText(fragments),
        end="",
        style=STYLE,
        output=Vt100_Output(text, lambda: Size(rows=1, columns=width)),
        color_depth=get_app_session().output.get_default_color_depth(),
    )
    return text.getvalue()
