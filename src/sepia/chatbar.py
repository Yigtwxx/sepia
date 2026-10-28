"""The chat bar: an input line between two rules, pinned to the bottom rows.

`ChatBar` draws the whole bar as one block: top rule, the input, bottom rule and a
status line. (A `PromptSession` puts its bottom toolbar on the screen's last row,
which split the block in two.)

`BottomBar` keeps that block on the window's last rows. A terminal scroll region
covers every row above it, so the transcript starts under the welcome box and, once
it reaches the bar, scrolls the welcome box out of view while the bar never moves.
"""

import io
import shutil
from collections.abc import Callable, Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app_session
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
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
from prompt_toolkit.layout import FormattedTextControl, HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.processors import (
    AfterInput,
    AppendAutoSuggestion,
    BeforeInput,
    ConditionalProcessor,
)
from prompt_toolkit.output.vt100 import Vt100_Output
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.styles import Style

from sepia import ui

BAR_ROWS = 4
"""Top rule, input line, bottom rule, status line."""

STYLE = Style.from_dict(
    {
        "frame": ui.FRAME,
        "prompt": f"bold {ui.ACCENT}",
        "placeholder": ui.MUTED,
        "auto-suggestion": ui.MUTED,
        "status": ui.MUTED,
    }
)


class BottomBar:
    """Keeps the chat bar on the bottom rows while the transcript scrolls above it."""

    SAVE, RESTORE, RESET = "\x1b7", "\x1b8", "\x1b[r"

    def __init__(self, write: Callable[[str], None], rows: Callable[[], int]) -> None:
        self._write = write
        self._rows = rows

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

    def _top(self) -> int:
        return max(self._rows() - BAR_ROWS + 1, 1)

    def _region(self) -> str:
        return f"\x1b[1;{max(self._rows() - BAR_ROWS, 1)}r"


class CommandSuggest(AutoSuggest):
    """Completes a slash command in grey as it is typed; Tab or → accepts it.

    An inline hint instead of a menu, because the bar sits on the last rows and a
    menu below it would fall off the screen.
    """

    def __init__(self, names: Sequence[str]) -> None:
        self._names = names

    def get_suggestion(self, buffer: Buffer, document: Document) -> Suggestion | None:
        text = document.text
        if not text.startswith("/") or " " in text:
            return None
        for name in self._names:
            if name.startswith(text) and name != text:
                return Suggestion(name[len(text) :])
        return None


class ChatBar:
    """Reads one line at a time inside the framed box."""

    def __init__(
        self,
        history: History,
        commands: Sequence[tuple[str, str]],
        placeholder: str,
        status: Callable[[], str],
    ) -> None:
        self._history = history
        self._suggest = CommandSuggest([usage.split()[0] for usage, _ in commands])
        self._placeholder = placeholder
        self._status = status

    def read(self) -> str:
        """The submitted line. Raises KeyboardInterrupt on Ctrl+C and EOFError on
        Ctrl+D in an empty bar, like `input()`."""
        result: str = self._application().run()
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

    def _application(self) -> Application[str]:
        buffer = Buffer(
            history=self._history,
            auto_suggest=self._suggest,
            multiline=False,
            accept_handler=lambda buf: _accept(buf),
        )
        empty = Condition(lambda: not buffer.text)
        field = Window(
            BufferControl(
                buffer,
                input_processors=[
                    BeforeInput(ui.PROMPT, style="class:prompt"),
                    AppendAutoSuggestion(),
                    ConditionalProcessor(
                        AfterInput(self._placeholder, style="class:placeholder"),
                        empty,
                    ),
                ],
            ),
            height=1,
            dont_extend_height=True,
        )
        body = HSplit(
            [
                _line(ui.bar_rule, "class:frame"),
                field,
                _line(ui.bar_rule, "class:frame"),
                _line(lambda _: self._status(), "class:status"),
            ]
        )

        def _accept(buf: Buffer) -> bool:
            # Enter on a partial command runs the one suggested for it: /us -> /usage.
            suggestion = self._suggest.get_suggestion(buf, buf.document)
            if suggestion is not None:
                buf.text += suggestion.text
            app.exit(result=buf.text)
            return True  # keep the text out of the buffer reset; history still saves

        keys = KeyBindings()

        @keys.add("c-c")
        def _interrupt(event: KeyPressEvent) -> None:
            event.app.exit(exception=KeyboardInterrupt())

        @keys.add("c-d", filter=empty)
        def _end(event: KeyPressEvent) -> None:
            event.app.exit(exception=EOFError())

        @keys.add("tab")
        def _complete(event: KeyPressEvent) -> None:
            # Computed here rather than read from buffer.suggestion, which is
            # filled in the background and can lag behind fast typing.
            current = event.current_buffer
            suggestion = self._suggest.get_suggestion(current, current.document)
            if suggestion is not None:
                current.insert_text(suggestion.text)

        app: Application[str] = Application(
            layout=Layout(body, focused_element=field),
            key_bindings=keys,
            style=STYLE,
            full_screen=False,
            erase_when_done=True,
            mouse_support=False,
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
