# /undo, /again and /cam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/undo`, `/again` and `/cam` to the prompt window, as designed in
`docs/superpowers/specs/2026-10-29-undo-again-cam-design.md`.

**Architecture:** The prompt window keeps a `History` of scenes and commits a new
scene only after a change succeeded. The viewer owns the camera: the prompt sends
`camera` messages, the viewer reads frames on a thread and draws them as raw ANSI.

**Tech Stack:** Python 3.12, numpy, Pillow, rich, prompt-toolkit, optional
`opencv-python-headless`.

## Global Constraints

- Code, identifiers and comments in English; user-facing strings in `ui.STRINGS`.
- mypy strict on `src/`, ruff at 88 columns, LF line endings.
- `cv2` imported inside functions only; the `cam` extra stays optional.
- Tests: `test_<unit>_<scenario>_<expected>`, every assert has a message, mock only
  external dependencies (here `cv2`), no real camera, window or API call.
- No commits unless the user asks (user rule beats the skill's commit steps).
- Done means: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`,
  `uv run pytest` all clean.

---

### Task 1: Scene history

**Files:**
- Modify: `src/sepia/scene.py`
- Test: `tests/test_scene.py`

**Interfaces:**
- Produces: `new_seed() -> int`; `Scene.path: Path | None`, `Scene.base: Image | None`;
  `Scene.record(request, prompt, image, path, likeness=None, base=None)`;
  `Scene.copy() -> Scene`; `UNDO_LIMIT = 20`;
  `History(limit=UNDO_LIMIT)` with `push(scene)`, `pop() -> Scene | None`, `__len__`.
  `Scene.reset` is removed.

- [ ] Write tests: copy keeps lists independent and shares pictures; history pops
  newest first; history drops the oldest beyond its limit; pop on empty is None;
  record keeps path and base.
- [ ] Run, see them fail; implement; run, see them pass.

### Task 2: /undo and /again in the prompt window

**Files:**
- Modify: `src/sepia/repl.py`, `src/sepia/ui.py`
- Test: `tests/test_repl.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `Repl.history: History`; `Repl._commit(scene: Scene) -> None`;
  `Repl._next_path() -> Path`; `Repl._paint(prompt, seed, base, likeness) -> Painting | None`;
  `Repl._painted(painting, likeness) -> str` (the reply's detail);
  `_direct(words, found, scene)`, `_present(request, found, message, scene)`.

- [ ] Write tests: undo after two pictures shows the first and restores its scene;
  undo after /add restores the requests; undo past the first picture clears the
  window; undo with nothing says so; /clear can be undone; a failed new request
  keeps the old scene; /again paints the last prompt with a new seed without
  Claude, over the base after /add, keeps the likeness, is counted and undoable;
  /again on a shown picture and on an empty scene refuse.
- [ ] Run, see them fail; refactor `_draw` to build a target scene and commit it;
  add `/undo`, `/again`, their strings and `COMMANDS` rows; run, see them pass.

### Task 3: Fast ANSI and a cheaper fit

**Files:**
- Modify: `src/sepia/ascii_art.py`, `src/sepia/raster.py`
- Test: `tests/test_ascii_art.py`, `tests/test_raster.py`

**Interfaces:**
- Produces: `to_ansi(art: SymbolArt) -> str`;
  `fit_image(image, width, height, resample=Image.Resampling.LANCZOS)`.

- [ ] Write tests: `to_ansi` places each row with `ESC[row;1H`, prints the same
  characters as `to_text`, writes the fill style's backgrounds, repeats no color
  escape within a run of one color, ends with a reset; `fit_image` honors `resample`.
- [ ] Run, see them fail; implement; run, see them pass.

### Task 4: The camera

**Files:**
- Create: `src/sepia/camera.py`
- Modify: `pyproject.toml` (extra `cam`, mypy override for `cv2`)
- Test: `tests/test_camera.py`

**Interfaces:**
- Produces: `CameraError(Exception)`; `camera_installed() -> bool`;
  `Capture` protocol (`isOpened`, `read`, `set`, `release`);
  `Camera(open_capture: Callable[[], Capture] = open_capture)` with
  `start() -> None` (raises `CameraError`), `latest() -> RGBImage | None`,
  `failed: bool`, `stop() -> None`; `mirrored_rgb(frame) -> RGBImage`.

- [ ] Write tests with a fake capture: start fails when not opened; latest is the
  newest frame mirrored and in RGB; a failed read sets `failed`; stop releases the
  capture and ends the thread; `camera_installed` follows `find_spec`.
- [ ] Run, see them fail; implement; run, see them pass.

### Task 5: The live view in the viewer

**Files:**
- Modify: `src/sepia/viewer.py`
- Test: `tests/test_viewer.py`

**Interfaces:**
- Consumes: Tasks 3 and 4.
- Produces: `LIVE_FPS = 15`; `LiveView(write, make_camera=Camera, clock=time.monotonic)`
  with `active: bool`, `handle(message) -> Message | None` (the reply to send),
  `step(cols, rows, style, charset) -> Message | None` (draws a due frame; an error
  reply when the camera was lost), `stop()`; `live_frame(pixels, cols, rows, style, charset) -> str`.

- [ ] Write tests: `on` starts the camera and replies `state: on`; a camera that
  cannot open replies the error; `off` stops; `keep` writes the newest frame as a
  PNG, stops and replies `kept`; `keep` without a frame replies an error; frames are
  limited to `LIVE_FPS`; a lost camera stops and replies an error; the loop wires
  messages, replies and drawing.
- [ ] Run, see them fail; implement and wire into `_loop`; run, see them pass.

### Task 6: /cam in the prompt window

**Files:**
- Modify: `src/sepia/repl.py`, `src/sepia/ui.py`
- Test: `tests/test_repl.py`

**Interfaces:**
- Consumes: Tasks 2 and 4 (`camera_installed`), Task 5's messages.
- Produces: `Repl.camera_live: bool`; `CAMERA_SECONDS = 15`;
  `Repl._camera(argument)`, `_start_camera()`, `_keep_frame() -> bool`,
  `_stop_camera()`.

- [ ] Write tests (the fake host answers camera messages): not installed explains
  the extra; on says so and marks live; an error reply explains with the privacy
  hint; /cam while live keeps the frame as a scene with an empty prompt, cropped to
  the paint size, undoable; /cam off stops; /add while live keeps then paints over
  the frame; /save while live keeps then saves; a request while live stops the
  camera; the status line shows the camera; no reply in time says so.
- [ ] Run, see them fail; implement; run, see them pass.

### Task 7: Docs

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `site/src/data/commands.ts`, `CLAUDE.md`

- [ ] Add the three commands to the README command table and install notes (the
  `cam` extra), `[Unreleased]` entries, the site's command list, and `camera.py`
  to the project guide's layout.
- [ ] Run all checks, and the site's `npm run check && npm run format:check && npm run build`.
