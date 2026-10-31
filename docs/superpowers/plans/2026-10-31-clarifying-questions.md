# Clarifying Questions and /config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a request is open-ended, Claude asks one to three questions (one option, several, or the person's own words) before painting; `/config` lists the on/off settings.

**Architecture:** The director's JSON reply gains a `questions` field while the setting is on; the prompt window shows them in a new inline prompt_toolkit menu (`questions.py`) and asks Claude again with the answers. `/config` is a toggle list in `picker.py`. The spec is `docs/superpowers/specs/2026-10-31-clarifying-questions-design.md`.

**Tech Stack:** Python 3.12, prompt_toolkit, rich, anthropic SDK (structured output), pydantic, pytest, uv.

## Global Constraints

- Code, identifiers and comments in English; interface strings in `ui.STRINGS` (English only).
- Full type annotations; `uv run mypy` (strict on `src/`) must pass; `ruff` formats at 88 columns.
- Prompts for Claude live in `src/sepia/prompts/`, never inline in code.
- Tests: names `test_<unit>_<scenario>_<expected>`, every assert has a message, shared fixtures in `tests/conftest.py`, mock only external dependencies. No real API calls, windows or downloads.
- Never open or read `.env`. Never print or log a key.
- Commands to run checks: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, `uv run pytest`.
- Commit style: Conventional Commits, imperative summary ≤72 characters, body says why, ending with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01BW1DAApQxrcaPKBC51LHfS
  ```
- Hint wording follows the existing menus: `↑↓ to move · Enter to choose · Esc to cancel`.

---

### Task 1: The `ask` setting

**Files:**
- Modify: `src/sepia/config.py` (`Settings`, `Choices`, `load_settings`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.ask: bool` (default `True`), `Choices.ask: bool | None`, env `SEPIA_ASK` (`on`/`off`, default `on`). `remember(ask=...)` works through `Choices`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_config.py`, and add `"SEPIA_ASK"` to the list in `test_load_settings_unknown_choice_raises_config_error`'s parametrize)

```python
@pytest.mark.parametrize(
    ("environ", "expected"),
    [({}, True), ({"SEPIA_ASK": " OFF "}, False), ({"SEPIA_ASK": "on"}, True)],
)
def test_load_settings_ask_switch_sets_clarifying_questions(
    environ: dict[str, str], expected: bool
) -> None:
    settings = load_settings(environ)
    assert settings.ask is expected, f"{environ}: got {settings}"


def test_load_settings_kept_ask_choice_wins_over_the_environment() -> None:
    settings = load_settings({"SEPIA_ASK": "on"}, Choices(ask=False))
    assert settings.ask is False, f"The kept choice must win, got {settings}"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_config.py -k "ask or unknown_choice" -v`
Expected: FAIL (`Settings` has no `ask`; `SEPIA_ASK=loud` raises nothing).

- [ ] **Step 3: Implement**

In `Settings`, after `mature`:

```python
    ask: bool = True
    """Let Claude ask a few questions before painting a vague request."""
```

In `Choices`, after `mature`:

```python
    ask: bool | None = None
```

In `load_settings`, after the `mature = ...` line:

```python
    ask = _choice(environ, "SEPIA_ASK", get_args(Switch), "on")
```

and pass `ask=ask == "on",` to `Settings(...)` after `mature=mature == "on",`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sepia/config.py tests/test_config.py
git commit -m "feat: add the clarifying questions setting" -m "SEPIA_ASK and a kept choice turn the questions on or off, like SEPIA_MATURE." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BW1DAApQxrcaPKBC51LHfS"
```

---

### Task 2: Questions in the director's reply

**Files:**
- Create: `src/sepia/prompts/ask.md`
- Modify: `src/sepia/prompts/request.md`, `src/sepia/director.py`
- Test: `tests/test_director.py`

**Interfaces:**
- Produces (in `sepia.director`):
  - `@dataclass(frozen=True) class Option: label: str; description: str`
  - `@dataclass(frozen=True) class Question: header: str; text: str; multi: bool; options: tuple[Option, ...]`
  - `@dataclass(frozen=True) class Answer: header: str; question: str; choices: tuple[str, ...]`
  - `Direction.questions: tuple[Question, ...] = ()`
  - `ASK_SCHEMA: dict[str, Any]`, `MAX_QUESTIONS = 3`, `MAX_OPTIONS = 4`, `MAX_HEADER = 12`
  - `Director(client, model, effort, mature=False, ask=False)`, property `ask` with setter
  - `Director.direct(request, scene, linked=None, answers: Sequence[Answer] = ()) -> Direction`
  - `system_prompt(mature: bool = False, ask: bool = False) -> str`
  - `build_request(request, scene, linked=False, answers: Sequence[Answer] = ()) -> str`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_director.py`; extend its `from sepia.director import (...)` with `ASK_SCHEMA, Answer, Option, Question`)

```python
QUESTION = {
    "header": "Subject",
    "question": "What should it show?",
    "multi": False,
    "options": [
        {"label": "A galaxy", "description": "spiral arms"},
        {"label": "A black hole", "description": "a bright disk"},
    ],
}


@pytest.mark.parametrize("ask", [False, True])
def test_director_direct_sends_questions_schema_and_rules_only_when_asking(
    fake_client: MagicMock, make_message, set_final_message, ask: bool
) -> None:
    set_final_message(make_message({**REPLY, "questions": []}))
    Director(fake_client, "claude-haiku-5-5", "low", ask=ask).direct("evren", Scene())
    kwargs = fake_client.beta.messages.stream.call_args.kwargs
    schema = kwargs["output_config"]["format"]["schema"]
    assert (schema is ASK_SCHEMA) is ask, f"ask={ask}: wrong schema"
    has_rules = "Clarifying questions:" in kwargs["system"]
    assert has_rules is ask, f"ask={ask}: rules in system prompt = {has_rules}"


