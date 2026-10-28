# sepia: project guide

sepia (always lowercase) is a Python CLI. `sepia` opens a prompt window; each request is turned into a photo prompt by Claude, painted by Pollinations (or FLUX.2 [klein] 4B locally as a fallback), and shown as colored text characters in a second terminal window. PyPI distribution `sepia-cli`, command `sepia`, MIT. Design: `docs/superpowers/specs/2026-10-28-sepia-design.md` (the SVG pipeline in older history is obsolete).

## Stack

- Python 3.12+, uv (build backend `uv_build`), src layout.
- Runtime: anthropic, prompt-toolkit, rich, pillow, numpy, pydantic, platformdirs, python-dotenv.
- Optional extra `local`: torch, diffusers, transformers, accelerate, bitsandbytes (not on macOS). `[tool.uv.sources]` takes torch from the PyTorch cu130 index on Windows and Linux.
- Dev group: ruff, mypy (strict), pytest.

## Layout

- `src/sepia/cli.py`: argparse entry point; `--download`, `--version`, hidden `--viewer <session file>`.
- `src/sepia/repl.py`: the prompt window loop, slash commands, spinner, session folders, viewer relaunch.
- `src/sepia/ui.py`: wordmark, palette, spinner frames, replies, interface strings (English only).
- `src/sepia/director.py`: one Claude call per request; structured JSON reply (`message`, `prompt`, `edit`); maps API errors to `Failure`.
- `src/sepia/prompts/`: `director.md` (system prompt) and `request.md` (per-request template).
- `src/sepia/painter.py`: `ApiPainter` (Pollinations), `LocalPainter` (FLUX.2 [klein]), `FallbackPainter` with 120 s cooldown, `select_device`, model download.
- `src/sepia/scene.py`: `Scene` (requests, prompts, latest image, fixed seed) and `Canvas` (viewer size in cells).
- `src/sepia/raster.py`: autocontrast, saturation boost, cover-crop to the grid.
- `src/sepia/ascii_art.py`: pixels to `SymbolArt` (density ramps, Bayer dither, ink/fill colors, optional Sobel outlines) and to rich `Text`.
- `src/sepia/ipc.py`: HMAC-authenticated loopback channel, JSON messages only, session file.
- `src/sepia/launcher.py`: opens the viewer (Windows Terminal focus mode with a fragment profile, conhost fallback, Terminal.app via osascript).
- `src/sepia/viewer.py`: full-screen picture window; redraws on resize and on messages.
- `src/sepia/config.py`: settings from env and `.env` files, key storage, config dir.
- `tests/`: one `test_<module>.py` per module, shared fixtures in `conftest.py`.
- `scripts/spike.py`: quality spike; `scripts/release_notes.py`: CHANGELOG section for a release.
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
- Tests: names `test_<unit>_<scenario>_<expected>`, every assert has a message, shared fixtures in `tests/conftest.py`, mock only external dependencies (Anthropic client, HTTP, subprocess, torch). No real API calls, windows or downloads in tests.
- Commits: Conventional Commits (`feat`, `fix`, `refactor`, `test`, `docs`, `chore`; `ci` for workflows), imperative summary of at most 72 characters, body explains why. Commit, push or tag only when asked.
- The version lives in `pyproject.toml` and `src/sepia/__init__.py`; bump both. User-visible changes go under `[Unreleased]` in `CHANGELOG.md`.
