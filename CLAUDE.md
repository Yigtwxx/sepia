# sepia: project guide

sepia (always lowercase) is a Python CLI. `sepia` opens a prompt window; each request is turned into a photo prompt by Claude, painted by FLUX.2 [klein] 4B on Cloudflare Workers AI (or locally as a fallback), and shown as colored text characters in a second terminal window. PyPI distribution `sepia-cli`, command `sepia`, MIT. Design: `docs/superpowers/specs/2026-10-28-sepia-design.md` (the SVG pipeline in older history is obsolete).

## Stack

- Python 3.12+, uv (build backend `uv_build`), src layout.
- Runtime: anthropic, prompt-toolkit, rich, pillow, numpy, pydantic, platformdirs, python-dotenv.
- Optional extra `local`: torch, diffusers, transformers, accelerate, bitsandbytes (not on macOS). `[tool.uv.sources]` takes torch from the PyTorch cu130 index on Windows and Linux.
- Dev group: ruff, mypy (strict), pytest.

## Layout

- `src/sepia/cli.py`: argparse entry point; `--download`, `--version`, hidden `--viewer <session file>`.
- `src/sepia/repl.py`: the prompt window loop, slash commands, spinner, session folders, viewer relaunch.
- `src/sepia/chatbar.py`: the chat bar pinned to the bottom rows, with the slash-command menu above it.
- `src/sepia/ui.py`: wordmark, palette, spinner frames, replies, interface strings (English only).
- `src/sepia/director.py`: one Claude call per request; structured JSON reply (`message`, `prompt`, `edit`, `references`); maps API errors to `Failure`.
- `src/sepia/prompts/`: `director.md` (system prompt), `mature.md` (appended to it while `/mature` is on) and `request.md` (per-request template).
- `src/sepia/reference.py`: finds a reference picture for a named subject (Brave image search with `BRAVE_SEARCH_API_KEY`, else a link or page `og:image`), pasted links in requests, https and public hosts only.
- `src/sepia/painter.py`: `CloudflarePainter` (Workers AI, FLUX.2 [klein] 4B, multipart upload), `LocalPainter`, `FallbackPainter` (120 s cooldown after HTTP 429, off for the session when the day's free allocation is used up; `retry_primary` for `/api`), `build_painter`, `select_device`, model download.
- `src/sepia/picker.py`: arrow-key menu for commands with fixed options (`/style`, `/charset`, `/effort`, `/mature`).
- `src/sepia/usage.py`: totals for `/usage` (tokens, searches, estimated cost from list prices, pictures per source); `Ledger` keeps all-time totals in `usage.json` in the config dir, with a one-time estimate of earlier use from the prompt history and session folders.
- `src/sepia/scene.py`: `Scene` (requests, prompts, latest image, fixed seed) and `Canvas` (viewer size in cells).
- `src/sepia/raster.py`: autocontrast, saturation boost, cover-crop to the grid, letterbox for pictures shown as they are.
- `src/sepia/ascii_art.py`: pixels to `SymbolArt` (density ramps, Bayer dither, ink/fill colors, optional Sobel outlines) and to rich `Text`.
- `src/sepia/ipc.py`: HMAC-authenticated loopback channel, JSON messages only, session file.
- `src/sepia/launcher.py`: opens the viewer (Windows Terminal window with a purple "sepia" tab and a fragment profile, conhost fallback, Terminal.app via osascript).
- `src/sepia/viewer.py`: full-screen picture window; redraws on resize and on messages.
- `src/sepia/mouse.py`: pointer reports from the terminal (SGR mouse mode); `src/sepia/ripple.py`: the rings that spread from the pointer, drawn as ANSI over the changed cells only.
- `src/sepia/config.py`: settings from env and `.env` files, slash-command choices kept in `choices.json` (they win over `SEPIA_*`), key storage (`save_keys`), config dir.
- `src/sepia/keys.py`: the Anthropic and Cloudflare keys asked for on the first run and by `/keys`; hidden prompts, a key's state is only set or not set.
- `tests/`: one `test_<module>.py` per module, shared fixtures in `conftest.py`.
- `scripts/spike.py`: quality spike; `scripts/release_notes.py`: CHANGELOG section for a release; `scripts/site_art.py`: draws the landing page's plates and demo pictures with `ascii_art` (writes `site/src/data/art.generated.ts` and `site/public/art/`).
- `site/`: the landing page (Astro 7, static, deployed on Vercel with `site` as the project root, https://sepia-cli.vercel.app). Design: `docs/superpowers/specs/2026-10-29-landing-page-design.md`. Sources of its pictures: `site/images.manifest.json`, `site/scripts/sources/`.
- `docs/releasing.md`: release process (tag push, PyPI Trusted Publishing).

## Commands

```bash
uv sync --extra local          # dev install with the local painter (plain `uv sync` without it)
uv run sepia                   # run from the checkout
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
uv run python scripts/spike.py --chain "waterfall" "mountains"   # judge output by eye
uv run python scripts/spike.py --show spike-output               # re-render, no API calls
uv run python scripts/site_art.py                                # redraw the site's plates and pictures
```

The site (`site/`, Node 22.12+):

```bash
cd site && npm ci
npm run dev            # http://localhost:4321
npm run check && npm run format:check && npm run build
npm run glyphs         # Plex Mono outlines for the mark (after a font update)
npm run favicon        # raster favicons, from a fresh build
```

All four checks must pass. CI runs them on Windows and macOS without the local extra.

## Conventions

- Code, identifiers and comments in English. User-facing strings go in `ui.STRINGS` for both `en` and `tr`.
- Full type annotations; mypy strict on `src/`. ruff formats at 88 columns.
- Prompts for Claude live in `src/sepia/prompts/`, never inline in code.
- Secrets only from the environment or `.env` files. Never hardcode, print or log a key. Never open or read `.env`.
- The local extra is optional: import torch, diffusers and huggingface_hub inside functions, never at module level.
- Device order for the local model is CUDA, then MPS, then CPU (`painter.select_device`). Keep it.
- Windows and macOS are both first-class; Linux only needs to import and pass tests. Line endings are LF (`.gitattributes`).
- Tests: names `test_<unit>_<scenario>_<expected>`, every assert has a message, shared fixtures in `tests/conftest.py`, mock only external dependencies (Anthropic client, HTTP, subprocess, torch). No real API calls, windows or downloads in tests. An autouse fixture gives every test its own config folder, so nothing reaches the real one.
- Commits: Conventional Commits (`feat`, `fix`, `refactor`, `test`, `docs`, `chore`; `ci` for workflows), imperative summary of at most 72 characters, body explains why. Commit, push or tag only when asked.
- The version lives in `pyproject.toml` and `src/sepia/__init__.py`; bump both. User-visible changes go under `[Unreleased]` in `CHANGELOG.md`.