def test_ask_schema_requires_questions_on_top_of_the_reply() -> None:
    assert "questions" in ASK_SCHEMA["required"], "questions must be required"
    assert set(REPLY_SCHEMA["required"]) < set(ASK_SCHEMA["required"]), (
        "Every reply field must stay required"
    )
    assert "questions" not in REPLY_SCHEMA["properties"], "The plain schema is today's"


def test_director_direct_vague_request_returns_its_questions(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message({**REPLY, "questions": [QUESTION]}))
    director = Director(fake_client, "claude-haiku-5-5", "low", ask=True)
    direction = director.direct("evren", Scene())
    expected = (
        Question(
            "Subject",
            "What should it show?",
            False,
            (
                Option("A galaxy", "spiral arms"),
                Option("A black hole", "a bright disk"),
            ),
        ),
    )
    assert direction.questions == expected, f"Got {direction.questions}"


def test_director_direct_keeps_questions_within_the_limits(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    six = [{"label": f" Option {i} ", "description": " d "} for i in range(6)]
    long = {
        "header": "  A very long header ",
        "question": " Which one? ",
        "multi": True,
        "options": [{"label": "  ", "description": "no label"}, *six],
    }
    no_text = {**QUESTION, "question": "  "}
    one_option = {**QUESTION, "options": QUESTION["options"][:1]}
    no_header = {**QUESTION, "header": ""}
    questions = [no_text, one_option, long, no_header, QUESTION, QUESTION]
    set_final_message(make_message({**REPLY, "questions": questions}))
    director = Director(fake_client, "claude-haiku-5-5", "low", ask=True)
    asked = director.direct("evren", Scene()).questions
    assert len(asked) == 3, f"At most three questions, got {len(asked)}"
    first = asked[0]
    assert first.header == "A very long", f"Header cut to 12, got {first.header!r}"
    assert first.text == "Which one?", f"Text stripped, got {first.text!r}"
    labels = [option.label for option in first.options]
    assert labels == ["Option 0", "Option 1", "Option 2", "Option 3"], f"Got {labels}"
    assert asked[1].header == "Question 2", f"Empty header, got {asked[1].header!r}"


@pytest.mark.parametrize(
    "case", ["off", "add", "linked", "answers", "subject", "references"]
)
def test_director_direct_drops_questions_when_it_should_not_ask(
    fake_client: MagicMock, make_message, set_final_message, case: str
) -> None:
    reply: dict[str, object] = {**REPLY, "questions": [QUESTION]}
    if case == "subject":
        reply["subject"] = "Yunara League of Legends"
    if case == "references":
        reply["references"] = ["https://example.com/yunara"]
    set_final_message(make_message(reply))
    director = Director(fake_client, "claude-haiku-5-5", "low", ask=case != "off")
    scene = _painted_scene() if case == "add" else Scene()
    linked = Image.new("RGB", (4, 4)) if case == "linked" else None
    answers = (Answer("Mood", "Which mood?", ("Calm",)),) if case == "answers" else ()
    direction = director.direct("evren", scene, linked, answers)
    assert direction.questions == (), f"{case}: questions must be dropped"


def test_build_request_lists_the_answers_after_the_request() -> None:
    answers = (
        Answer("Subject", "What should it show?", ("A black hole",)),
        Answer("Mood", "Which moods fit?", ("Calm", "a dying red star")),
    )
    text = build_request("universe", Scene(), answers=answers)
    expected = (
        "<request>universe</request>\n<answers>\n"
        "Subject: What should it show? A black hole\n"
        "Mood: Which moods fit? Calm; a dying red star\n</answers>"
    )
    assert expected in text, f"Answers missing from {text!r}"


def test_build_request_without_answers_ends_with_the_request() -> None:
    text = build_request("universe", Scene())
    assert text.rstrip().endswith("<request>universe</request>"), f"Got {text!r}"


def test_system_prompt_adds_mature_then_question_rules() -> None:
    both = system_prompt(True, True)
    mature_rules = system_prompt(True).removeprefix(system_prompt()).strip()
    assert both.startswith(system_prompt()), "The base prompt comes first"
    mature_at, ask_at = both.index(mature_rules), both.index("Clarifying questions:")
    assert mature_at < ask_at, "mature.md comes before ask.md"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_director.py -v`
Expected: FAIL with `ImportError: cannot import name 'ASK_SCHEMA'`.

- [ ] **Step 3: Write the prompt** — create `src/sepia/prompts/ask.md` with exactly:

```
Clarifying questions:
- Some requests could mean very different pictures, and a guess would likely miss what the person has in mind: a one-word broad theme ("universe", "nature", "the future", "love", "a dream") or a vague ask ("something cool", "paint anything", "a fantasy scene"). For such a new picture, ask one to three short questions in "questions" that settle what changes the picture most: the subject first, then the mood, the setting or the style.
- Do not ask when the request already says what to paint ("a cat", "a waterfall at sunset", "yunara lol"), when earlier requests are listed, when a reference picture comes before the request, or when <answers> follow it: leave "questions" empty.
- Each question has a "header" of one or two words (at most 12 characters, such as "Subject" or "Mood"), the "question" in one short sentence ending in a question mark, "multi" true when several answers combine well (moods, colors, things to include) and false when only one makes sense (the main subject, the time of day), and two to four "options". Each option has a "label" of one to five words and a "description" of at most eight words saying what the picture would show. Make the options concrete and clearly different; never add an "other" or "anything" option, since sepia adds a box for the person's own answer.
- Write the questions, headers and options in English, whatever language the request is in, like the message.
- Even when you ask, fill "message", "prompt" and the other fields for your best guess: sepia paints it when the person skips the questions.
- When <answers> follow the request, the person answered your questions: paint what the request and the answers describe together. An answer can be their own words instead of one of your options; a question they left unanswered is yours to decide.
- With these rules the reply has a seventh field, "questions": the list of questions, or an empty list.
```

Replace `src/sepia/prompts/request.md` with (the file keeps its trailing newline):

```
$history
$linked<request>$request</request>$answers
```

- [ ] **Step 4: Implement in `src/sepia/director.py`**

Imports: add `from collections.abc import Sequence`.

After `LINKED_SIDE`:

```python
MAX_QUESTIONS = 3
"""Questions asked about one request; more would feel like a form."""
MAX_OPTIONS = 4
"""Options per question, besides the person's own answer."""
MAX_HEADER = 12
"""Characters in a question's tab."""
```

After `REPLY_SCHEMA`:

```python
_OPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "One to five words."},
        "description": {
            "type": "string",
            "description": "At most eight words on what the picture would show.",
        },
    },
    "required": ["label", "description"],
    "additionalProperties": False,
}
_QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "header": {
            "type": "string",
            "description": "One or two words, at most 12 characters.",
        },
        "question": {
            "type": "string",
            "description": "One short sentence ending in a question mark.",
        },
        "multi": {
            "type": "boolean",
            "description": "True when several answers combine well.",
        },
        "options": {
            "type": "array",
            "items": _OPTION_SCHEMA,
            "description": "Two to four clearly different options.",
        },
    },
    "required": ["header", "question", "multi", "options"],
    "additionalProperties": False,
}
ASK_SCHEMA: dict[str, Any] = {
    **REPLY_SCHEMA,
    "properties": {
        **REPLY_SCHEMA["properties"],
        "questions": {
            "type": "array",
            "items": _QUESTION_SCHEMA,
            "description": "One to three questions about a vague request; empty "
            "when the request says what to paint.",
        },
    },
    "required": [*REPLY_SCHEMA["required"], "questions"],
}
"""The reply while clarifying questions are on."""
```

Before `class _Reply`:

```python
class _Option(BaseModel):
    label: str = ""
    description: str = ""


