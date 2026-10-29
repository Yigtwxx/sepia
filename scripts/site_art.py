"""Draw the landing page's pictures with sepia's own code.

    uv run python scripts/site_art.py          # from the repository root
    npm run images                             # the same, from site/

Two kinds of picture, both listed in site/images.manifest.json:

- Plates: public-domain engravings of cephalopods. Each is downloaded once into
  site/.cache/, cleaned to dark lines on white, then inverted and drawn the way the
  viewer draws a photo, so its densest characters fall on the engraved lines. The
  page sets them in ink on paper.
- Pictures: real sepia output (scripts/spike.py), drawn exactly as the viewer
  window draws them, in both character sets. Their cell colours go to
  site/public/art/<id>.json for the canvas, which applies the ink and fill
  styles itself (site/src/lib/ramps.ts mirrors the constants used here).

Everything the page needs at build time is written to
site/src/data/art.generated.ts; both outputs are committed.
"""

import base64
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, TypedDict

import numpy as np
from PIL import Image

# The page draws what the viewer draws, so it uses the viewer's own steps. These
# helpers are private to the package; this script is their only outside reader.
from sepia.ascii_art import (
    _RAMP_ARRAYS,
    CELL_HEIGHT,
    CELL_WIDTH,
    _cell_mean,
    _dither,
    _linear_to_srgb,
    _luma,
    _ramp_index,
    _srgb_to_linear,
    _stretch,
    image_to_art,
)
from sepia.raster import enhance, fit_image

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
MANIFEST = SITE / "images.manifest.json"
CACHE = SITE / ".cache"
PUBLIC_ART = SITE / "public" / "art"
GENERATED = SITE / "src" / "data" / "art.generated.ts"
# Wikimedia asks automated clients to name themselves and a way to reach them.
USER_AGENT = "sepia-site/0.1 (https://github.com/Yigtwxx/sepia; image build script)"


class Plate(TypedDict, total=False):
    id: str
    title: str
    author: str
    year: str
    source: str
    page_url: str
    file_url: str
    licence: str
    licence_url: str
    alt: str
    crop: list[float]
    erase: list[list[float]]
    levels: list[float]
    gamma: float
    cols: int


class Picture(TypedDict):
    id: str
    file: str
    cols: int
    rows: int


def download(plate: Plate) -> Path:
    """The plate's original file, fetched once into the cache.

    Several plates can crop one file, so the cache is keyed by the file's name.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    name = urllib.parse.unquote(plate["file_url"].rsplit("/", 1)[-1])
    path = CACHE / name
    if not path.exists():
        request = urllib.request.Request(
            plate["file_url"], headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            path.write_bytes(response.read())
    return path


SPECK = 0.12
"""Density under which a cell counts as blank paper when looking for neighbours."""


def despeckle(density: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Blank the faint cells that have no inked neighbour.

    Foxing and paper grain survive the levels as lone light symbols scattered over
    the sheet; a mark on the animal always has company, a speck of dirt does not.
    """
    inked = (density > SPECK).astype(np.int32)
    padded = np.pad(inked, 1)
    rows, cols = density.shape
    neighbours = sum(
        padded[1 + dy : 1 + dy + rows, 1 + dx : 1 + dx + cols]
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if dy or dx
    )
    lonely = (neighbours < 2) & (density < 0.45)
    cleaned: np.ndarray[Any, Any] = np.where(lonely, 0.0, density)
    return cleaned


def draw_plate(plate: Plate) -> dict[str, Any]:
    """Characters for an engraving: dense on the lines, blank on the paper."""
    Image.MAX_IMAGE_PIXELS = None  # the scans are large, and they are ours to trust
    image = Image.open(download(plate)).convert("L")
    width, height = image.size
    # Letters and plate numbers printed beside a figure are painted out as paper.
    for x0, y0, x1, y1 in plate.get("erase", []):
        image.paste(
            255,
            (
                round(x0 * width),
                round(y0 * height),
                round(x1 * width),
                round(y1 * height),
            ),
        )
    left, top, right, bottom = plate.get("crop", [0.0, 0.0, 1.0, 1.0])
    image = image.crop(
        (
            round(left * width),
            round(top * height),
            round(right * width),
            round(bottom * height),
        )
    )
    # Old paper is never white: levels push it there, so it draws as blank cells
    # instead of a haze of light symbols, and push the darkest lines to black.
    black, white = plate.get("levels", [0.08, 0.82])
    grey = np.asarray(image, dtype=np.float32) / 255.0
    grey = np.clip((grey - black) / (white - black), 0.0, 1.0)
    inverted = Image.fromarray(np.rint((1.0 - grey) * 255).astype(np.uint8))

    cols = plate.get("cols", 96)
    rows = max(
        1, round(cols * inverted.height / inverted.width * CELL_WIDTH / CELL_HEIGHT)
    )
    pixels = fit_image(inverted, cols * CELL_WIDTH, rows * CELL_HEIGHT)
    srgb = pixels.astype(np.float32) / 255.0
    cell_h, cell_w = CELL_HEIGHT, CELL_WIDTH
    cell_color = _linear_to_srgb(
        _cell_mean(_srgb_to_linear(srgb), rows, cell_h, cols, cell_w)
    )
    # The viewer lifts dark surfaces with a 0.5 gamma; an engraving's blank paper
    # has to stay blank, so a plate keeps more of the curve.
    density = _stretch(_luma(cell_color)) ** plate.get("gamma", 0.85)
    density = despeckle(density)
    ramp_chars, ramp_density = _RAMP_ARRAYS["classic"]
    chars = ramp_chars[_ramp_index(_dither(density), ramp_density)]
    lines = ["".join(row).rstrip() for row in chars]
    return {
        "id": plate["id"],
        "cols": cols,
        "rows": rows,
        "text": "\n".join(lines),
        "alt": plate["alt"],
        "credit": {
            "title": plate["title"],
            "author": plate["author"],
            "year": plate.get("year", ""),
            "source": plate["source"],
            "page_url": plate["page_url"],
            "licence": plate["licence"],
            "licence_url": plate["licence_url"],
        },
    }


