# Clarifying questions and /config

When a request is open-ended ("universe", "something cool"), Claude asks one to
three short questions before painting, as Claude Code does: each question picks
one option or several, and every question has a box for the person's own answer.
`/config` gathers the on/off settings (clarifying questions and mature
pictures) in one list. Both ship in **0.4.0** with the unreleased `/undo`,
`/again` and `/cam`.

## Choice

The director's JSON reply gains a `questions` field (approach A). Claude decides
in the same call whether to ask, and always writes its best guess as well.
A clear request costs what it does today plus the longer system prompt (about
+6% input tokens). A request that asks makes a second call with the answers,
about twice the tokens. Rejected: a separate "is this vague?" call before every
request (an extra call each time), and a client-side `ask_user` tool (a tool
loop mixed with the server-side web search, for the same result).

## Director

### Prompt

`prompts/ask.md` is appended to the system prompt while clarifying questions are
on, after `mature.md` when that is on too: `system_prompt(mature, ask)`. It says:

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

### Schema

With questions on, the director sends `ASK_SCHEMA`: `REPLY_SCHEMA` plus a
required `questions` array of objects with `header`, `question`, `multi` and
`options` (objects with `label` and `description`), all required, no additional
properties. Size limits are in the descriptions, not in schema keywords, and the
code enforces them. With questions off the schema and the prompt are exactly
today's, so turning the feature off costs nothing.

### Types and limits

In `director.py`:

```python
@dataclass(frozen=True)
class Option:
    label: str
    description: str

@dataclass(frozen=True)
class Question:
    header: str
    text: str
    multi: bool
    options: tuple[Option, ...]

@dataclass(frozen=True)
class Answer:
    header: str
    question: str
    choices: tuple[str, ...]
    """Option labels and the person's own words, in the order shown."""
```

`Direction.questions: tuple[Question, ...] = ()`. The reply is cleaned up:
whitespace is stripped, options without a label are dropped, options past the
fourth are dropped, a question with no text or fewer than two options is
dropped, questions past the third are dropped, and a header is cut to 12
characters (`MAX_QUESTIONS = 3`, `MAX_OPTIONS = 4`, `MAX_HEADER = 12`).

`Director.ask: bool` is a property like `mature`. `direct(request, scene,
linked=None, answers=())` returns no questions when the director should not
ask, whatever Claude wrote: questions off, an earlier picture in the scene
(`/add`), a reference picture, answers given, or a named subject (`subject` or
`references` set). So the prompt window shows questions whenever a direction
has them.

### Answers in the request

`build_request(request, scene, linked, answers)` adds, after the request:

```
<answers>
Subject: What should the universe picture show? A black hole
Mood: Which moods fit? Calm; a dying red star
</answers>
```

`request.md` gets an `$answers` slot after `<request>`; it is empty without
answers.

## Prompt window

`Repl._draw` after the first direction:

1. No questions: as today.
2. Questions: `questions.ask(direction.questions, words)` shows the menu.
   - **Answers**: the transcript keeps one muted line per answered question
     (`   · Subject  A black hole`, headers padded to one width). The spinner's
     clock restarts, the director is asked again with the answers, and that
     direction paints. The scene records the request as `universe (Subject: A
     black hole; Mood: Calm, a dying red star)`, so a later `/add` knows what
     was chosen. If the second call fails, its error is shown and nothing is
     painted; the person's answers are not silently replaced by the guess.
   - **Skipped** (Esc, or Paint with nothing answered): the transcript shows
     `   · Skipped the questions, painting Claude's guess` (muted) and the
     first direction paints. No second call.
   - **Cancelled** (Ctrl+C): `⏺ Cancelled, nothing painted` and the scene
     stays as it was. Ctrl+C here does not close sepia.
3. Everything after (subject lookup, `show`, painting) works on the direction
   that came last.

## Question menu

New module `src/sepia/questions.py`: `ask(questions, words) -> Asked`, with
`Asked(answers: tuple[Answer, ...], cancelled: bool)`. Skipped is empty answers
and not cancelled. Like `picker.choose` it is an inline prompt_toolkit
`Application` drawn at the transcript's cursor that erases itself when done,
in the same palette: `❯` pointer, bold `ACCENT` for the highlighted row,
`MUTED` descriptions and hints, `✔` in `ACCENT`.

### Layout

Several questions get a tab row and a Paint page; a single question has
neither and finishes as soon as it is answered.

```
 ☐ Subject   ☐ Mood   ☐ Light   ✔ Paint

 What should the universe picture show?
 ❯ 1. A spiral galaxy   its glowing arms seen from far away
   2. A black hole      a bright disk of light bending around it
   3. A nebula          clouds of colored gas where stars are born
   4. Other…

 ↑↓ to move · Enter to pick · ←→ to switch · Esc to paint my guess
```

- Tab row: an answered question's tab shows `✔` (`ACCENT`), an unanswered one
  `☐` (`MUTED`); the current tab is bold `ACCENT` in reverse video. The last
  tab, `✔ Paint`, opens the Paint page. Tabs are separated by three spaces.
- Question: bold, one line, then the options numbered from 1, labels padded to
  the widest label, descriptions `MUTED` after two spaces.
- Single choice: the chosen option shows `✔` after its description when the
  question is visited again, and the pointer starts on it.
- Several choices: a box before the label, `[✔]` in `ACCENT` or `[ ]` in
  `MUTED`; the question ends with " Pick any." in `MUTED`.
- The last row is always the person's own answer: `Other…` (`MUTED`) while
  empty and not highlighted; highlighted it reads `Other: ` plus the text typed
  so far and a `█` cursor in `ACCENT`. Typed text marks it chosen.