class _Question(BaseModel):
    header: str = ""
    question: str = ""
    multi: bool = False
    options: list[_Option] = Field(default_factory=list)
```

In `_Reply`, add `questions: list[_Question] = Field(default_factory=list)`.

Before `class Direction`:

```python
@dataclass(frozen=True)
class Option:
    label: str
    description: str


@dataclass(frozen=True)
class Question:
    """One of Claude's questions about a vague request."""

    header: str
    """The question's tab: one or two words."""
    text: str
    multi: bool
    """Several options can be picked together."""
    options: tuple[Option, ...]


@dataclass(frozen=True)
class Answer:
    header: str
    question: str
    choices: tuple[str, ...]
    """Option labels and the person's own words, in the order shown."""
```

In `Direction`, after `show`:

```python
    questions: tuple[Question, ...] = ()
    """Asked before painting a vague new picture; `prompt` is the guess meanwhile."""
```

`Director.__init__` gains `ask: bool = False` after `mature` and stores `self._ask = ask`. Add after the `mature` setter:

```python
@property
def ask(self) -> bool:
    return self._ask


@ask.setter
def ask(self, ask: bool) -> None:
    """Takes effect from the next request; /config sets it while sepia waits."""
    self._ask = ask
```

`direct` becomes (docstring gains the `answers` sentence; changed lines marked by context):

```python
    def direct(
        self,
        request: str,
        scene: Scene,
        linked: Image.Image | None = None,
        answers: Sequence[Answer] = (),
    ) -> Direction:
        """Turn `request`, in the context of `scene`, into an image prompt.

        `linked` is a picture of the subject, linked by the person or found by
        sepia; Claude sees it, so it can write the subject's look into the prompt
        without searching. `answers` are the person's answers to Claude's
        questions about this request. Questions come back only for a vague new
        picture: never for /add, a reference picture, answers or a named subject.
        """
        output_config: BetaOutputConfigParam = {
            "effort": self._effort,
            "format": {
                "type": "json_schema",
                "schema": ASK_SCHEMA if self._ask else REPLY_SCHEMA,
            },
        }
        fallback = self._model in FALLBACK_MODELS
        text = build_request(request, scene, linked=linked is not None, answers=answers)
```

and `system=system_prompt(self._mature, self._ask),`. At the end, replace the `return Direction(...)` block with:

```python
        edit = reply.edit and not scene.is_empty
        references = _links(reply.references)
        subject = reply.subject.strip()
        asks = (
            self._ask
            and scene.is_empty
            and linked is None
            and not answers
            and not subject
            and not references
        )
        return Direction(
            message=reply.message.strip(),
            prompt=reply.prompt.strip(),
            edit=edit,
            references=references,
            model=message.model,
            searches=_searches(message.usage),
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            subject=subject,
            show=reply.show and not edit,
            questions=_questions(reply.questions) if asks else (),
        )
```

After `_links`:

```python
def _questions(raw: list[_Question]) -> tuple[Question, ...]:
    """Claude's questions within sepia's limits; one that cannot be asked (no
    text, fewer than two options) is dropped."""
    kept: list[Question] = []
    for item in raw:
        options = tuple(
            Option(option.label.strip(), option.description.strip())
            for option in item.options
            if option.label.strip()
        )[:MAX_OPTIONS]
        text = item.question.strip()
        if not text or len(options) < 2:
            continue
        header = item.header.strip()[:MAX_HEADER].rstrip()
        kept.append(
            Question(header or f"Question {len(kept) + 1}", text, item.multi, options)
        )
    return tuple(kept[:MAX_QUESTIONS])
```

`system_prompt`:

```python
@cache
def system_prompt(mature: bool = False, ask: bool = False) -> str:
    """The art director's instructions; `mature` adds the rules for grown-up
    pictures and `ask` the rules for clarifying questions."""
    parts = [_prompt("director.md")]
    if mature:
        parts.append(_prompt("mature.md"))
    if ask:
        parts.append(_prompt("ask.md"))
    return "\n\n".join(parts)
```

`build_request` gains `answers: Sequence[Answer] = ()` and, before the `return`:

```python
    given = ""
    if answers:
        lines = "\n".join(
            f"{answer.header}: {answer.question} {'; '.join(answer.choices)}"
            for answer in answers
        )
        given = f"\n<answers>\n{lines}\n</answers>"
    return Template(_prompt("request.md")).substitute(
        history=history, linked=picture, request=request.strip(), answers=given
    )
