# /copy Implementation Plan

> Executed inline (light process for small features): one implementation pass,
> then one review of the whole diff.

**Goal:** `/copy` puts the picture in the viewer window on the clipboard as fenced
plain text that fits one Discord message, and answers `Copied`.

**Architecture:** the prompt window draws the text itself from `Scene.image`, the
charset and a smaller grid derived from the window's `Canvas` (as `/save` draws
its PNG), then hands it to the operating system's clipboard tool. Spec:
`docs/superpowers/specs/2026-11-03-copy-command-design.md`.

**Tech Stack:** the existing raster and ascii_art pipeline; `clip`, `pbcopy`,
`wl-copy`/`xclip`/`xsel` through `subprocess`. No new dependency.

## Global Constraints

- At most 80 columns (`COPY_COLS = 80`) and 2,000 characters with the fences
  (`COPY_LIMIT = 2000`); the copy keeps the window's shape.
- Fenced with ```` ``` ````; `` ` `` becomes `.`; trailing spaces removed.
- No real clipboard or tool in tests: `subprocess.run`, `shutil.which` and
  `sys.platform` are patched in `test_clipboard.py`, `repl.copy_text` in
  `test_repl.py`. Every assert has a message; names
  `test_<unit>_<scenario>_<expected>`.
- Strings in `ui.STRINGS`, English only. mypy strict, ruff clean.
- Commits are left to the user.

---

### Task 1: `clipboard.py`

**Files:** create `src/sepia/clipboard.py`, `tests/test_clipboard.py`.

**Produces:** `COPY_COLS`, `COPY_LIMIT`, `FENCE`, `copy_size(canvas: Canvas) ->
Canvas`, `fence(lines: Sequence[str]) -> str`, `art_text(image: Image.Image,
canvas: Canvas, charset: Charset) -> str`, `ClipboardError(Exception)`,
`copy_text(text: str) -> None`.

- [ ] Write the tests listed under `tests/test_clipboard.py` in the spec.
- [ ] Run `uv run pytest tests/test_clipboard.py`: fails (no module).
- [ ] Write `clipboard.py` as the spec's Units section says.
- [ ] Run `uv run pytest tests/test_clipboard.py`: passes.

### Task 2: `/copy` in the prompt window, help and docs

**Files:** modify `src/sepia/repl.py` (`_handle`, new `_copy` beside `_save`),
`src/sepia/ui.py` (`STRINGS`, `COMMANDS`), `tests/test_repl.py` (autouse
`copied` fixture, `/copy` tests), `tests/test_ui.py`, `README.md`,
`CHANGELOG.md`, `site/src/data/commands.ts`, `CLAUDE.md`.

**Consumes:** `art_text`, `copy_text`, `ClipboardError` from Task 1.

- [ ] Write the `/copy` tests in `test_repl.py` and the `/copy` help test in
  `test_ui.py`.
- [ ] Run them: fail (unknown command).
- [ ] Add the strings, the help line and `_copy`.
- [ ] Run them: pass.
- [ ] Docs: README row, CHANGELOG `[Unreleased]` → `### Added`, site
  `commands.ts`, CLAUDE.md layout line.

### Verification

```bash
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
cd site && npm run check && npm run format:check && npm run build
```

Then one review of the whole diff.
