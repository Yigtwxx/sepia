"""Quality spike: run prompts through the whole pipeline and save previews.

    uv run python scripts/spike.py "night city"                  # one picture
    uv run python scripts/spike.py --chain "waterfall" "mountains"  # one evolving scene
    uv run python scripts/spike.py --show spike-output           # re-show, no API calls

Each picture is saved to spike-output/ with PNG previews of its symbol art (the same
characters and colors, drawn with a terminal font) in both styles.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from rich.console import Console

from sepia.ascii_art import CELL_HEIGHT, CELL_WIDTH, ArtStyle, SymbolArt, image_to_art
from sepia.ascii_art import to_text as art_text
from sepia.config import (
    api_key,
    load_environment,
    load_settings,
    pollinations_key,
    search_key,
)
from sepia.director import Director, DirectorError, create_client
from sepia.painter import PainterError, Painting, build_painter, image_size
from sepia.raster import enhance, fit_image, letterbox
from sepia.reference import find_subject
from sepia.scene import Canvas, Scene

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
    parser.add_argument("--show", type=Path, help="re-render saved pictures only")
    parser.add_argument("--cols", type=int, default=160)
    parser.add_argument("--rows", type=int, default=50)
    parser.add_argument("--out", type=Path, default=Path("spike-output"))
    args = parser.parse_args()
    console = Console(highlight=False)
    canvas = Canvas(args.cols, args.rows)

    if args.show:
        for path in sorted(args.show.glob("*.jpg")) + sorted(args.show.glob("*.png")):
            if "-ink" in path.stem or "-fill" in path.stem:
                continue
            show(console, path, canvas)
        return 0

    load_environment()
    settings = load_settings()
    key = api_key()
    if key is None:
        console.print("ANTHROPIC_API_KEY is not set (put it in .env)")
        return 1
    director = Director(create_client(key), settings.model, settings.effort)
    painter, _ = build_painter(pollinations_key(), settings.image_model)
    brave = search_key()
    args.out.mkdir(exist_ok=True)
    scene = Scene()
    for index, request in enumerate(args.prompts, 1):
        if not args.chain:
            scene.reset()
        # The same steps as the prompt window: find a named subject's picture, show
        # it for a bare name, else let Claude see it before painting.
        size = image_size(canvas.aspect)
        try:
            direction = director.direct(request, scene)
            found, _ = find_subject(direction.subject, direction.references, brave)
            if found is not None and direction.show:
                image = letterbox(found.cutout or found.image, *size)
                painting = Painting(image, "api", 0.0)
            else:
                if found is not None:
                    direction = director.direct(request, scene, found.image)
                reference = scene.image if direction.edit else None
                painting = painter.paint(
                    direction.prompt,
                    size,
                    scene.seed,
                    reference,
                    found or scene.likeness,
                )
        except (DirectorError, PainterError) as exc:
            console.print(f"[red]{request!r} failed: {exc}[/red]")
            continue
        likeness = found or scene.likeness
        scene.record(request, direction.prompt, painting.image, likeness)
        path = args.out / f"{index:02d}-{slug(request)}.png"
        painting.image.save(path)
        meta = {
            "request": request,
            "message": direction.message,
            "prompt": direction.prompt,
            "edit": direction.edit,
            "references": list(direction.references),
            "subject": direction.subject,
            "show": direction.show,
            "likeness": likeness.url if likeness else None,
            "source": painting.source,
            "paint_seconds": round(painting.seconds, 1),
            "tokens": [direction.input_tokens, direction.output_tokens],
        }
        path.with_suffix(".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(json.dumps(meta, ensure_ascii=False))
        show(console, path, canvas)
    return 0


def art_for(path: Path, canvas: Canvas, style: ArtStyle) -> SymbolArt:
    picture = enhance(Image.open(path))
    pixels = fit_image(picture, canvas.cols * CELL_WIDTH, canvas.rows * CELL_HEIGHT)
    return image_to_art(pixels, canvas.cols, canvas.rows, style=style)


def show(console: Console, path: Path, canvas: Canvas) -> None:
    for style in STYLES:
        art = art_for(path, canvas, style)
        save_png(art, path.with_name(f"{path.stem}-{style}.png"))
        console.rule(f"{path.stem} [{style}]")
        console.print(art_text(art))


def save_png(art: SymbolArt, path: Path, cell_w: int = 7, cell_h: int = 14) -> None:
    """Rasterize the symbol art the way a dark terminal would show it."""
    font = next(
        (ImageFont.truetype(f, cell_h - 3) for f in FONTS if Path(f).exists()),
        ImageFont.load_default(),
    )
    image = Image.new("RGB", (art.cols * cell_w, art.rows * cell_h), (0, 0, 0))
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