```

- [ ] **Step 5: Run the tests and the checks**

Run: `uv run pytest tests/test_director.py -v && uv run mypy && uv run ruff check && uv run ruff format --check`
Expected: all PASS, no mypy or ruff errors.

- [ ] **Step 6: Commit**

```bash
git add src/sepia/prompts/ask.md src/sepia/prompts/request.md src/sepia/director.py tests/test_director.py
git commit -m "feat: let Claude ask about a vague request" -m "A broad request like 'universe' can mean very different pictures; with the questions on, Claude may return up to three questions next to its best guess, and a second call paints from the answers." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BW1DAApQxrcaPKBC51LHfS"
```

---

### Task 3: A toggle list in the picker

**Files:**
- Modify: `src/sepia/picker.py`
- Test: `tests/test_picker.py`

**Interfaces:**
- Produces: `picker.toggles(title: str, rows: Sequence[tuple[str, str, str, bool]], hint: str) -> dict[str, bool]` — rows are `(key, label, summary, value)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_picker.py`; import `toggles`)

```python
ROWS = (
    ("ask", "Clarifying questions", "ask before painting", True),
    ("mature", "Mature pictures", "sexy and dark", False),
)


def _toggles() -> dict[str, bool]:
    return toggles("Settings", ROWS, "Esc to close")


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("\x1b", {"ask": True, "mature": False}),
        ("\r\x1b", {"ask": False, "mature": False}),
        (f"{DOWN} \x1b", {"ask": True, "mature": True}),
        ("2\x1b", {"ask": True, "mature": True}),
        (f"\r\r{UP}{UP} q", {"ask": False, "mature": False}),
        (f"{UP}\r\x03", {"ask": True, "mature": True}),
    ],
)
def test_toggles_flips_values_and_returns_them_when_closed(
    terminal, keys: str, expected: dict[str, bool]
) -> None:
    pipe, _ = terminal
    pipe.send_text(keys)
    values = _toggles()
    assert values == expected, f"{keys!r}: expected {expected}, got {values}"


