"""Claude's questions about a vague request, answered in a menu as in Claude Code:
one option, several, or the person's own words.

Like the picker it draws where the transcript's cursor is and erases itself once
done; the prompt window then keeps the answers in the transcript.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import FormattedTextControl, Layout, Window
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth

from sepia import ui
from sepia.director import Answer, Question

BOX = "☐"
"""Marks an unanswered question's tab."""
STYLE = Style.from_dict(
    {
        "question": "bold",
        "chosen": f"bold {ui.ACCENT}",
        "summary": ui.MUTED,
        "mark": ui.ACCENT,
        "hint": ui.MUTED,
        "tab": ui.MUTED,
        "here": f"bold reverse {ui.ACCENT}",
        "cursor": ui.ACCENT,
    }
)


@dataclass(frozen=True)
class Asked:
    """How the menu ended: the answered questions (none when skipped), or
    cancelled."""

    answers: tuple[Answer, ...] = ()
    cancelled: bool = False


@dataclass
class _Page:
    """One question and what has been chosen on it so far."""

    question: Question
    pointer: int = 0
    picked: set[int] = field(default_factory=set)
    other: str = ""

    @property
    def other_row(self) -> int:
        return len(self.question.options)

    @property
    def on_other(self) -> bool:
        return self.pointer == self.other_row

    def choices(self) -> tuple[str, ...]:
        labels = [
            option.label
            for index, option in enumerate(self.question.options)
            if index in self.picked
        ]
        if self.other.strip():
            labels.append(self.other.strip())
        return tuple(labels)

    def answer(self) -> Answer | None:
        choices = self.choices()
        if not choices:
            return None
        return Answer(self.question.header, self.question.text, choices)


