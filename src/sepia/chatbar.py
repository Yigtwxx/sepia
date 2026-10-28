"""The chat bar: a framed input box drawn as one block, like Claude Code's.

A `PromptSession` puts its bottom toolbar on the last row of the screen, which split
the frame in two. A small inline application instead draws the whole bar where the
cursor is: top border, the input line between side borders, bottom border and a
status line. It is erased when the line is submitted, so the transcript can take its
place and the next bar is drawn below.
"""

import shutil
from collections.abc import Callable, Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.filters import Condition, has_completions
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import History
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    ConditionalContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import (
    AfterInput,
    BeforeInput,
    ConditionalProcessor,
)
from prompt_toolkit.styles import Style

from sepia import ui

STYLE = Style.from_dict(
    {
        "frame": ui.FRAME,
        "prompt": f"bold {ui.ACCENT}",
        "placeholder": ui.MUTED,
        "status": ui.MUTED,
    }
)


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
        self._completer = WordCompleter(
            [usage.split()[0] for usage, _ in commands],
            meta_dict={usage.split()[0]: text for usage, text in commands},
            sentence=True,
        )
        self._placeholder = placeholder
        self._status = status

    def read(self) -> str:
        """The submitted line. Raises KeyboardInterrupt on Ctrl+C and EOFError on
        Ctrl+D in an empty bar, like `input()`."""
        result: str = self._application().run()
        return result

    def _application(self) -> Application[str]:
        buffer = Buffer(
            history=self._history,
            completer=self._completer,
            complete_while_typing=True,
            multiline=False,
            accept_handler=lambda buf: _accept(buf.text),
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
        side = Window(FormattedTextControl([("class:frame", "│")]), width=1)
        body = HSplit(
            [
                _line(lambda w: ui.bar_top(w), "class:frame"),
                VSplit([side, field, side]),
                _line(lambda w: ui.bar_bottom(w), "class:frame"),
                _line(lambda _: self._status(), "class:status"),
                ConditionalContainer(
                    CompletionsMenu(max_height=6, scroll_offset=1), has_completions
                ),
            ]
        )

        def _accept(text: str) -> bool:
            app.exit(result=text)
            return True  # keep the text out of the buffer reset; history still saves

        keys = KeyBindings()

        @keys.add("c-c")
        def _interrupt(event: KeyPressEvent) -> None:
            event.app.exit(exception=KeyboardInterrupt())

        @keys.add("c-d", filter=empty)
        def _end(event: KeyPressEvent) -> None:
            event.app.exit(exception=EOFError())

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