def draw_picture(picture: Picture) -> dict[str, Any]:
    """A spike picture as the viewer draws it, plus the colours the canvas needs."""
    source = SITE / picture["file"]
    cols, rows = picture["cols"], picture["rows"]
    pixels = fit_image(
        enhance(Image.open(source)), cols * CELL_WIDTH, rows * CELL_HEIGHT
    )
    srgb = pixels.astype(np.float32) / 255.0
    linear = _srgb_to_linear(srgb)
    cell_color = _linear_to_srgb(
        _cell_mean(linear, rows, CELL_HEIGHT, cols, CELL_WIDTH)
    )
    weight = (_luma(linear) ** 2 + 1e-6)[..., None]
    glow = _linear_to_srgb(
        _cell_mean(linear * weight, rows, CELL_HEIGHT, cols, CELL_WIDTH)
        / _cell_mean(weight, rows, CELL_HEIGHT, cols, CELL_WIDTH)
    )
    art: dict[str, Any] = {"id": picture["id"], "cols": cols, "rows": rows}
    for charset in ("classic", "symbols"):
        drawn = image_to_art(pixels, cols, rows, style="ink", charset=charset)
        art[charset] = "\n".join(drawn.lines())
    meta_path = source.with_suffix(".json")
    meta = (
        json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    )
    colours = {
        "id": picture["id"],
        "cols": cols,
        "rows": rows,
        "cell": encode(cell_color),
        "glow": encode(glow),
        # What the viewer itself prints, for checking the page's ink and fill colours.
        "ink": encode_bytes(image_to_art(pixels, cols, rows, style="ink").fg),
    }
    PUBLIC_ART.mkdir(parents=True, exist_ok=True)
    (PUBLIC_ART / f"{picture['id']}.json").write_text(
        json.dumps(colours, separators=(",", ":")), encoding="utf-8"
    )
    art["request"] = meta.get("request", picture["id"])
    art["message"] = meta.get("message", "")
    art["painter"] = meta.get("source", "")
    art["seconds"] = meta.get("paint_seconds", 0)
    return art


def encode(colour: np.ndarray[Any, Any]) -> str:
    """sRGB floats in 0..1, rounded the way the viewer rounds them, as base64."""
    return encode_bytes(np.clip(np.rint(colour * 255.0), 0, 255).astype(np.uint8))


def encode_bytes(colour: np.ndarray[Any, Any]) -> str:
    return base64.b64encode(np.ascontiguousarray(colour).tobytes()).decode("ascii")


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    plates = {p["id"]: draw_plate(p) for p in manifest["plates"]}
    pictures = {p["id"]: draw_picture(p) for p in manifest["pictures"]}
    header = (
        "/* Generated by scripts/site_art.py from images.manifest.json: "
        "do not edit. */\n"
    )
    body = (
        "export interface Credit {\n"
        "    title: string;\n    author: string;\n    year: string;\n"
        "    source: string;\n    page_url: string;\n"
        "    licence: string;\n    licence_url: string;\n}\n"
        "export interface PlateArt {\n"
        "    id: string;\n    cols: number;\n    rows: number;\n"
        "    text: string;\n    alt: string;\n    credit: Credit;\n}\n"
        "export interface PictureArt {\n"
        "    id: string;\n    cols: number;\n    rows: number;\n"
        "    classic: string;\n    symbols: string;\n    request: string;\n"
        "    message: string;\n    painter: string;\n    seconds: number;\n}\n"
        f"export const plates: Record<string, PlateArt> = {json.dumps(plates)};\n"
        f"export const pictures: Record<string, PictureArt> = {json.dumps(pictures)};\n"
    )
    GENERATED.write_text(header + body, encoding="utf-8")
    print(
        f"{len(plates)} plates, {len(pictures)} pictures -> "
        f"{GENERATED.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