def ask(questions: Sequence[Question], words: ui.Words) -> Asked:
    """Ask `questions`; several get a tab each and a Paint page."""
    pages = [_Page(question) for question in questions]
    several = len(pages) > 1
    current = 0
    """A page's index, or len(pages) for the Paint page."""

    def answers() -> tuple[Answer, ...]:
        given = (page.answer() for page in pages)
        return tuple(answer for answer in given if answer is not None)

    def render() -> StyleAndTextTuples:
        width = get_app().output.get_size().columns - 1
        lines: list[StyleAndTextTuples] = []
        if several:
            lines += [tabs(), []]
        if current == len(pages):
            lines += paint_page()
        else:
            lines += question_page(pages[current])
        lines += [[], [("class:hint", f" {hint()}")]]
        drawn: StyleAndTextTuples = []
        for number, line in enumerate(lines):
            if number:
                drawn.append(("", "\n"))
            drawn.extend(_fit(line, width))
        return drawn

    def tabs() -> StyleAndTextTuples:
        line: StyleAndTextTuples = [("", " ")]
        for index, page in enumerate(pages):
            done = page.answer() is not None
            label = f"{ui.CHECK if done else BOX} {page.question.header}"
            style = "class:mark" if done else "class:tab"
            line.append(("class:here" if index == current else style, label))
            line.append(("", "   "))
        here = current == len(pages)
        paint = f"{ui.CHECK} {words('questions_paint')}"
        line.append(("class:here" if here else "class:mark", paint))
        return line

    def question_page(page: _Page) -> list[StyleAndTextTuples]:
        question = page.question
        title: StyleAndTextTuples = [("class:question", f" {question.text}")]
        if question.multi:
            title.append(("class:summary", f" {words('questions_any')}"))
        rows = [title]
        width = max(get_cwidth(option.label) for option in question.options)
        for index, option in enumerate(question.options):
            here = index == page.pointer
            style = "class:chosen" if here else ""
            row: StyleAndTextTuples = [
                (style, f" {ui.POINTER if here else ' '} {index + 1}. ")
            ]
            if question.multi:
                row.append(box(index in page.picked))
            padding = " " * (width - get_cwidth(option.label))
            row.append((style, f"{option.label}{padding}"))
            row.append(("class:summary", f"  {option.description}"))
            if not question.multi and index in page.picked:
                row.append(("class:mark", f" {ui.CHECK}"))
            rows.append(row)
        rows.append(other_row(page))
        return rows

    def other_row(page: _Page) -> StyleAndTextTuples:
        here = page.on_other
        style = "class:chosen" if here else ""
        number = page.other_row + 1
        row: StyleAndTextTuples = [
            (style, f" {ui.POINTER if here else ' '} {number}. ")
        ]
        if page.question.multi:
            row.append(box(bool(page.other.strip())))
        typed = words("questions_other_typed")
        if here:
            row += [(style, typed), ("", page.other), ("class:cursor", ui.BLOCK)]
        elif page.other:
            row.append(("", f"{typed}{page.other}"))
            if not page.question.multi and not page.picked:
                row.append(("class:mark", f" {ui.CHECK}"))
        else:
            row.append(("class:summary", words("questions_other")))
        return row

    def box(checked: bool) -> tuple[str, str]:
        return (
            ("class:mark", f"[{ui.CHECK}] ") if checked else ("class:summary", "[ ] ")
        )

    def paint_page() -> list[StyleAndTextTuples]:
        rows: list[StyleAndTextTuples] = [
            [("class:question", f" {words('questions_ready')}")]
        ]
        width = max(get_cwidth(page.question.header) for page in pages)
        for page in pages:
            header = page.question.header
            padding = " " * (width - get_cwidth(header))
            choices = page.choices()
            value = ("", ", ".join(choices)) if choices else ("class:summary", "—")
            rows.append([("", f"   {header}{padding}  "), value])
        return rows

    def hint() -> str:
        if current == len(pages):
            return words("questions_paint_hint")
        page = pages[current]
        multi = page.question.multi
        parts: list[str] = []
        if page.on_other:
            parts.append(words("questions_type"))
        elif multi:
            parts.append(words("questions_toggle"))
        else:
            parts.append(words("questions_move"))
        if multi:
            parts.append(words("questions_next" if several else "questions_paint_key"))
        else:
            parts.append(words("questions_pick"))
        if several:
            parts.append(words("questions_switch"))
        parts.append(words("questions_skip"))
        return " · ".join(parts)

    def go_on(event: KeyPressEvent) -> None:
        """After a question is answered: the next tab, or finish."""
        nonlocal current
        if several:
            current += 1
        else:
            event.app.exit(result=Asked(answers()))

    def pick(event: KeyPressEvent, page: _Page) -> None:
        """Enter on a question: pick the row (one choice) or go on (several)."""
        if not page.question.multi:
            if page.on_other:
                if not page.other.strip():
                    return
                page.picked.clear()
            else:
                page.picked = {page.pointer}
                page.other = ""
        go_on(event)

    def type_into(page: _Page, text: str) -> None:
        page.other += text
        if not page.question.multi:
            page.picked.clear()

    keys = KeyBindings()

    @keys.add("up")
    def _up(event: KeyPressEvent) -> None:
        if current < len(pages):
            page = pages[current]
            page.pointer = (page.pointer - 1) % (page.other_row + 1)

    @keys.add("down")
    def _down(event: KeyPressEvent) -> None:
        if current < len(pages):
            page = pages[current]
            page.pointer = (page.pointer + 1) % (page.other_row + 1)

    @keys.add("left")
    @keys.add("s-tab")
    def _left(event: KeyPressEvent) -> None:
        nonlocal current
        if several:
            current = (current - 1) % (len(pages) + 1)

    @keys.add("right")
    @keys.add("tab")
    def _right(event: KeyPressEvent) -> None:
        nonlocal current
        if several:
            current = (current + 1) % (len(pages) + 1)

    @keys.add("enter")
    def _enter(event: KeyPressEvent) -> None:
        if current == len(pages):
            event.app.exit(result=Asked(answers()))
        else:
            pick(event, pages[current])

    @keys.add("space")
    def _space(event: KeyPressEvent) -> None:
        if current == len(pages):
            return
        page = pages[current]
        if page.on_other:
            type_into(page, " ")
        elif page.question.multi:
            page.picked ^= {page.pointer}
        else:
            pick(event, page)

    @keys.add("backspace")
    def _backspace(event: KeyPressEvent) -> None:
        if current < len(pages) and pages[current].on_other:
            pages[current].other = pages[current].other[:-1]

    @keys.add(Keys.Any)
    def _type(event: KeyPressEvent) -> None:
        if current == len(pages) or not event.data.isprintable():
            return
        page = pages[current]
        if page.on_other:
            type_into(page, event.data)
        elif event.data.isdigit() and event.data != "0":
            row = int(event.data) - 1
            if row == page.other_row:
                page.pointer = row
            elif row < page.other_row:
                page.pointer = row
                if page.question.multi:
                    page.picked ^= {row}
                else:
                    pick(event, page)

    @keys.add("escape", eager=True)
    def _skip(event: KeyPressEvent) -> None:
        event.app.exit(result=Asked())

    @keys.add("c-c")
    def _cancel(event: KeyPressEvent) -> None:
        event.app.exit(result=Asked(cancelled=True))

    menu = Window(
        FormattedTextControl(render, show_cursor=False), dont_extend_height=True
    )
    app: Application[Asked] = Application(
        layout=Layout(menu),
        key_bindings=keys,
        style=STYLE,
        full_screen=False,
        erase_when_done=True,
        mouse_support=False,
    )
    asked: Asked = app.run()
    return asked


def _fit(line: StyleAndTextTuples, width: int) -> StyleAndTextTuples:
    """`line` cut to `width` columns, ending in … when anything was cut, so no
    line of the menu wraps."""
    if sum(get_cwidth(fragment[1]) for fragment in line) <= width:
        return line
    room = width - 1
    kept: StyleAndTextTuples = []
    for fragment in line:
        style, text = fragment[0], fragment[1]
        part = ""
        for char in text:
            if get_cwidth(char) > room:
                break
            part += char
            room -= get_cwidth(char)
        if part:
            kept.append((style, part))
        if len(part) < len(text):
            break
    kept.append(("class:summary", "…"))
    return kept
