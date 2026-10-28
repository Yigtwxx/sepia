# Contributing to sepia

sepia is developed on both Windows and macOS, and CI checks both. Everything below works on either system unless a step says otherwise.

## Setup

Install [uv](https://docs.astral.sh/uv/) and Git. uv reads `.python-version` and provides Python 3.12 if needed.

```bash
git clone https://github.com/Yigtwxx/sepia && cd sepia
uv sync --extra local
```

`uv sync` installs sepia in editable mode together with the `dev` group (ruff, mypy, pytest). `--extra local` adds the local painter (torch, diffusers, transformers, accelerate, bitsandbytes). You do not need an extra index for it: `[tool.uv.sources]` in `pyproject.toml` already takes torch from the PyTorch CUDA 13.0 index on Windows and Linux, and from PyPI (with MPS) on macOS. bitsandbytes is skipped on macOS.

The local extra is about 3 GB. If you do not work on the local painter, a plain `uv sync` is enough; CI does the same, and the tests stub the local extra.

Add your keys for development:

```bash
# macOS
cp .env.example .env
```

```powershell
# Windows (PowerShell)
Copy-Item .env.example .env
```

Then set `ANTHROPIC_API_KEY` (and optionally `POLLINATIONS_KEY`) in `.env`. The file is ignored by Git; never commit it, and never paste a key into code, tests, logs or issues.

Run sepia from the checkout:

```bash
uv run sepia
uv run sepia --download   # only if you work on the local painter
```

Line endings are LF on every platform: `.gitattributes` sets `* text=auto eol=lf`. Configure your editor to keep LF.

## Checks

All four must pass before a pull request is merged. CI runs them on `windows-latest` and `macos-latest`.

```bash
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```

`uv run ruff format` and `uv run ruff check --fix` fix most findings.

## Quality spike

Rendering and prompt changes are judged by eye. `scripts/spike.py` runs requests through the whole pipeline (director, painter, symbol conversion) without the two windows, prints the result, and saves the picture, its metadata and PNG previews of both styles to `spike-output/` (ignored by Git):

```bash
uv run python scripts/spike.py --chain "waterfall" "mountains"   # one evolving scene
uv run python scripts/spike.py "night city"                      # one picture
uv run python scripts/spike.py --show spike-output               # re-render saved pictures, no API calls
```

`--cols` and `--rows` set the grid size (default 160x50). The spike needs `ANTHROPIC_API_KEY` in the environment or `.env`.

## Code

- Code, identifiers and comments are in English. User-facing strings live in `src/sepia/ui.py` and are English only.
- Type annotations everywhere; mypy runs in strict mode on `src/`.
- ruff formats at 88 columns and lints with the rule set in `pyproject.toml`.
- Prompts for Claude live in `src/sepia/prompts/` as Markdown files, not inline in code.
- Secrets come only from the environment or `.env` files.
- The local extra is optional. Import torch, diffusers and huggingface_hub inside the functions that need them, never at module level, so the base install keeps working.
- The local model picks its device in the order CUDA, then MPS, then CPU (`painter.select_device`). Keep that order.

## Tests

- pytest, in `tests/`, one `test_<module>.py` per module.
- Name tests `test_<unit>_<scenario>_<expected>`, for example `test_fallback_painter_rate_limit_skips_primary_during_cooldown`.
- Give every assert a message that says what went wrong: `assert scene.image is second, "Latest image must replace the previous one"`.
- Shared fixtures go in `tests/conftest.py`. A fixture used by one file only may stay in that file.
- Mock only external dependencies: the Anthropic client, HTTP calls, `subprocess`, torch. Test sepia's own code for real, and use `tmp_path` for files.
- Tests never call real APIs, never open windows, and never download models.

## Commits

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<scope>): <short summary>

<body: why the change was made>
```

- Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`. Changes to the GitHub workflows use `ci`.
- The scope is usually the module: `painter`, `director`, `viewer`, `launcher`, `repl`, `ui`, `ipc`, `ascii`, `raster`, `config`, `spike`.
- Write the summary in the imperative ("add", "fix", "remove"), at most 72 characters.
- The body explains why, not what; the diff already shows what.

Example from the history:

```text
fix(ipc): keep listening after a failed handshake
```

## Pull requests

- One topic per pull request.
- Add user-visible changes to the `[Unreleased]` section of `CHANGELOG.md`.
- Describe how you checked the change. For rendering or prompt changes, attach a spike preview.

Releases are cut by the maintainer; the process is in [docs/releasing.md](docs/releasing.md).

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE) and that you follow the [Code of Conduct](CODE_OF_CONDUCT.md).
