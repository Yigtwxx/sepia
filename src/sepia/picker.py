"""A small menu for picking one option with the arrow keys, a list of on/off settings,
and a panel to read and close, as in Claude Code.

Both draw where the transcript's cursor is and erase themselves once done, so only
the reply that follows stays in the transcript.
"""

from collections.abc import Callable, Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI, StyleAndTextTuples, to_formatted_text
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import FormattedTextControl, Layout, Window
from prompt_toolkit.styles import Style

from sepia import ui

STYLE = Style.from_dict(
    {
        "title": "bold",
        "chosen": f"bold {ui.ACCENT}",
        "summary": ui.MUTED,
        "current": ui.ACCENT,
        "on": f"bold {ui.ACCENT}",
        "off": ui.MUTED,
        "hint": ui.MUTED,
    }
)


def choose(
    title: str, options: Sequence[tuple[str, str]], current: str, hint: str
) -> str | None:
    """The value picked from `options` (value, summary pairs), or None on Esc or
    Ctrl+C. The pointer starts on `current`; ↑ and ↓ move it, Enter picks, and an
    option's number picks it at once."""
    values = [value for value, _ in options]
    index = values.index(current) if current in values else 0
    width = max(len(value) for value in values)

    def render() -> StyleAndTextTuples:
        lines: StyleAndTextTuples = [("class:title", f" {title}\n")]
        for number, (value, summary) in enumerate(options, 1):
            here = number - 1 == index
            pointer = ui.POINTER if here else " "
            label = f" {pointer} {number}. {value.ljust(width)}"
            lines.append(("class:chosen" if here else "", label))
            lines.append(("class:summary", f"  {summary}"))
            if value == current:
                lines.append(("class:current", f" {ui.CHECK}"))
            lines.append(("", "\n"))
        lines.append(("class:hint", f" {hint}"))
        return lines

    keys = KeyBindings()

    @keys.add("up")
    def _up(event: KeyPressEvent) -> None:
        nonlocal index
        index = (index - 1) % len(values)

    @keys.add("down")
    def _down(event: KeyPressEvent) -> None:
        nonlocal index
        index = (index + 1) % len(values)

    @keys.add("enter")
    def _pick(event: KeyPressEvent) -> None:
        event.app.exit(result=values[index])

    @keys.add("escape", eager=True)
    @keys.add("c-c")
    def _cancel(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    for number, value in enumerate(values[:9], 1):
        keys.add(str(number))(_picker_for(value))

    menu = Window(
        FormattedTextControl(render, show_cursor=False), dont_extend_height=True
    )
    app: Application[str | None] = Application(
        layout=Layout(menu),
        key_bindings=keys,
        style=STYLE,
        full_screen=False,
        erase_when_done=True,
        mouse_support=False,
    )
    picked: str | None = app.run()
    return picked


def toggles(
    title: str, rows: Sequence[tuple[str, str, str, bool]], hint: str
) -> dict[str, bool]:
    """The values of `rows` (key, label, summary, value) once the list closes.
    ↑ and ↓ move; Enter, Space or a row's number flips its value at once; Esc, q
    or Ctrl+C close the list."""
    values = {key: value for key, _, _, value in rows}
    keys_in_order = [key for key, _, _, _ in rows]
    width = max(len(label) for _, label, _, _ in rows)
    index = 0

    def render() -> StyleAndTextTuples:
        lines: StyleAndTextTuples = [("class:title", f" {title}\n")]
        for number, (key, label, summary, _) in enumerate(rows, 1):
            here = number - 1 == index
            pointer = ui.POINTER if here else " "
            on = values[key]
            lines.append(
                ("class:chosen" if here else "", f" {pointer} {label.ljust(width)}")
            )
            lines.append(
                ("class:on" if on else "class:off", "   on " if on else "   off")
            )
            lines.append(("class:summary", f"  {summary}"))
            lines.append(("", "\n"))
        lines.append(("", "\n"))
        lines.append(("class:hint", f" {hint}"))
        return lines

    keys = KeyBindings()

    @keys.add("up")
    def _up(event: KeyPressEvent) -> None:
        nonlocal index
        index = (index - 1) % len(rows)

    @keys.add("down")
    def _down(event: KeyPressEvent) -> None:
        nonlocal index
        index = (index + 1) % len(rows)

    @keys.add("enter")
    @keys.add("space")
    def _flip(event: KeyPressEvent) -> None:
        key = keys_in_order[index]
        values[key] = not values[key]

    @keys.add("escape", eager=True)
    @keys.add("q")
    @keys.add("c-c")
    def _close(event: KeyPressEvent) -> None:
        event.app.exit(result=dict(values))

    for number in range(1, min(len(rows), 9) + 1):
        keys.add(str(number))(_flipper_for(number - 1, keys_in_order, values))

    menu = Window(
        FormattedTextControl(render, show_cursor=False), dont_extend_height=True
    )
    app: Application[dict[str, bool]] = Application(
        layout=Layout(menu),
        key_bindings=keys,
        style=STYLE,
        full_screen=False,
        erase_when_done=True,
        mouse_support=False,
    )
    closed: dict[str, bool] = app.run()
    return closed


def show(panel: str, hint: str) -> None:
    """Show `panel` (text with ANSI colors) with `hint` under it until Esc, Enter,
    q or Ctrl+C closes it; then it leaves the screen."""
    body: StyleAndTextTuples = [
        *to_formatted_text(ANSI(panel)),
        ("", "\n\n"),
        ("class:hint", f" {hint}"),
    ]
    keys = KeyBindings()

    @keys.add("escape", eager=True)
    @keys.add("enter")
    @keys.add("q")
    @keys.add("c-c")
    def _close(event: KeyPressEvent) -> None:
        event.app.exit()

    window = Window(
        FormattedTextControl(body, show_cursor=False), dont_extend_height=True
    )
    app: Application[None] = Application(
        layout=Layout(window),
        key_bindings=keys,
        style=STYLE,
        full_screen=False,
        erase_when_done=True,
        mouse_support=False,
    )
    app.run()


def _picker_for(value: str) -> Callable[[KeyPressEvent], None]:
    def pick(event: KeyPressEvent) -> None:
        event.app.exit(result=value)

    return pick


def _flipper_for(
    row: int, keys_in_order: list[str], values: dict[str, bool]
) -> Callable[[KeyPressEvent], None]:
    def flip(event: KeyPressEvent) -> None:
        values[keys_in_order[row]] = not values[keys_in_order[row]]

    return flip
