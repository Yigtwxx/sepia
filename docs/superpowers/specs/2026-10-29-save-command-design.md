# /save: keep the picture in the window as a PNG

## Goal

`/save` writes the picture the viewer window shows, as colored characters, to a PNG
in the user's Pictures folder (`Pictures/sepia/`). Only the picture: no tab bar, no
window frame. One file per `/save`; the painted photo itself is not saved.

## Approach

The prompt window draws the PNG itself. It already holds everything the viewer
uses: the latest picture (`Scene.image`), the style, the charset and the window's
size in cells (`Canvas`, updated from the viewer's `size` messages). The viewer's
pipeline is deterministic, so running it again gives the same `SymbolArt`:

```
Scene.image -> raster.enhance -> raster.fit_image(cols * CELL_WIDTH, rows * CELL_HEIGHT)
            -> ascii_art.image_to_art(cols, rows, style, charset) -> snapshot.draw -> PNG
```

This needs no IPC and works while the viewer window is closed. Rejected: asking the
viewer over IPC (a round trip, and nothing to ask when the window is closed) and an
OS screenshot of the window (breaks on covered windows, DPI scaling, Terminal.app).

## Units

### `src/sepia/snapshot.py` (new)

- `SNAPSHOT_CELL_WIDTH = 12`, `SNAPSHOT_CELL_HEIGHT = 24`, `FONT_SIZE = 20`: pixels
  per cell in the PNG, the 1:2 shape of a terminal cell. 110x36 cells -> 1320x864.
- `BACKGROUND = (0, 0, 0)`: the viewer profile's background (`launcher.py`).
- `FONTS`: monospace fonts tried in order: Cascadia Mono, Consolas (Windows), Menlo
  (macOS), DejaVu Sans Mono (Linux), as file names and known paths per platform.
- `load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont`: the first
  font in `FONTS` that loads; otherwise `ImageFont.load_default`, which is
  proportional (its `@` is 17 px at 20 px), so it is loaded small enough for the
  widest ramp symbol to fit a 12 px cell.
- `draw(art: SymbolArt, font) -> Image.Image`: an RGB image of
  `art.cols * SNAPSHOT_CELL_WIDTH` x `art.rows * SNAPSHOT_CELL_HEIGHT`. Each cell is
  filled with `art.bg` (`fill` style) or `BACKGROUND` (`ink`), then its character
  drawn in `art.fg`, centered in the cell (anchor `"mm"`), so a proportional fallback
  font still lines up. Spaces are skipped.
- `snapshot(image: Image.Image, canvas: Canvas, style: ArtStyle, charset: Charset)
  -> Image.Image`: the pipeline above, then `draw`.
- `save_snapshot(picture: Image.Image, folder: Path, now: datetime) -> Path`:
  creates `folder` if needed and saves `folder / f"{now:%Y-%m-%d_%H-%M-%S}.png"`; a
  second save within the same second gets `-2`, `-3`, ... so nothing is overwritten.
- `pictures_dir() -> Path`: `platformdirs.user_pictures_path() / "sepia"`.

### `src/sepia/repl.py`

`/save` in `_handle`: with an empty scene, a failed reply `save_empty`. Otherwise
`snapshot(self.scene.image, self.canvas, self.style, self.charset)`, then
`save_snapshot(..., pictures_dir(), datetime.now())`, and a reply `saved` with the
path. An `OSError` while saving gives a failed reply `save_failed` with the error.

### `src/sepia/ui.py`

- Help line: `("/save", "save the picture in the window to Pictures/sepia")`, after
  `/charset`.
- Strings: `save_empty` ("Nothing to save yet: describe a picture first"),
  `saved` ("Saved to {path}"), `save_failed` ("Could not save the picture: {error}").

### `CHANGELOG.md`

Under `[Unreleased]`: `/save` keeps the picture in the window as a PNG in
`Pictures/sepia`.

## Errors

- No picture yet: the `save_empty` reply, nothing written.
- Folder or file cannot be written (`OSError`): the `save_failed` reply; sepia goes on.
- No font in `FONTS` found: Pillow's default font, no message.

## Tests (`tests/test_snapshot.py`, `tests/test_ui.py`)

- `draw` gives an image of cols x 12 by rows x 24 pixels.
- `ink` art: a space cell stays `BACKGROUND`; a `@` cell holds pixels of its fg color.
- `fill` art: a space cell is its bg color.
- `load_font` with no font in `FONTS` found falls back to Pillow's default.
- `snapshot` of a solid picture on a small canvas has the canvas's pixel size.
- `save_snapshot` creates a missing folder, names the file after the time, and a
  second save in the same second does not overwrite the first.
- `Words.commands` include `/save`.

No windows are opened. Tests that check pixels use Pillow's default font, so they
do not depend on the fonts a machine has; `save_snapshot` writes to `tmp_path`.