- Every line is cut to the terminal width with `…`, so nothing wraps.
- Hints, `MUTED`, worded like the other menus' (`↑↓ to move · Enter to
  choose · Esc to cancel`), only for the keys that work here, joined with ` · `:
  - single choice: `↑↓ to move · Enter to pick · ←→ to switch · Esc to paint
    my guess`
  - several choices: `Space to toggle · Enter to go on · ←→ to switch · Esc to
    paint my guess` (no `↑↓ to move`, so the line fits 80 columns)
  - on the Other row: `type your own answer` first, instead of `↑↓ to move`
    and `Space to toggle`
  - a single question: no `←→ to switch`, and `Enter to paint` instead of
    `Enter to go on`.

Paint page:

```
 ✔ Subject   ✔ Mood   ☐ Light   ✔ Paint

 Ready to paint
   Subject  A black hole
   Mood     Calm, a dying red star
   Light    —

 Enter to paint · ←→ to change an answer · Esc to paint my guess
```

Headers padded to one width; an unanswered question shows `—` in `MUTED`.

### Keys

- ↑ ↓ move the pointer, wrapping. ← → (and Tab, Shift+Tab) move between tabs,
  wrapping, when there are several questions.
- Single choice: Enter picks the highlighted option and goes to the next tab
  (the last question goes to Paint; a single question finishes). A digit 1–9
  picks that option the same way. Enter on an empty Other row does nothing.
- Several choices: Space or a digit toggles an option; Enter goes to the next
  tab (a single question finishes). A question with nothing chosen stays
  unanswered.
- Other row: printable keys (Space and digits too) type into it, Backspace
  deletes; the row counts as chosen while its text is not empty. A single
  choice picks it with Enter; several choices keep it alongside the others.
- Paint page: Enter finishes with the answered questions; with none answered
  it is the same as Esc.
- Esc finishes with no answers (paint the guess). Ctrl+C cancels.

## /config

`/config` opens a list of on/off settings, drawn and erased like the other
menus:

```
 Settings
 ❯ Clarifying questions   on   ask before painting a vague idea
   Mature pictures        off  sexy and dark pictures, never explicit

 ↑↓ to move · Enter or Space to switch · Esc to close
```

`picker.toggles(title, rows, hint) -> dict[str, bool]`, rows being `(key,
label, summary, value)`: ↑ ↓ move (wrapping), Enter, Space or the row's number
flips the highlighted value at once (`on` in bold `ACCENT`, `off` in `MUTED`),
and Esc, q or Ctrl+C close it and return the values as they are. The prompt window applies each value that changed, keeps it with
`remember` and says so (`mature_on` / `mature_off` as `/mature` does today,
and new `ask_on` / `ask_off`: "Clarifying questions on, from the next picture
on" / "Clarifying questions off: sepia paints its best guess"). Nothing changed
says nothing. `/mature [on|off]` stays as a shortcut to the same setting.

## Settings

- `Settings.ask: bool = True`, `Choices.ask: bool | None`, and `SEPIA_ASK`
  (`on` or `off`, default `on`), read like `SEPIA_MATURE`. A value kept in
  `choices.json` wins over the variable, as for the others.
- `Repl` builds the director with `ask=settings.ask`.

## Strings and docs

- `ui.STRINGS` (English only, as all interface strings): the menu hints, `Other…`,
  `Other: `, `Pick any.`, `Paint`, `Ready to paint`, the skipped and cancelled
  lines, `config_title`, `config_hint`, `config.ask`, `config.mature` (label and
  summary), `ask_on`, `ask_off`.
- `ui.COMMANDS`: `("/config", "turn clarifying questions and mature pictures on
  or off")`, before `/mature`.
- README: a "Clarifying questions" section, `/config` in the command table and
  the menu paragraph, `SEPIA_ASK` in the variables table, `ask` among the kept
  choices. Site: `/config` in `commands.ts`, the menu sentence in `Cli.astro`,
  version `0.4.0`. CLAUDE.md layout: `questions.py`, `ask.md`, `/config` in
  `picker.py`.
- CHANGELOG `[Unreleased]` → `## [0.4.0] - 2026-10-31`: clarifying questions
  and `/config` under Added, with the entries already there.

## Release

Version `0.4.0` in `pyproject.toml`, `src/sepia/__init__.py` and
`site/src/data/commands.ts` (and `uv.lock`). All checks pass (ruff, ruff
format, mypy, pytest; site check, format:check, build), then commit, push
`main`, tag `v0.4.0` and push the tag, as `docs/releasing.md` says.

## Testing

- `test_director.py`: `ASK_SCHEMA` and `ask.md` only with questions on; replies
  with questions become `Question`s; the clean-up limits; no questions after
  `/add`, with a reference picture, with answers or with a named subject;
  `build_request` with answers.
- `test_questions.py` (new, through the `terminal` fixture): a single question
  picked with Enter and with a digit; several choices toggled with Space and
  sent with Enter; typing an Other answer; Esc skips; Ctrl+C cancels; tabs with
  ← → and the Paint page; the drawing of tabs, boxes, Other and hints; long
  lines cut to the width.
- `test_picker.py`: `toggles` flips with Enter, Space and digits and returns
  the values on Esc.
- `test_config.py`: `SEPIA_ASK`, and `ask` kept in `choices.json`.
- `test_repl.py`: a direction with questions asks, calls Claude again with the
  answers and paints that direction; skipping paints the first one with a
  single call; cancelling paints nothing and keeps the scene; `/config` flips
  both settings and remembers them.
- `test_ui.py`: `/config` in the commands.
