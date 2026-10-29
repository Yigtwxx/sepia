# /save Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/save` writes the picture the viewer window shows, as colored characters, to a PNG in `Pictures/sepia/`.

**Architecture:** The prompt window redraws the viewer's picture itself: `Scene.image` goes through the viewer's own pipeline (`enhance` → `fit_image` → `image_to_art`) at the viewer's size (`Canvas`), and a new `snapshot.py` draws the resulting `SymbolArt` with Pillow onto a PNG, one 12x24 px cell per character. No IPC, no OS screenshot, so no tab bar or window frame.

**Tech Stack:** Python 3.12, Pillow 13 (`ImageDraw`, `ImageFont`), numpy, platformdirs (`user_pictures_path`), pytest.

Spec: `docs/superpowers/specs/2026-10-29-save-command-design.md`.

## Global Constraints

- Code, identifiers and comments in English; user-facing strings in `ui.STRINGS`.
- Full type annotations; `uv run mypy` (strict on `src/`) clean; ruff at 88 columns.
- Tests: names `test_<unit>_<scenario>_<expected>`, every assert has a message, no real windows or API calls; files written only under `tmp_path`.
- Pixel tests use Pillow's default font (`ImageFont.load_default(20)`), never a system font.
- Cell in the PNG: `SNAPSHOT_CELL_WIDTH = 12`, `SNAPSHOT_CELL_HEIGHT = 24`, `FONT_SIZE = 20`; `BACKGROUND = (0, 0, 0)`.
- Fonts, in order: `CascadiaMono.ttf`, `consola.ttf`, `Menlo.ttc`, `DejaVuSansMono.ttf`; else `ImageFont.load_default(size)`.
- File name: `f"{now:%Y-%m-%d_%H-%M-%S}.png"`, then `-2`, `-3`, … within the same second.
- Folder: `platformdirs.user_pictures_path() / "sepia"`.
- No commits, pushes or tags: the user commits (user and project CLAUDE.md). Each task ends with a check, not a commit.

## File Structure

- Create `src/sepia/snapshot.py`: fonts, drawing `SymbolArt` to an image, the full pipeline, saving with a unique name, the Pictures folder.
- Create `tests/test_snapshot.py`: tests for all of the above.
- Modify `src/sepia/repl.py`: the `/save` branch in `_handle` and a `_save` method.
- Modify `src/sepia/ui.py`: one `COMMANDS` line, three `STRINGS`.
- Modify `tests/test_ui.py`: `/save` is listed; its strings fill in.
- Modify `README.md` (commands table), `CHANGELOG.md` (`[Unreleased]`), `CLAUDE.md` (Layout).

---

### Task 1: Draw symbol art to an image

**Files:**
- Create: `src/sepia/snapshot.py`
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Consumes: `sepia.ascii_art.SymbolArt(chars: NDArray[str_], fg: RGBImage, bg: RGBImage | None)`.
- Produces: `Font = ImageFont.FreeTypeFont | ImageFont.ImageFont`; `load_font(size: int = FONT_SIZE, names: tuple[str, ...] = FONTS) -> Font`; `draw(art: SymbolArt, font: Font) -> Image.Image`; constants `SNAPSHOT_CELL_WIDTH`, `SNAPSHOT_CELL_HEIGHT`, `FONT_SIZE`, `BACKGROUND`, `FONTS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_snapshot.py`:

```python
import numpy as np
import pytest
from PIL import Image, ImageFont

from sepia import snapshot
from sepia.ascii_art import SymbolArt

RGB = tuple[int, int, int]


@pytest.fixture
def font() -> snapshot.Font:
    """Pillow's own font: pixel tests must not depend on the machine's fonts."""
    return ImageFont.load_default(snapshot.FONT_SIZE)


def _art(lines: list[str], fg: RGB, bg: RGB | None = None) -> SymbolArt:
    chars = np.array([list(line) for line in lines])
    shape = (*chars.shape, 3)
    fill = None if bg is None else np.full(shape, bg, np.uint8)
    return SymbolArt(chars, np.full(shape, fg, np.uint8), fill)


def _cell(picture: Image.Image, row: int, col: int) -> np.ndarray:
    w, h = snapshot.SNAPSHOT_CELL_WIDTH, snapshot.SNAPSHOT_CELL_HEIGHT
    return np.asarray(picture)[row * h : (row + 1) * h, col * w : (col + 1) * w]


def test_draw_size_is_one_snapshot_cell_per_character(font: snapshot.Font) -> None:
    picture = snapshot.draw(_art(["@@@", "@@@"], (255, 0, 0)), font)
    expected = (3 * snapshot.SNAPSHOT_CELL_WIDTH, 2 * snapshot.SNAPSHOT_CELL_HEIGHT)
    assert picture.size == expected, f"Expected {expected}, got {picture.size}"
    assert picture.mode == "RGB", f"Expected an RGB image, got {picture.mode}"


def test_draw_ink_space_stays_background_and_symbol_takes_fg(
    font: snapshot.Font,
) -> None:
    picture = snapshot.draw(_art(["@ "], (255, 0, 0)), font)
    space, symbol = _cell(picture, 0, 1), _cell(picture, 0, 0)
    assert (space == snapshot.BACKGROUND).all(), "A space must stay the background"
    assert symbol[..., 0].max() > 128, "The symbol must be drawn in its red fg"
    assert symbol[..., 1:].max() == 0, "Ink on black must add no other channel"


def test_draw_fill_space_is_its_cell_background(font: snapshot.Font) -> None:
    picture = snapshot.draw(_art([" "], (255, 255, 255), bg=(10, 20, 30)), font)
    assert (_cell(picture, 0, 0) == (10, 20, 30)).all(), "Fill must paint the bg"


def test_load_font_without_any_listed_font_uses_pillows_own() -> None:
    loaded = snapshot.load_font(20, names=("no-such-font-sepia.ttf",))
    default = ImageFont.load_default(20)
    assert isinstance(loaded, ImageFont.FreeTypeFont), f"Got {type(loaded)}"
    assert isinstance(default, ImageFont.FreeTypeFont), f"Got {type(default)}"
    assert loaded.getname() == default.getname(), f"Got {loaded.getname()}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_snapshot.py -v`
Expected: collection error, `ImportError: cannot import name 'snapshot' from 'sepia'`.

- [ ] **Step 3: Write the implementation**

Create `src/sepia/snapshot.py`:

```python
"""/save: the picture in the window, drawn as its characters, kept as a PNG."""

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from sepia.ascii_art import SymbolArt

SNAPSHOT_CELL_WIDTH = 12
SNAPSHOT_CELL_HEIGHT = 24
"""Pixels per cell in the PNG: a terminal cell's 1:2 shape, large enough to read."""
FONT_SIZE = 20
"""Cascadia Mono advances exactly one 12 px cell at this size."""
BACKGROUND = (0, 0, 0)
"""The viewer profile's background (see launcher.py), under `ink` art."""
FONTS = ("CascadiaMono.ttf", "consola.ttf", "Menlo.ttc", "DejaVuSansMono.ttf")
"""Monospace fonts tried in turn: Windows Terminal's default and Consolas, then the
macOS and Linux ones. Pillow looks each name up in the system's font folders."""

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


def load_font(size: int = FONT_SIZE, names: tuple[str, ...] = FONTS) -> Font:
    """The first of `names` this machine has, else Pillow's own font."""
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def draw(art: SymbolArt, font: Font) -> Image.Image:
    """`art` as an RGB image: each cell its background, its symbol centered on it,
    so even a proportional fallback font keeps to the grid."""
    width, height = SNAPSHOT_CELL_WIDTH, SNAPSHOT_CELL_HEIGHT
    if art.bg is None:
        picture = Image.new("RGB", (art.cols * width, art.rows * height), BACKGROUND)
    else:
        cells = np.repeat(np.repeat(art.bg, height, axis=0), width, axis=1)
        picture = Image.fromarray(cells)
    pen = ImageDraw.Draw(picture)
    for row, col in zip(*np.nonzero(art.chars != " "), strict=True):
        center = ((col + 0.5) * width, (row + 0.5) * height)
        color = tuple(int(v) for v in art.fg[row, col])
        pen.text(center, str(art.chars[row, col]), fill=color, font=font, anchor="mm")
    return picture
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_snapshot.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/sepia/snapshot.py tests/test_snapshot.py; uv run ruff format --check src/sepia/snapshot.py tests/test_snapshot.py; uv run mypy`
Expected: no errors. If mypy flags `center` (numpy integers), wrap as `(float((col + 0.5) * width), float((row + 0.5) * height))`.

---

### Task 2: The pipeline, saving and the Pictures folder

**Files:**
- Modify: `src/sepia/snapshot.py`
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Consumes: `load_font`, `draw`, `Font` (Task 1); `sepia.raster.enhance(image) -> Image.Image`; `sepia.raster.fit_image(image, width, height) -> RGBImage`; `sepia.ascii_art.image_to_art(pixels, cols, rows, style=..., charset=...)`, `CELL_WIDTH`, `CELL_HEIGHT`, `ArtStyle`, `Charset`; `sepia.scene.Canvas(cols, rows)`.
- Produces: `snapshot(image: Image.Image, canvas: Canvas, style: ArtStyle, charset: Charset, font: Font | None = None) -> Image.Image`; `save_snapshot(picture: Image.Image, folder: Path, now: datetime) -> Path`; `pictures_dir() -> Path`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_snapshot.py` (add `from datetime import datetime`, `from pathlib import Path` and `from sepia.scene import Canvas` to the imports at the top):

```python
NOON = datetime(2026, 10, 29, 12, 0, 5)