def test_toggles_draws_labels_values_summaries_and_hint(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text("\x1b")
    _toggles()
    drawn = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|[\r\n]", "", screen.getvalue())
    pieces = [
        "Settings",
        f"{POINTER} Clarifying questions   on   ask before painting",
        "Mature pictures        off  sexy and dark",
        "Esc to close",
    ]
    missing = [piece for piece in pieces if piece not in drawn]
    assert not missing, f"{missing} missing from {drawn!r}"
```

The fifth case: Enter twice flips `ask` off and on again, `UP UP` wraps back to row 0, Space flips it off, `q` closes. The last: `UP` wraps to row 1, Enter flips mature on, Ctrl+C closes keeping it.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_picker.py -v`
Expected: FAIL with `ImportError: cannot import name 'toggles'`.

- [ ] **Step 3: Implement** in `src/sepia/picker.py` — update the module docstring's first line to "A small menu for picking one option with the arrow keys, a list of on/off settings, and a panel to read and close, as in Claude Code."; add to `STYLE`: `"on": f"bold {ui.ACCENT}", "off": ui.MUTED,`; add after `choose`:

```python
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
```

and at the end of the module:

```python
def _flipper_for(
    row: int, keys_in_order: list[str], values: dict[str, bool]
) -> Callable[[KeyPressEvent], None]:
    def flip(event: KeyPressEvent) -> None:
        values[keys_in_order[row]] = not values[keys_in_order[row]]

    return flip
```

Wrap the two long `lines.append` calls in `render` as `ruff format` wants (the formatter decides; run it).

- [ ] **Step 4: Run the tests and checks**

Run: `uv run ruff format src/sepia/picker.py tests/test_picker.py && uv run pytest tests/test_picker.py -v && uv run mypy && uv run ruff check`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sepia/picker.py tests/test_picker.py
git commit -m "feat: add a list of on/off settings to the picker" -m "/config needs one menu for several switches; each flips at once and the list returns the values when it closes." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BW1DAApQxrcaPKBC51LHfS"
```

---

### Task 4: The question menu

**Files:**
- Create: `src/sepia/questions.py`
- Modify: `src/sepia/ui.py` (`STRINGS`)
- Test: `tests/test_questions.py`

**Interfaces:**
- Consumes: `sepia.director.Answer`, `Option`, `Question` (Task 2); `ui.Words`, `ui.POINTER`, `ui.CHECK`, `ui.BLOCK`, `ui.ACCENT`, `ui.MUTED`.
- Produces: `@dataclass(frozen=True) class Asked: answers: tuple[Answer, ...] = (); cancelled: bool = False` and `ask(questions: Sequence[Question], words: ui.Words) -> Asked`. Skipped = empty `answers` and not `cancelled`.

- [ ] **Step 1: Add the strings** to `ui.STRINGS` (after `"close_hint"`):

```python
    "questions_any": "Pick any.",
    "questions_other": "Other…",
    "questions_other_typed": "Other: ",
    "questions_paint": "Paint",
    "questions_ready": "Ready to paint",
    "questions_move": "↑↓ to move",
    "questions_toggle": "Space to toggle",
    "questions_pick": "Enter to pick",
    "questions_next": "Enter to go on",
    "questions_paint_key": "Enter to paint",
    "questions_switch": "←→ to switch",
    "questions_type": "type your own answer",
    "questions_skip": "Esc to paint my guess",
    "questions_paint_hint": "Enter to paint · ←→ to change an answer · Esc to paint "
    "my guess",
```

- [ ] **Step 2: Write the failing tests** — create `tests/test_questions.py`:

```python
import re

import pytest

from sepia import ui
from sepia.director import Answer, Option, Question
from sepia.questions import Asked, ask

DOWN, LEFT, RIGHT = "\x1b[B", "\x1b[D", "\x1b[C"
SUBJECT = Question(
    "Subject",
    "What should it show?",
    False,
    (
        Option("A galaxy", "spiral arms"),
        Option("A black hole", "a bright disk"),
        Option("A nebula", "colored gas"),
    ),
)
MOOD = Question(
    "Mood",
    "Which moods fit?",
    True,
    (
        Option("Calm", "still"),
        Option("Dramatic", "strong contrast"),
        Option("Mysterious", "hidden shapes"),
    ),
)


def _ask(*questions: Question) -> Asked:
    return ask(questions, ui.Words())


def _answer(question: Question, *choices: str) -> Answer:
    return Answer(question.header, question.text, choices)


def _drawn(screen) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|[\r\n]", "", screen.getvalue())


@pytest.mark.parametrize(
    ("keys", "choice"),
    [("\r", "A galaxy"), (f"{DOWN}\r", "A black hole"), ("3", "A nebula")],
)
def test_ask_single_question_picks_and_finishes(
    terminal, keys: str, choice: str
) -> None:
    pipe, _ = terminal
    pipe.send_text(keys)
    asked = _ask(SUBJECT)
    expected = Asked((_answer(SUBJECT, choice),))
    assert asked == expected, f"{keys!r}: got {asked}"


def test_ask_several_choices_toggle_with_space_and_finish_with_enter(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text(f" {DOWN}{DOWN} \r")
    asked = _ask(MOOD)
    expected = Asked((_answer(MOOD, "Calm", "Mysterious"),))
    assert asked == expected, f"Got {asked}"


def test_ask_several_choices_toggled_off_leave_the_question_unanswered(
    terminal,
) -> None:
    pipe, _ = terminal
    pipe.send_text("11\r")
    assert _ask(MOOD) == Asked(), "Nothing chosen is the same as skipping"


def test_ask_other_row_takes_typed_words_as_the_answer(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text("4a dying star 2\x7f\r")
    asked = _ask(SUBJECT)
    expected = Asked((_answer(SUBJECT, "a dying star"),))
    assert asked == expected, f"Got {asked}"


def test_ask_other_row_empty_does_not_pick(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text("4\r\x1b")
    assert _ask(SUBJECT) == Asked(), "Enter on an empty Other row must not pick"


def test_ask_several_choices_keep_typed_words_beside_the_options(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text(" 4neon\r")
    asked = _ask(MOOD)
    expected = Asked((_answer(MOOD, "Calm", "neon"),))
    assert asked == expected, f"Got {asked}"


def test_ask_escape_skips_with_no_answers(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text(f"{DOWN}\x1b")
    assert _ask(SUBJECT, MOOD) == Asked(), "Esc must paint the guess"


def test_ask_ctrl_c_cancels(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text("\x03")
    assert _ask(SUBJECT, MOOD) == Asked(cancelled=True), "Ctrl+C must cancel"


def test_ask_several_questions_go_on_to_the_paint_page(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text("2 \r\r")  # black hole → Mood, Calm, next → Paint, paint
    asked = _ask(SUBJECT, MOOD)
    expected = Asked((_answer(SUBJECT, "A black hole"), _answer(MOOD, "Calm")))
    assert asked == expected, f"Got {asked}"


def test_ask_switching_back_changes_an_answer(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text(f"1{LEFT}2{RIGHT}\r")  # galaxy, back, black hole, → Paint, paint
    asked = _ask(SUBJECT, MOOD)
    expected = Asked((_answer(SUBJECT, "A black hole"),))
    assert asked == expected, f"Only the changed answer must be sent, got {asked}"


def test_ask_paint_with_nothing_answered_skips(terminal) -> None:
    pipe, _ = terminal
    pipe.send_text(f"{RIGHT}{RIGHT}\r")
    assert _ask(SUBJECT, MOOD) == Asked(), "Painting with no answers is a skip"


def test_ask_draws_tabs_options_other_and_hint(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text("\x1b")
    _ask(SUBJECT, MOOD)
    drawn = _drawn(screen)
    pieces = [
        "☐ Subject",
        "☐ Mood",
        f"{ui.CHECK} Paint",
        "What should it show?",
        f"{ui.POINTER} 1. A galaxy      spiral arms",
        "Other…",
        "↑↓ to move · Enter to pick · ←→ to switch · Esc to paint my guess",
    ]
    missing = [piece for piece in pieces if piece not in drawn]
    assert not missing, f"{missing} missing from {drawn!r}"


def test_ask_draws_boxes_for_several_choices(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text(" \x1b")
    _ask(MOOD)
    drawn = _drawn(screen)
    pieces = [
        "Which moods fit? Pick any.",
        f"[{ui.CHECK}] Calm",
        "[ ] Dramatic",
        "Space to toggle · Enter to paint · Esc to paint my guess",
    ]
    missing = [piece for piece in pieces if piece not in drawn]
    assert not missing, f"{missing} missing from {drawn!r}"


def test_ask_draws_the_paint_page_with_unanswered_dashes(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text(f"2{RIGHT}\x1b")
    _ask(SUBJECT, MOOD)
    drawn = _drawn(screen)
    pieces = ["Ready to paint", "Subject  A black hole", "Mood     —"]
    missing = [piece for piece in pieces if piece not in drawn]
    assert not missing, f"{missing} missing from {drawn!r}"


def test_ask_cuts_long_lines_to_the_terminal_width(terminal) -> None:
    pipe, screen = terminal
    pipe.send_text("\x1b")
    long = Question(
        "Size", "How big?", False, (Option("Huge", "x" * 200), Option("Tiny", "y"))
    )
    _ask(long)
    drawn = _drawn(screen)
    assert "x" * 100 not in drawn, "A long description must be cut"
    assert "…" in drawn, "A cut line must end in an ellipsis"
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_questions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sepia.questions'`.

- [ ] **Step 4: Implement** — create `src/sepia/questions.py`:

```python
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
```

Notes for the implementer:
- Keys with their own binding (digits are not bound separately; `Keys.Any` handles them) win over `Keys.Any` in prompt_toolkit, so `space`, `enter`, arrows and `backspace` never reach `_type`.
- `"\x7f"` in the pipe arrives as `backspace`.
- If mypy complains about `row += [...]` on `StyleAndTextTuples`, use `row.extend([...])`.

- [ ] **Step 5: Run the tests and checks**

Run: `uv run ruff format src/sepia/questions.py tests/test_questions.py && uv run pytest tests/test_questions.py -v && uv run mypy && uv run ruff check`
Expected: all PASS. If a drawing assertion fails only on spacing, compare with the layout in the spec (labels padded to the widest label, two spaces before the description) and fix the code, not the expectation.

- [ ] **Step 6: Commit**

```bash
git add src/sepia/questions.py src/sepia/ui.py tests/test_questions.py
git commit -m "feat: add a menu for Claude's questions" -m "Each question takes one option, several, or the person's own words, with tabs and a Paint page when there are several, so a vague request can be settled in a few keys." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BW1DAApQxrcaPKBC51LHfS"
```

---

### Task 5: Wire the questions and /config into the prompt window

**Files:**
- Modify: `src/sepia/repl.py`, `src/sepia/ui.py` (`STRINGS`, `COMMANDS`, `answers`, `note`)
- Test: `tests/test_repl.py`, `tests/test_ui.py`

**Interfaces:**
- Consumes: `Director.ask`, `Director.direct(..., answers)`, `Direction.questions`, `Answer` (Task 2); `picker.toggles` (Task 3); `questions.ask`, `Asked` (Task 4); `Settings.ask`, `remember(ask=...)` (Task 1).
- Produces: `/config` command; `ui.answers(rows: Sequence[tuple[str, str]]) -> Text`; `ui.note(message: str) -> Text`.

- [ ] **Step 1: Strings and helpers in `ui.py`**

Add to `STRINGS`:

```python
    "questions_skipped": "Skipped the questions, painting Claude's guess",
    "questions_cancelled": "Cancelled, nothing painted",
    "config_title": "Settings",
    "config_hint": "↑↓ to move · Enter or Space to switch · Esc to close",
    "config.ask": "Clarifying questions",
    "config.ask_summary": "ask before painting a vague idea",
    "config.mature": "Mature pictures",
    "config.mature_summary": "sexy and dark pictures, never explicit",
    "ask_on": "Clarifying questions on, from the next picture on",
    "ask_off": "Clarifying questions off: sepia paints its best guess",
```

In `COMMANDS`, before the `/mature` row:

```python
(("/config", "turn clarifying questions and mature pictures on or off"),)
```

After `reply`:

```python
def answers(rows: Sequence[tuple[str, str]]) -> Text:
    """The answers to Claude's questions, kept under the request: a muted line per
    question, headers padded to one width."""
    width = max(len(header) for header, _ in rows)
    text = Text(style=MUTED)
    for index, (header, answer) in enumerate(rows):
        if index:
            text.append("\n")
        text.append(f"   · {header.ljust(width)}  {answer}")
    return text


def note(message: str) -> Text:
    """A muted aside under the request."""
    return Text(f"   · {message}", style=MUTED)
```

Tests (append to `tests/test_ui.py`):

```python
def test_words_commands_include_config() -> None:
    names = [usage.split()[0] for usage, _ in ui.Words().commands]
    assert "/config" in names, f"Got {names}"


def test_answers_pads_headers_to_one_width() -> None:
    text = ui.answers([("Subject", "A black hole"), ("Mood", "Calm")]).plain
    expected = "   · Subject  A black hole\n   · Mood     Calm"
    assert text == expected, f"Got {text!r}"
```

- [ ] **Step 2: Write the failing repl tests** — in `tests/test_repl.py`:

Replace the dict inside `Rig.direct` with a module constant above `class Rig` and add `direct_each`:

```python
PLAIN_REPLY: dict[str, object] = {
    "message": "A calm lake.",
    "prompt": "a lake at dawn",
    "edit": False,
    "references": [],
    "subject": "",
    "show": False,
}
```

```python
def direct(self, **fields: object) -> None:
    """What Claude answers from now on; `fields` override a plain reply."""
    self.set_message(self.make_message({**PLAIN_REPLY, **fields}))


def direct_each(self, *replies: dict[str, object]) -> None:
    """Claude's answers to the next calls, in order; each overrides a plain
    reply."""
    stream = self.client.beta.messages.stream.return_value.__enter__.return_value
    stream.get_final_message.side_effect = [
        self.make_message({**PLAIN_REPLY, **fields}) for fields in replies
    ]
```

Add a section after the picture-request tests:

```python
# --- clarifying questions ----------------------------------------------------------

VAGUE = {
    "message": "A spiral galaxy.",
    "prompt": "a galaxy guess",
    "questions": [
        {
            "header": "Subject",
            "question": "What should it show?",
            "multi": False,
            "options": [
                {"label": "A galaxy", "description": "spiral arms"},
                {"label": "A black hole", "description": "a bright disk"},
            ],
        }
    ],
}
CLEAR = {"message": "A black hole.", "prompt": "a black hole", "questions": []}


def test_repl_vague_request_asks_then_paints_from_the_answers(
    rig: Rig, terminal
) -> None:
    keys, _ = terminal
    rig.repl.director.ask = True
    rig.direct_each(VAGUE, CLEAR)
    keys.send_text("2")
    rig.say("universe")
    painted = [call[0] for call in rig.local.calls]
    assert painted == ["a black hole"], f"The answered direction must paint: {painted}"
    calls = rig.client.beta.messages.stream.call_args_list
    second = calls[1].kwargs["messages"][0]["content"]
    assert "Subject: What should it show? A black hole" in second, second
    requests = rig.repl.scene.requests
    assert requests == ["universe (Subject: A black hole)"], f"Kept {requests}"
    assert "· Subject  A black hole" in rig.printed(), rig.printed()
    assert "A black hole." in rig.printed(), "The second message must be shown"


def test_repl_skipped_questions_paint_the_guess_with_one_call(
    rig: Rig, terminal
) -> None:
    keys, _ = terminal
    rig.repl.director.ask = True
    rig.direct_each(VAGUE, CLEAR)
    keys.send_text("\x1b")
    rig.say("universe")
    painted = [call[0] for call in rig.local.calls]
    assert painted == ["a galaxy guess"], f"The guess must paint: {painted}"
    count = rig.client.beta.messages.stream.call_count
    assert count == 1, f"Skipping must not ask Claude again, asked {count} times"
    assert "Skipped the questions" in rig.printed(), rig.printed()


def test_repl_cancelled_questions_paint_nothing_and_keep_the_scene(
    rig: Rig, terminal
) -> None:
    keys, _ = terminal
    rig.say("a lake")
    before = rig.repl.scene
    rig.repl.director.ask = True
    rig.direct_each(VAGUE, CLEAR)
    keys.send_text("\x03")
    keep_going = rig.say("universe")
    assert keep_going, "Ctrl+C in the questions must not close sepia"
    assert len(rig.local.calls) == 1, "Nothing new may be painted"
    assert rig.repl.scene is before, "The scene must stay as it was"
    assert "Cancelled, nothing painted" in rig.printed(), rig.printed()


def test_repl_config_flips_both_switches_and_remembers_them(rig: Rig, terminal) -> None:
    keys, _ = terminal
    keys.send_text(f"\r{DOWN} \x1b")
    rig.say("/config")
    assert rig.repl.director.ask is True, "Clarifying questions must be on"
    assert rig.repl.director.mature is True, "Mature pictures must be on"
    kept = _choices()
    assert kept["ask"] is True and kept["mature"] is True, f"Kept {kept}"
    assert "Clarifying questions on" in rig.printed(), rig.printed()
    assert "Mature pictures on" in rig.printed(), rig.printed()


def test_repl_config_closed_unchanged_says_nothing(rig: Rig, terminal) -> None:
    keys, _ = terminal
    keys.send_text("\x1b")
    rig.say("/config")
    assert not config.choices_file().exists(), "Nothing may be remembered"
    assert "Clarifying questions" not in rig.printed(), rig.printed()
```

(The rig's director starts with `ask=False` and `mature=False`, so `/config`'s Enter flips questions on and Space on the second row flips mature on.)

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_repl.py tests/test_ui.py -v -k "vague or skipped or cancelled or config or answers"`
Expected: FAIL (`/config` unknown; questions never asked).

- [ ] **Step 4: Implement in `src/sepia/repl.py`**

Imports:

```python
from collections.abc import Callable, Sequence

...
from sepia.director import Answer, Direction, Director, DirectorError, create_client

...
from sepia.picker import choose, show, toggles
from sepia.questions import ask as ask_questions
```

In `_handle`, before the `elif command.name == "mature":` branch:

```python
        elif command.name == "config":
            self._configure()
```

After `_pick`:

```python
    def _configure(self) -> None:
        """/config: the on/off settings in one list. Each one changed is applied,
        kept for the next session and confirmed; /mature is a shortcut to one."""
        values = toggles(
            self.words("config_title"),
            [
                (
                    "ask",
                    self.words("config.ask"),
                    self.words("config.ask_summary"),
                    self.director.ask,
                ),
                (
                    "mature",
                    self.words("config.mature"),
                    self.words("config.mature_summary"),
                    self.director.mature,
                ),
            ],
            self.words("config_hint"),
        )
        if values["ask"] != self.director.ask:
            self.director.ask = values["ask"]
            remember(ask=values["ask"])
            self.transcript.say(ui.reply(self.words(f"ask_{_switch(values['ask'])}")))
        if values["mature"] != self.director.mature:
            self.director.mature = values["mature"]
            remember(mature=values["mature"])
            state = _switch(values["mature"])
            self.transcript.say(ui.reply(self.words(f"mature_{state}")))
```

`_draw`: replace everything from `direction = self._direct(words, found, scene)` down to (and including) `scene.record(...)`'s first argument as follows (the rest of the method stays):

```python
        direction = self._direct(words, found, scene)
        if direction is None:
            return
        answers: tuple[Answer, ...] = ()
        if direction.questions:
            asked = self._ask(direction)
            if asked is None:
                return
            answers = asked
            if answers:
                direction = self._direct(words, found, scene, answers)
                if direction is None:
                    return
        told = _clarified(words or request, answers)
        if found is None and (direction.subject or direction.references):
            found = self._find_subject(direction)
            if found is not None and direction.show:
                self._present(told, found, direction.message, scene)
                return
            if found is not None:
                # Claude now sees the picture, so the prompt describes the real look.
                direction = self._direct(words, found, scene, answers) or direction
        # A new picture starts from an empty scene; /add keeps the last reference.
        likeness = found or scene.likeness
        base = scene.image
        painting = self._paint(direction.prompt, scene.seed, base, likeness)
        if painting is None:
            return
        path = self._keep(painting.image)
        scene.record(
            told,
            direction.prompt,
            painting.image,
            likeness,
            path=path,
            base=base,
        )
```

Update the `_draw` docstring: add "A vague new picture may first get Claude's questions; the answers go back to Claude before anything is painted."

`_direct` gains `answers: Sequence[Answer] = ()` and passes it on:

```python
    def _direct(
        self,
        words: str,
        found: Reference | None,
        scene: Scene,
        answers: Sequence[Answer] = (),
    ) -> Direction | None:
        """Claude's direction for `words` in `scene`, shown `found` when there is
        one and told the person's `answers`; None after saying why it failed."""
        picture = found.image if found is not None else None
        try:
            direction = self._wait(
                lambda: self.director.direct(words, scene, picture, answers),
                "directing",
            )
```

After `_direct`:

```python
    def _ask(self, direction: Direction) -> tuple[Answer, ...] | None:
        """The person's answers to Claude's questions: empty when they skipped
        them (Claude's guess paints), None when they cancelled the request. The
        spinner's clock starts again once they are done."""
        asked = ask_questions(direction.questions, self.words)
        if asked.cancelled:
            self.transcript.say(ui.reply(self.words("questions_cancelled")))
            return None
        if asked.answers:
            rows = [(answer.header, ", ".join(answer.choices)) for answer in asked.answers]
            self.transcript.say(ui.answers(rows))
        else:
            self.transcript.say(ui.note(self.words("questions_skipped")))
        self._started = time.monotonic()
        return asked.answers
```

Module functions, after `_host`:

```python
def _switch(on: bool) -> str:
    return "on" if on else "off"


def _clarified(request: str, answers: Sequence[Answer]) -> str:
    """`request` with the answers to Claude's questions, as the scene keeps it for
    a later /add: "universe (Subject: A black hole; Mood: Calm)"."""
    if not answers:
        return request
    given = "; ".join(f"{a.header}: {', '.join(a.choices)}" for a in answers)
    return f"{request} ({given})"
```

In `run_repl`, build the director with the setting:

```python
    director = Director(
        create_client(key),
        settings.model,
        settings.effort,
        settings.mature,
        settings.ask,
    )
```

- [ ] **Step 5: Run the whole suite and the checks**

Run: `uv run ruff format && uv run ruff check && uv run mypy && uv run pytest`
Expected: all PASS (the existing `test_repl` tests too: the rig's director has `ask=False`).

- [ ] **Step 6: Commit**

```bash
git add src/sepia/repl.py src/sepia/ui.py tests/test_repl.py tests/test_ui.py
git commit -m "feat: ask about vague requests and add /config" -m "The prompt window shows Claude's questions, sends the answers back before painting, and keeps them with the request for /add. /config gathers the on/off settings in one list." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BW1DAApQxrcaPKBC51LHfS"
```

---

### Task 6: Docs, landing page and changelog

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `CLAUDE.md`, `site/src/data/commands.ts`, `site/src/components/Cli.astro`

**Interfaces:**
- Consumes: the behaviour from Tasks 1–5; nothing produced for code.

- [ ] **Step 1: README.md**
  - Command table: add a row before `/mature`: `| \`/config\` | Turn clarifying questions and mature pictures on or off in one list. |`
  - The menu paragraph (the one starting "`/style`, `/charset`, `/model`, `/effort`, `/mature` and `/keys` without an argument open a menu"): add a sentence: "`/config` lists the on/off settings: the arrow keys move, Enter or Space switches one, Esc closes."
  - New section "Clarifying questions" after the command section: when a request could mean very different pictures ("universe", "something cool"), Claude asks one to three short questions first. Each picks one option or several (Space), and the last row takes your own words. With several questions, ←→ switches between them and the Paint page sends the answers. Esc skips them and paints Claude's guess; Ctrl+C cancels the request. A clear request is painted at once. Asking costs a second Claude call, about twice the tokens of that request; turn it off in `/config` or with `SEPIA_ASK=off`.
  - Variables table: add `| \`SEPIA_ASK\` | \`on\` | Let Claude ask about a vague request before painting (\`on\` or \`off\`). \`/config\` changes it while sepia runs. |` after `SEPIA_MATURE`.
  - The kept-choices sentence: "What you pick with `/model`, `/effort`, `/style`, `/charset`, `/mature`, `/config`, `/api` or `/local` is kept…".
- [ ] **Step 2: Site** — `site/src/data/commands.ts`: add `{ cmd: '/config', comment: 'turn clarifying questions and mature pictures on or off' },` before the `/mature` entry. `site/src/components/Cli.astro`: next to the sentence about menus, add that `<code>/config</code>` lists the on/off settings. Run `cd site && npm run format` if it exists, else `npx prettier --write src/data/commands.ts src/components/Cli.astro`, then `npm run check && npm run format:check && npm run build`.
- [ ] **Step 3: CLAUDE.md** — layout: add `- \`src/sepia/questions.py\`: the menu for Claude's clarifying questions (one option, several, or the person's own words; tabs and a Paint page for several).`; `prompts/` line: add "`ask.md` (appended while clarifying questions are on)"; picker line: "arrow-key menu for commands with fixed options (`/style`, `/charset`, `/effort`, `/mature`) and the `/config` toggle list"; director line: "structured JSON reply (`message`, `prompt`, `edit`, `references`, and `questions` while asking)".
- [ ] **Step 4: CHANGELOG.md** — under `[Unreleased]` → `### Added`, first two bullets:

```markdown
- Clarifying questions: when a request could mean very different pictures ("universe", "something cool"), Claude first asks one to three short questions, as Claude Code does. Each takes one option or several, and the last row takes your own words; Esc paints Claude's guess instead, Ctrl+C cancels. Off with `/config` or `SEPIA_ASK=off`.
- `/config` lists the on/off settings, clarifying questions and mature pictures, in one menu; `/mature` stays as a shortcut.
```

- [ ] **Step 5: Run all checks**

Run: `uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest && cd site && npm run check && npm run format:check && npm run build`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add README.md CHANGELOG.md CLAUDE.md site/src/data/commands.ts site/src/components/Cli.astro
git commit -m "docs: describe clarifying questions and /config" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BW1DAApQxrcaPKBC51LHfS"
```

---

## Release (done by the coordinator after Task 6, not by a task agent)

1. All checks pass on a clean tree.
2. Version `0.4.0` in `pyproject.toml`, `src/sepia/__init__.py`, `site/src/data/commands.ts`; `uv lock`.
3. CHANGELOG: `[Unreleased]` → `## [0.4.0] - 2026-10-31` with an empty `[Unreleased]` above it, compare links updated; `uv run python scripts/release_notes.py 0.4.0` prints the notes.
4. `rm -rf dist && uv build && uvx twine check dist/*`; version check from `docs/releasing.md`.
5. `git commit -m "chore: release 0.4.0"`, `git push origin main`, `git tag v0.4.0 && git push origin v0.4.0`; watch the `release` workflow.
