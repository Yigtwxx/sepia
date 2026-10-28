# Releasing

The publishing decision is the owner's: a release is a `v*` tag the owner
pushes. `.github/workflows/release.yml` builds that tag and uploads it to PyPI
as `sepia-cli` through Trusted Publishing, so no token exists anywhere.

## One-time setup

**PyPI pending publisher.** `sepia-cli` does not exist on PyPI until the first
upload, so the publisher is registered as a *pending* one: pypi.org → *Your
account* → *Publishing* → *Add a new pending publisher* → *GitHub*:

| Field             | Value         |
| ----------------- | ------------- |
| PyPI Project Name | `sepia-cli`   |
| Owner             | `Yigtwxx`     |
| Repository name   | `sepia`       |
| Workflow name     | `release.yml` |
| Environment name  | `pypi`        |

The first successful run creates the project and turns the pending publisher
into a normal one. A pending publisher does not reserve the name, so push the
first tag soon after registering it.

**GitHub environment.** Repository *Settings* → *Environments* → *New
environment*, name `pypi`. Under *Deployment branches and tags*, choose
*Selected branches and tags* and add the tag rule `v*` (and the branch rule
`main` if the manual run below should be able to publish). Adding yourself
under *Required reviewers* makes every upload wait for a click.

## The version lives in two places

`pyproject.toml` (`version = ...`) and `src/sepia/__init__.py`
(`__version__ = ...`). Bump both in the same commit. The workflow checks the
tag against the built wheel, which takes its version from `pyproject.toml`
only, so this checks the other one:

```bash
uv run python -c "import importlib.metadata as m, sepia; assert m.version('sepia-cli') == sepia.__version__"
```

Versions are PEP 440: `0.1.0a1`, `0.1.0b1`, `0.1.0rc1`, `0.1.0`. A tag is the
same string with a `v` in front.

## Release steps

1. Run the checks: `uv run ruff check . && uv run ruff format --check . &&
   uv run mypy && uv run pytest`.
2. Bump the version in `pyproject.toml` and `src/sepia/__init__.py`.
3. In `CHANGELOG.md`, move the released entries from `[Unreleased]` into a new
   `## [X.Y.Z] - YYYY-MM-DD` section, and update the compare links at the
   bottom. `uv run python scripts/release_notes.py X.Y.Z` prints exactly what
   the GitHub Release will say.
4. Optional rehearsal of what CI builds: `rm -rf dist && uv build && uvx twine
   check dist/*`. Always a bare `uv build`, never `uv build --wheel`: it builds
   the sdist first and the wheel from that sdist, the path a release takes, so
   a file missing from the sdist shows up here rather than on PyPI.
5. Commit, then tag that commit and push the tag:

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

The `release` workflow refuses a tag whose version has no `CHANGELOG.md`
section or does not match the built wheel, publishes from the `pypi`
environment, and then creates the GitHub Release with that CHANGELOG section
as its notes and the wheel and sdist attached. Pre-release tags (`a`, `b`,
`rc`) are marked as pre-releases on GitHub.

A manual run (*Actions* → *release* → *Run workflow*) rebuilds the current
`main` and skips files PyPI already has, so it is safe to start by hand.

**A version number burns on upload.** PyPI will not let a file be replaced,
only yanked, so a broken `0.1.0` is fixed by releasing `0.1.1`.

To try a pre-release from PyPI, pin it, since installers skip pre-releases
by default: `uvx --from sepia-cli==0.2.0a1 sepia --help`.
