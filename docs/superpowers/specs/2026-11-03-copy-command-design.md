# /copy: the picture as plain text on the clipboard

## Goal

`/copy` puts the picture the viewer window shows on the clipboard as plain text,
ready to paste into Discord, Slack, GitHub or a code comment, and the prompt window
answers `Copied`. No colors, no HTML or ANSI files: one command, one result.

## Decisions

- **Plain text in a code fence.** The text is wrapped in ```` ``` ```` lines, which
  Discord, Slack and GitHub need to show it in a monospace font; in a code comment
  the two fence lines are deleted by hand.
- **Sized for one Discord message.** Discord takes at most 2,000 characters a
  message. The copy keeps the window's shape, is at most 60 columns wide, and
  shrinks until the fenced text fits 2,000 characters. A 200x50 window gives
  60x15 cells, 922 characters. Discord wraps a code block's longer rows at their
  spaces, and about 72 characters fit beside the member list on a 1920 px screen;
  the first release's 80 columns broke every row in two.
- **Dark backgrounds, as the viewer.** Dense symbols stand for bright pixels, as in
  the viewer and on Discord's default dark theme. On a light theme the picture reads
  as a negative; that is accepted, nothing is inverted.
- **No backticks.** The classic ramp's lightest symbol is `` ` ``; three in a row
  would close the fence early. In the copy it becomes `.`, a symbol of about the
  same coverage.
- **No new dependency.** The operating system's own tool takes the text: `clip` on
  Windows, `pbcopy` on macOS, and on Linux the first of `wl-copy`,
  `xclip -selection clipboard` and `xsel --clipboard --input` that is installed.

## Approach

The prompt window builds the text itself, as `/save` builds its PNG: it holds the
latest picture (`Scene.image`), the charset and the window's size (`Canvas`). Only
the grid differs: the copy's own smaller grid instead of the window's.

```
Scene.image -> raster.enhance -> raster.fit_image(cols * CELL_WIDTH, rows * CELL_HEIGHT)
            -> ascii_art.image_to_art(cols, rows, charset=charset) -> fenced text
            -> OS clipboard tool
```

`/style` does not change the text: the symbols are the same in `ink` and `fill`,
only their colors differ.

## Units

### `src/sepia/clipboard.py` (new)

- `COPY_COLS = 60`, `COPY_LIMIT = 2000`, `FENCE = "```"`.
- `copy_size(canvas: Canvas) -> Canvas`: the copy's grid. Starts at
  `min(COPY_COLS, canvas.cols)` columns, with `rows = max(1, round(cols *
  canvas.rows / canvas.cols))`, and takes one column off (rows following) while
  `rows * (cols + 1) + 7 > COPY_LIMIT` and `cols > 1`. The rows are then capped at
  `(COPY_LIMIT - 7) // (cols + 1)`, so even an absurd window shape fits. `rows *
  (cols + 1) + 7` is the fenced text's longest length: two fence lines, their two
  newlines, and every row full with its newline.
- `fence(lines: Sequence[str]) -> str`: each line with `` ` `` replaced by `.` and
  its trailing spaces removed, joined by `\n`, between a ```` ``` ```` line above
  and below.
- `art_text(image: Image.Image, canvas: Canvas, charset: Charset) -> str`: the
  pipeline above on `copy_size(canvas)`, then `fence(art.lines())`.
- `class ClipboardError(Exception)`: no tool found, or the tool failed.
- `copy_text(text: str) -> None`: runs the platform's tool with `text` on its
  standard input (UTF-8; the text is ASCII), `check=True`, a 5 second timeout,
  output sent to `DEVNULL` (`wl-copy` and `xclip` leave a process behind that
  would hold a captured pipe open). A non-zero exit, a timeout and a tool that
  cannot start each become a `ClipboardError` that names the reason ("clip exited
  with code 1", "clip did not finish in time", "could not run clip"); on Linux
  with none of the three tools installed it raises
  `ClipboardError("no clipboard tool found; install wl-copy or xclip")`.

### `src/sepia/repl.py`

`/copy` in `_handle`, beside `/save`. `_copy` mirrors `_save`: a live camera keeps
its frame first; with no picture, a failed reply `copy_empty`. Otherwise
`copy_text(art_text(self.scene.image, self.canvas, self.charset))` and a reply
`copied`; a `ClipboardError` gives a failed reply `copy_failed`. A playing video is
left alone, as `/save` leaves it: the picture under it is copied.

### `src/sepia/ui.py`

- Help line after `/save`: `("/copy", "copy the picture as text for Discord or GitHub")`.
- Strings: `copy_empty` ("Nothing to copy yet: describe a picture first"), `copied`
  ("Copied"), `copy_failed` ("Could not copy the picture: {error}").

### Docs

- `README.md`: a `/copy` row after `/save` in the commands table, with the 60
  columns, the 2,000 characters and the fence.
- `CHANGELOG.md`: under `[Unreleased]`, `### Added`.
- `site/src/data/commands.ts`: the help line, word for word.
- `CLAUDE.md`: `clipboard.py` in the layout list.

## Errors

- No picture yet: the `copy_empty` reply; the clipboard is not touched.
- No clipboard tool (Linux), or the tool fails or times out: the `copy_failed`
  reply with the reason; sepia goes on.

## Tests

`tests/test_clipboard.py`:

- `copy_size` of a 200x50 window is 60x15.
- `copy_size` of a tall 100x80 window fits 2,000 characters and keeps its shape
  within a row.
- `copy_size` of a window narrower than 60 columns keeps its width.
- `copy_size` of an absurd 1x5000 window still fits 2,000 characters.
- `fence` wraps the lines in fence lines, turns backticks into dots and drops
  trailing spaces.
- `art_text` of a gradient gives `copy_size` rows of at most its columns, inside the
  fence, at most 2,000 characters.
- `copy_text` runs `clip` on Windows and `pbcopy` on macOS with the text as input
  (`subprocess.run` mocked, `sys.platform` patched).
- `copy_text` on Linux uses the first installed tool (`shutil.which` mocked) and
  raises `ClipboardError` when there is none.
- `copy_text` turns a failing tool (`CalledProcessError`) into `ClipboardError`.

`tests/test_repl.py` (the rig records copies instead of touching the clipboard):

- `/copy` without a picture says so and copies nothing.
- `/copy` after a request copies fenced text and says `Copied`.
- A `ClipboardError` is reported with `Could not copy the picture`.
- `/copy` while the camera is live keeps the frame first.

`tests/test_ui.py`: `Words.commands` include `/copy`.

No test touches the real clipboard or runs a real tool.
