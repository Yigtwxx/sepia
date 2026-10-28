"""Quality spike: paint prompts with Claude and show them in both symbol styles.

    uv run python scripts/spike.py "night city"                 # one picture
    uv run python scripts/spike.py --chain "waterfall" "mountains"  # one evolving scene
    uv run python scripts/spike.py --show spike-output          # re-show, no API calls

Each drawing is saved to spike-output/ as SVG, plus PNG previews of the symbol art
(the same characters and colors, rasterized with a terminal font) for both styles.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from rich.console import Console

from sepia.artist import Artist, ArtistError, create_client
from sepia.ascii_art import (
    CELL_HEIGHT,
    CELL_WIDTH,
    ArtStyle,
    SymbolArt,
    image_to_art,
    to_text,
)
from sepia.config import api_key, load_environment, load_settings
from sepia.raster import render_svg
from sepia.scene import Canvas, Scene

PRICE_PER_MTOK = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0)}
FONTS = [
    "C:/Windows/Fonts/CascadiaMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]
STYLES: tuple[ArtStyle, ...] = ("ink", "fill")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prompts", nargs="*")
    parser.add_argument("--chain", action="store_true", help="build one scene")
    parser.add_argument("--show", type=Path, help="re-render saved SVGs only")
    parser.add_argument("--cols", type=int, default=100)
    parser.add_argument("--rows", type=int, default=32)
    parser.add_argument("--out", type=Path, default=Path("spike-output"))
    args = parser.parse_args()
    console = Console(highlight=False)
    canvas = Canvas(args.cols, args.rows)

    if args.show:
        for svg_path in sorted(args.show.glob("*.svg")):
            svg = svg_path.read_text(encoding="utf-8")
            for style in STYLES:
                art = art_for(svg, canvas, style)
                save_png(art, svg_path.with_name(f"{svg_path.stem}-{style}.png"))
            show(console, svg_path.stem, svg, canvas)
        return 0

    load_environment()
    settings = load_settings()
    key = api_key()
    if key is None:
        console.print("ANTHROPIC_API_KEY is not set (put it in .env)")
        return 1
    artist = Artist(create_client(key), settings.model, settings.effort)
    args.out.mkdir(exist_ok=True)
    scene = Scene()
    total = 0.0
    for index, prompt in enumerate(args.prompts, 1):
        if not args.chain:
            scene.reset()
        started = time.perf_counter()
        try:
            drawing = artist.draw(prompt, scene, canvas)
        except ArtistError as exc:
            console.print(f"[red]{prompt!r} failed: {exc.failure}[/red]")
            continue
        seconds = time.perf_counter() - started
        scene.record(prompt, drawing.svg)
        price_in, price_out = PRICE_PER_MTOK.get(settings.model, (0.0, 0.0))
        cost = (
            drawing.input_tokens * price_in + drawing.output_tokens * price_out
        ) / 1e6
        total += cost
        name = f"{index:02d}-{slug(prompt)}"
        (args.out / f"{name}.svg").write_text(drawing.svg, encoding="utf-8")
        meta = {
            "prompt": prompt,
            "message": drawing.message,
            "model": settings.model,
            "effort": settings.effort,
            "input_tokens": drawing.input_tokens,
            "output_tokens": drawing.output_tokens,
            "cost_usd": round(cost, 4),
            "seconds": round(seconds, 1),
            "svg_chars": len(drawing.svg),
        }
        (args.out / f"{name}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )
        console.print(f"[bold]{prompt}[/bold] -> {drawing.message}")
        console.print(f"  {json.dumps(meta, ensure_ascii=False)}")
        for style in STYLES:
            art = art_for(drawing.svg, canvas, style)
            save_png(art, args.out / f"{name}-{style}.png")
        show(console, name, drawing.svg, canvas)
    console.print(f"total ${total:.3f}")
    return 0


def art_for(svg: str, canvas: Canvas, style: ArtStyle) -> SymbolArt:
    pixels = render_svg(svg, canvas.cols * CELL_WIDTH, canvas.rows * CELL_HEIGHT)
    return image_to_art(pixels, canvas.cols, canvas.rows, style)


def show(console: Console, title: str, svg: str, canvas: Canvas) -> None:
    for style in STYLES:
        console.rule(f"{title} [{style}]")
        console.print(to_text(art_for(svg, canvas, style)))


def save_png(art: SymbolArt, path: Path, cell_w: int = 10, cell_h: int = 20) -> None:
    """Rasterize the symbol art the way a dark terminal would show it."""
    font = next(
        (ImageFont.truetype(f, cell_h - 3) for f in FONTS if Path(f).exists()),
        ImageFont.load_default(),
    )
    image = Image.new("RGB", (art.cols * cell_w, art.rows * cell_h), (12, 12, 16))
    draw = ImageDraw.Draw(image)
    for row in range(art.rows):
        for col in range(art.cols):
            x, y = col * cell_w, row * cell_h
            if art.bg is not None:
                bg = tuple(int(v) for v in art.bg[row, col])
                draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), fill=bg)
            fg = tuple(int(v) for v in art.fg[row, col])
            draw.text((x, y), str(art.chars[row, col]), font=font, fill=fg)
    image.save(path)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30] or "scene"


if __name__ == "__main__":
    sys.exit(main())