def test_snapshot_size_follows_the_canvas(font: snapshot.Font) -> None:
    photo = Image.new("RGB", (64, 64), (120, 80, 40))
    picture = snapshot.snapshot(photo, Canvas(10, 4), "fill", "classic", font=font)
    expected = (10 * snapshot.SNAPSHOT_CELL_WIDTH, 4 * snapshot.SNAPSHOT_CELL_HEIGHT)
    assert picture.size == expected, f"Expected {expected}, got {picture.size}"


def test_save_snapshot_missing_folder_is_created_and_named_after_the_time(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Pictures" / "sepia"
    path = snapshot.save_snapshot(Image.new("RGB", (4, 4)), folder, NOON)
    assert path == folder / "2026-10-29_12-00-05.png", f"Got {path}"
    assert path.is_file(), "The PNG must be written"


def test_save_snapshot_same_second_keeps_the_earlier_file(tmp_path: Path) -> None:
    first = snapshot.save_snapshot(Image.new("RGB", (4, 4), "red"), tmp_path, NOON)
    second = snapshot.save_snapshot(Image.new("RGB", (4, 4), "blue"), tmp_path, NOON)
    assert second == tmp_path / "2026-10-29_12-00-05-2.png", f"Got {second}"
    with Image.open(first) as kept:
        assert kept.getpixel((0, 0)) == (255, 0, 0), "The first file was overwritten"


def test_pictures_dir_is_a_sepia_folder_in_pictures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshot, "user_pictures_path", lambda: tmp_path)
    folder = snapshot.pictures_dir()
    assert folder == tmp_path / "sepia", f"Got {folder}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_snapshot.py -v`
Expected: the 4 new tests FAIL with `AttributeError: module 'sepia.snapshot' has no attribute 'snapshot'` (and `save_snapshot`, `user_pictures_path`); Task 1's 4 still pass.

- [ ] **Step 3: Write the implementation**

In `src/sepia/snapshot.py`, replace the import block with:

```python
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from platformdirs import user_pictures_path

from sepia.ascii_art import (
    CELL_HEIGHT,
    CELL_WIDTH,
    ArtStyle,
    Charset,
    SymbolArt,
    image_to_art,
)
from sepia.raster import enhance, fit_image
from sepia.scene import Canvas
```

Append at the end of the file:

```python
def snapshot(
    image: Image.Image,
    canvas: Canvas,
    style: ArtStyle,
    charset: Charset,
    font: Font | None = None,
) -> Image.Image:
    """`image` drawn the way the viewer draws it in a `canvas`-sized window."""
    pixels = fit_image(
        enhance(image), canvas.cols * CELL_WIDTH, canvas.rows * CELL_HEIGHT
    )
    art = image_to_art(pixels, canvas.cols, canvas.rows, style=style, charset=charset)
    return draw(art, load_font() if font is None else font)


def save_snapshot(picture: Image.Image, folder: Path, now: datetime) -> Path:
    """Save `picture` in `folder`, named after `now`, never over an earlier one."""
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{now:%Y-%m-%d_%H-%M-%S}"
    path, count = folder / f"{stem}.png", 1
    while path.exists():
        count += 1
        path = folder / f"{stem}-{count}.png"
    picture.save(path)
    return path


def pictures_dir() -> Path:
    """Where /save keeps pictures: a sepia folder in the user's Pictures."""
    return user_pictures_path() / "sepia"
```


- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_snapshot.py -v`
Expected: 8 passed.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff format src/sepia/snapshot.py tests/test_snapshot.py; uv run ruff check; uv run mypy`
Expected: no errors.

---

### Task 3: `/save` in the prompt window, with its words and docs

**Files:**
- Modify: `src/sepia/ui.py` (`STRINGS` after `"unknown"`, `COMMANDS` after the `/charset` line)
- Modify: `src/sepia/repl.py` (imports; `_handle` before the final `else`; new `_save` after `_handle`)
- Modify: `tests/test_ui.py`
- Modify: `README.md` (commands table, after `/charset`), `CHANGELOG.md` (`[Unreleased]`), `CLAUDE.md` (Layout, after `picker.py`)

**Interfaces:**
- Consumes: `snapshot(image, canvas, style, charset) -> Image.Image`, `save_snapshot(picture, folder, now) -> Path`, `pictures_dir() -> Path` (Task 2); `Repl.scene.image: Image.Image | None`, `Repl.canvas`, `Repl.style`, `Repl.charset`, `Repl.transcript.say`, `ui.reply(message, detail="", *, failed=False)`.
- Produces: the `/save` command; `STRINGS` keys `save_empty`, `saved`, `save_failed`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui.py`:

```python
def test_words_commands_include_save() -> None:
    names = [usage.split()[0] for usage, _ in ui.Words().commands]
    assert "/save" in names, f"Got {names}"


def test_words_save_replies_fill_in_the_path_and_the_error() -> None:
    words = ui.Words()
    saved = words("saved", path="C:/Pictures/sepia/a.png")
    failed = words("save_failed", error="disk full")
    assert saved == "Saved to C:/Pictures/sepia/a.png", f"Got {saved!r}"
    assert failed == "Could not save the picture: disk full", f"Got {failed!r}"
    assert words("save_empty"), "The empty-scene reply must say something"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ui.py -v -k save`
Expected: 2 FAIL (`'/save' in names` false; `KeyError: 'saved'`).

- [ ] **Step 3: Add the words**

In `src/sepia/ui.py`, after `"unknown": "No such command {command}",` add:

```python
    "save_empty": "Nothing to save yet: describe a picture first",
    "saved": "Saved to {path}",
    "save_failed": "Could not save the picture: {error}",
```

In `COMMANDS`, after `("/charset [classic|symbols]", "choose the characters that draw it"),` add:

```text
    ("/save", "save the picture in the window to Pictures/sepia"),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ui.py -v`
Expected: all pass.

- [ ] **Step 5: Wire `/save` into the prompt window**

In `src/sepia/repl.py`, add after `from sepia.scene import Canvas, Scene`:

```python
from sepia.snapshot import pictures_dir, save_snapshot, snapshot
```

In `_handle`, before the final `else:` (the `unknown` branch), add:

```python
        elif command.name == "save":
            self._save()
```

After the `_handle` method (before `_switch_painter`), add:

```python
    def _save(self) -> None:
        """Keep the picture in the window, drawn as its characters, as a PNG."""
        if self.scene.image is None:
            self.transcript.say(ui.reply(self.words("save_empty"), failed=True))
            return
        picture = snapshot(self.scene.image, self.canvas, self.style, self.charset)
        try:
            path = save_snapshot(picture, pictures_dir(), datetime.now())
        except OSError as exc:
            failed = self.words("save_failed", error=exc)
            self.transcript.say(ui.reply(failed, failed=True))
            return
        self.transcript.say(ui.reply(self.words("saved", path=path)))
```

`datetime` is already imported in `repl.py` (`from datetime import datetime`).

- [ ] **Step 6: Update the docs**

`README.md`, in the commands table after the `/charset` row:

```markdown
| `/save` | Save the picture in the viewer window as a PNG in the `sepia` folder of your Pictures folder: its colored characters as the window shows them, without the tab bar or frame, named after the time. |
```

`CHANGELOG.md`, under `## [Unreleased]`:

```markdown
### Added

- `/save` keeps the picture in the viewer window as a PNG in the `sepia`
  folder of the Pictures folder: its colored characters as the window shows
  them, without the tab bar or frame, named after the time.
```

`CLAUDE.md`, in Layout after the `picker.py` line:

```markdown
- `src/sepia/snapshot.py`: `/save`; draws the window's symbol art to a PNG (12x24 px cells, a system monospace font, Pillow's own as the fallback) in `Pictures/sepia`.
```

- [ ] **Step 7: Run the full checks**

Run: `uv run ruff check; uv run ruff format --check; uv run mypy; uv run pytest`
Expected: all clean, all tests pass.

---

### Task 4: Check the PNG by eye

**Files:** none in the repo; a probe script in the scratchpad.

- [ ] **Step 1: Render the newest saved session picture both ways**

Write a script in the scratchpad that takes the newest `NN.png` under `config_dir() / "sessions"`, runs `snapshot(image, Canvas(110, 36), style, "classic")` for `ink` and `fill`, and saves both with `save_snapshot` into the scratchpad (not the real Pictures folder). Run it with `uv run python <script>`.

- [ ] **Step 2: Look at both PNGs**

Open them with the Read tool. Expected: 1320x864 px, the picture recognizable, characters on a black ground (`ink`) or on colored cells (`fill`), no tab bar or frame, nothing cut off at the edges.

- [ ] **Step 3: Report**

Tell the user the results and the files changed; leave the commit to them. A suggested message: `feat: save the picture in the window with /save`.
