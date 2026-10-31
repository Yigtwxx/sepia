# sepia update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sepia update` upgrades sepia with the installer that installed it, in the same terminal, and sepia says on start when a newer release is out.

**Architecture:** A new module `src/sepia/update.py` finds the install kind from files in `sys.prefix`, asks PyPI for the latest version, runs the installer (renaming the running `sepia.exe` first on Windows), and keeps the last PyPI answer in `update.json` for a notice on the welcome screen. `cli.py` gains the `update` command; `/config` gains an "Update notices" row. Spec: `docs/superpowers/specs/2026-10-31-sepia-update-design.md`.

**Tech Stack:** Python 3.12 standard library (tomllib, urllib, subprocess), rich, prompt_toolkit, pytest, uv.

## Global Constraints

- Code, identifiers and comments in English; interface strings in `ui.STRINGS` (English only).
- Full type annotations; `uv run mypy` (strict on `src/`) must pass; `ruff` formats at 88 columns. ruff also formats Python blocks inside Markdown, so docs use `text` fences for code fragments.
- `src/sepia/update.py` imports only the standard library, rich and `sepia` (`__version__`, `ui`): never `sepia.config`, pydantic, numpy, Pillow or anything else with compiled modules from sepia's environment (Windows locks loaded modules while an upgrade replaces them).
- Tests: names `test_<unit>_<scenario>_<expected>`, every assert has a message, shared fixtures in `tests/conftest.py`, mock only external dependencies (network through the `web` fixture, `subprocess.run`, `shutil.which`, the platform). No real network, subprocess, windows or installs.
- Never open or read `.env`. Never print or log a key.
- Checks: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, `uv run pytest`.
- Commits: Conventional Commits, imperative summary ≤72 characters, body says why, ending with exactly these two lines:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01BW1DAApQxrcaPKBC51LHfS
  ```

---

### Task 1: Install kind, versions and the release cache

**Files:**
- Create: `src/sepia/update.py`
- Test: `tests/test_update.py`

**Interfaces:**
- Produces (in `sepia.update`): `PACKAGE = "sepia-cli"`, `PYPI_URL`, `CHECK_SECONDS = 3.0`, `CHECK_EVERY = timedelta(days=1)`, `OLD = ".old"`; `Method = Literal["uv", "pipx", "pip", "source"]`; `@dataclass(frozen=True) Install(method, command: tuple[str, ...] = (), launcher: Path | None = None, source: str = "")`; `@dataclass(frozen=True) Release(latest: str, checked: datetime)`; `find_install(prefix: Path | None = None, argv0: str | None = None) -> Install`; `is_newer(latest: str, current: str = __version__) -> bool`; `latest_release(timeout: float = CHECK_SECONDS) -> str | None`; `cached_release(path: Path) -> Release | None`; `refresh_release(path: Path, now: datetime | None = None, fetch: Callable[[], str | None] = latest_release) -> None`; `notice(path: Path) -> str`; `clear_old_launcher(argv0: str | None = None) -> None`; private `_launcher(argv0: str) -> Path | None`, `_direct_url() -> str`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_update.py`:

```text
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sepia import __version__, update
from sepia.update import (
    PACKAGE,
    PYPI_URL,
    Install,
    Release,
    cached_release,
    clear_old_launcher,
    find_install,
    is_newer,
    latest_release,
    notice,
    refresh_release,
)

UV_COMMAND = ("uv", "tool", "upgrade", PACKAGE)
RECEIPT = """[tool]
requirements = [{ name = "sepia-cli", extras = ["local"] }]
entrypoints = [
    { name = "sepia", install-path = "C:/Users/me/.local/bin/sepia.exe", from = "sepia-cli" },
]
"""
NOW = datetime(2026, 10, 31, 12, 0, 0)


def _receipt(prefix: Path, text: str = RECEIPT) -> Path:
    (prefix / "uv-receipt.toml").write_text(text, encoding="utf-8")
    return prefix


def _find(prefix: Path) -> Install:
    return find_install(prefix, argv0=str(prefix / "nowhere"))


def test_find_install_uv_tool_from_pypi_upgrades_with_uv(tmp_path: Path) -> None:
    found = _find(_receipt(tmp_path))
    expected = Install("uv", UV_COMMAND, Path("C:/Users/me/.local/bin/sepia.exe"))
    assert found == expected, f"Got {found}"


@pytest.mark.parametrize(
    ("key", "value"),
    [("editable", "C:/src/sepia"), ("git", "https://github.com/Yigtwxx/sepia")],
)
def test_find_install_uv_tool_from_a_source_has_no_command(
    tmp_path: Path, key: str, value: str
) -> None:
    text = f'[tool]\nrequirements = [{{ name = "sepia-cli", {key} = "{value}" }}]\n'
    found = _find(_receipt(tmp_path, text))
    assert found == Install("source", source=value), f"Got {found}"


def test_find_install_uv_receipt_without_entrypoint_uses_the_running_exe(
    tmp_path: Path,
) -> None:
    _receipt(tmp_path, '[tool]\nrequirements = [{ name = "sepia-cli" }]\n')
    exe = tmp_path / "sepia.exe"
    exe.write_bytes(b"launcher")
    found = find_install(tmp_path, argv0=str(tmp_path / "sepia"))
    assert found.launcher == exe, f"The running .exe must be found, got {found}"


def test_find_install_unreadable_receipt_still_upgrades_with_uv(tmp_path: Path) -> None:
    found = _find(_receipt(tmp_path, "[[[ not toml"))
    assert found.command == UV_COMMAND, f"Got {found}"


def test_find_install_pipx_upgrades_with_pipx(tmp_path: Path) -> None:
    (tmp_path / "pipx_metadata.json").write_text("{}", encoding="utf-8")
    found = _find(tmp_path)
    assert found.command == ("pipx", "upgrade", PACKAGE), f"Got {found}"


def test_find_install_pip_from_pypi_upgrades_with_this_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(update, "_direct_url", lambda: "")
    found = _find(tmp_path)
    expected = (sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE)
    assert found.method == "pip" and found.command == expected, f"Got {found}"


def test_find_install_pip_from_a_folder_is_a_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(update, "_direct_url", lambda: "file:///C:/src/sepia")
    found = _find(tmp_path)
    assert found == Install("source", source="file:///C:/src/sepia"), f"Got {found}"


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("0.4.1", "0.4.0", True),
        ("0.4.0", "0.4.0", False),
        ("0.3.9", "0.4.0", False),
        ("0.10.0", "0.9.9", True),
        ("1.0.0", "0.4.0", True),
        ("0.5.0", "0.5.0a1", True),
        ("0.5.0a1", "0.4.0", True),
        ("0.4", "0.4.0", False),
    ],
)
def test_is_newer_compares_release_numbers(
    latest: str, current: str, expected: bool
) -> None:
    result = is_newer(latest, current)
    assert result is expected, f"is_newer({latest!r}, {current!r}) = {result}"


def test_latest_release_reads_the_version_from_pypi(web) -> None:
    web[PYPI_URL] = (json.dumps({"info": {"version": "0.4.2"}}).encode(), "application/json")
    assert latest_release() == "0.4.2", "PyPI's info.version must come back"


@pytest.mark.parametrize("body", [None, b"not json", b'{"info": {}}', b"[1, 2]"])
def test_latest_release_unusable_answer_is_none(web, body: bytes | None) -> None:
    if body is not None:
        web[PYPI_URL] = (body, "application/json")
    assert latest_release() is None, f"{body!r} must give no version"


def _keep(path: Path, latest: str, checked: datetime) -> None:
    data = {"latest": latest, "checked": checked.isoformat()}
    path.write_text(json.dumps(data), encoding="utf-8")


def test_refresh_release_without_a_file_asks_and_keeps_the_answer(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config" / "update.json"
    refresh_release(path, now=NOW, fetch=lambda: "0.4.2")
    assert cached_release(path) == Release("0.4.2", NOW), "The answer must be kept"


def test_refresh_release_recent_answer_is_not_asked_again(tmp_path: Path) -> None:
    path = tmp_path / "update.json"
    _keep(path, "0.4.2", NOW)
    refresh_release(path, now=NOW + timedelta(hours=5), fetch=lambda: pytest.fail("asked"))
    assert cached_release(path) == Release("0.4.2", NOW), "The file must stay"


def test_refresh_release_day_old_answer_is_asked_again(tmp_path: Path) -> None:
    path = tmp_path / "update.json"
    _keep(path, "0.4.1", NOW - timedelta(days=2))
    refresh_release(path, now=NOW, fetch=lambda: "0.4.2")
    assert cached_release(path) == Release("0.4.2", NOW), "A stale answer is replaced"


def test_refresh_release_failed_check_keeps_the_old_answer(tmp_path: Path) -> None:
    path = tmp_path / "update.json"
    old = NOW - timedelta(days=2)
    _keep(path, "0.4.1", old)
    refresh_release(path, now=NOW, fetch=lambda: None)
    assert cached_release(path) == Release("0.4.1", old), "A failed check changes nothing"


@pytest.mark.parametrize("text", ["", "{", '{"latest": "1"}', "[]"])
def test_cached_release_unreadable_file_is_none(tmp_path: Path, text: str) -> None:
    path = tmp_path / "update.json"
    path.write_text(text, encoding="utf-8")
    assert cached_release(path) is None, f"{text!r} must read as nothing"


@pytest.mark.parametrize(("latest", "expected"), [("99.0.0", "99.0.0"), (__version__, "")])
def test_notice_names_only_a_newer_version(
    tmp_path: Path, latest: str, expected: str
) -> None:
    path = tmp_path / "update.json"
    _keep(path, latest, NOW)
    assert notice(path) == expected, f"{latest}: got {notice(path)!r}"


def test_notice_without_a_file_is_empty(tmp_path: Path) -> None:
    assert notice(tmp_path / "update.json") == "", "No file, no notice"


def test_clear_old_launcher_deletes_the_moved_launcher_only(tmp_path: Path) -> None:
    exe, old = tmp_path / "sepia.exe", tmp_path / "sepia.exe.old"
    exe.write_bytes(b"new")
    old.write_bytes(b"old")
    clear_old_launcher(str(exe))
    assert not old.exists(), "The old launcher must be deleted"
    assert exe.read_bytes() == b"new", "The launcher itself must stay"
```

(Lines over 88 columns in the tests are wrapped by `ruff format`; run it.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_update.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sepia.update'`.

- [ ] **Step 3: Implement** — create `src/sepia/update.py`:

```text
"""`sepia update` and the notice of a newer release.

It finds how sepia was installed, asks that installer to upgrade it, and checks
PyPI for a newer version. On Windows a running program locks the compiled
modules it has loaded while an upgrade replaces them, so this module imports
only the standard library, rich and `sepia.ui`.
"""

import contextlib
import importlib.metadata
import json
import os
import re
import sys
import tomllib
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sepia import __version__

PACKAGE = "sepia-cli"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
CHECK_SECONDS = 3.0
"""How long a release check waits for PyPI."""
CHECK_EVERY = timedelta(days=1)
"""How often the notice on start asks PyPI again."""
MAX_ANSWER = 2_000_000
"""Bytes read from PyPI's answer, which lists every release."""
OLD = ".old"
"""Added to the running launcher's name while an upgrade replaces it."""
SOURCE_KEYS = ("editable", "directory", "path", "git", "url")
"""Keys of a uv requirement that comes from somewhere other than PyPI."""

Method = Literal["uv", "pipx", "pip", "source"]


@dataclass(frozen=True)
class Install:
    """How this sepia was installed and what upgrades it."""

    method: Method
    command: tuple[str, ...] = ()
    """The upgrade command; empty for a source install."""
    launcher: Path | None = None
    """The `sepia.exe` that starts sepia, moved aside before upgrading on Windows."""
    source: str = ""
    """Where a source install comes from: a folder or a URL."""


@dataclass(frozen=True)
class Release:
    """The latest version PyPI named, and when it was asked."""

    latest: str
    checked: datetime


def find_install(prefix: Path | None = None, argv0: str | None = None) -> Install:
    """How this sepia was installed, from the files its installer left in the
    environment at `prefix` (`sys.prefix`)."""
    root = prefix if prefix is not None else Path(sys.prefix)
    launcher = _launcher(argv0 if argv0 is not None else sys.argv[0])
    receipt = root / "uv-receipt.toml"
    if receipt.is_file():
        return _uv_install(receipt, launcher)
    if (root / "pipx_metadata.json").is_file():
        return Install("pipx", ("pipx", "upgrade", PACKAGE), launcher)
    source = _direct_url()
    if source:
        return Install("source", source=source)
    command = (sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE)
    return Install("pip", command, launcher)


def _uv_install(receipt: Path, launcher: Path | None) -> Install:
    """A uv tool: from PyPI it upgrades with uv; from a folder or URL it is a
    source install. The receipt names the launcher uv wrote."""
    try:
        data = tomllib.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        data = {}
    tool: dict[str, Any] = data.get("tool", {})
    requirement = _named(tool.get("requirements", []), PACKAGE)
    for key in SOURCE_KEYS:
        if requirement.get(key):
            return Install("source", source=str(requirement[key]))
    path = _named(tool.get("entrypoints", []), "sepia").get("install-path")
    written = Path(path) if isinstance(path, str) and path else launcher
    return Install("uv", ("uv", "tool", "upgrade", PACKAGE), written)


def _named(items: object, name: str) -> dict[str, Any]:
    """The table in `items` whose name is `name`, or an empty one."""
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("name") == name:
                return item
    return {}


def _launcher(argv0: str) -> Path | None:
    """The `.exe` this sepia was started from; None when it was not one."""
    path = Path(argv0)
    if path.suffix.lower() != ".exe":
        path = path.with_name(f"{path.name}.exe")
    return path if path.is_file() else None


def _direct_url() -> str:
    """Where pip installed sepia from when that was not PyPI (a folder, a URL);
    empty for PyPI or when it cannot be told."""
    try:
        text = importlib.metadata.distribution(PACKAGE).read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return ""
    if not text:
        return ""
    try:
        url = json.loads(text).get("url", "")
    except (ValueError, AttributeError):
        return ""
    return url if isinstance(url, str) else ""


def is_newer(latest: str, current: str = __version__) -> bool:
    """`latest` is a later release than `current`: their numbers compare, and a
    pre-release of the same numbers ("0.5.0a1") comes before the release."""
    new, old = _numbers(latest), _numbers(current)
    if new != old:
        return new > old
    return _is_pre(current) and not _is_pre(latest)


def _numbers(version: str) -> tuple[int, ...]:
    found = re.match(r"\d+(?:\.\d+)*", version.strip())
    parts = [int(part) for part in found.group().split(".")] if found else []
    parts += [0] * (3 - len(parts))
    return tuple(parts)


def _is_pre(version: str) -> bool:
    return re.fullmatch(r"\d+(?:\.\d+)*", version.strip()) is None


def latest_release(timeout: float = CHECK_SECONDS) -> str | None:
    """The newest release on PyPI (it leaves pre-releases out); None when PyPI
    cannot be reached or answers something else."""
    request = urllib.request.Request(
        PYPI_URL,
        headers={"Accept": "application/json", "User-Agent": f"sepia/{__version__}"},
    )
    try:
        with urllib.request.build_opener().open(request, timeout=timeout) as reply:
            data = json.loads(reply.read(MAX_ANSWER))
    except (OSError, ValueError):
        return None
    info = data.get("info") if isinstance(data, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    return version.strip() if isinstance(version, str) and version.strip() else None


def cached_release(path: Path) -> Release | None:
    """The last answer kept in `path`; None when there is none or it is unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Release(str(data["latest"]), datetime.fromisoformat(data["checked"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def refresh_release(
    path: Path,
    now: datetime | None = None,
    fetch: Callable[[], str | None] = latest_release,
) -> None:
    """Ask PyPI again when the answer in `path` is a day old or missing, and keep
    the new one; a failed check leaves the file as it was."""
    moment = now or datetime.now()
    kept = cached_release(path)
    if kept is not None and moment - kept.checked < CHECK_EVERY:
        return
    latest = fetch()
    if latest is None:
        return
    record = json.dumps({"latest": latest, "checked": moment.isoformat()})
    temporary = path.with_suffix(".tmp")
    with contextlib.suppress(OSError):  # Only a convenience: the next start retries.
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(record, encoding="utf-8")
        os.replace(temporary, path)


def notice(path: Path) -> str:
    """The newer version kept in `path`, or empty when this one is the latest."""
    kept = cached_release(path)
    return kept.latest if kept is not None and is_newer(kept.latest) else ""


def clear_old_launcher(argv0: str | None = None) -> None:
    """Delete the launcher an update on Windows moved aside; it no longer runs."""
    launcher = _launcher(argv0 if argv0 is not None else sys.argv[0])
    if launcher is not None:
        with contextlib.suppress(OSError):
            launcher.with_name(launcher.name + OLD).unlink(missing_ok=True)
```

- [ ] **Step 4: Run the tests and checks**

Run: `uv run ruff format src/sepia/update.py tests/test_update.py && uv run pytest tests/test_update.py -v && uv run mypy && uv run ruff check`
Expected: all PASS. (`test_find_install_uv_tool_from_pypi...` builds `Path("C:/Users/me/...")`; on macOS that is a relative path and still compares equal to what the code builds from the same string.)

- [ ] **Step 5: Commit**

```text
git add src/sepia/update.py tests/test_update.py
git commit -m "feat: find how sepia was installed and its latest release" -m "sepia update needs the installer that installed sepia, and the notice on start needs PyPI's latest version without slowing the start." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BW1DAApQxrcaPKBC51LHfS"
```

---

### Task 2: The `sepia update` command

**Files:**
- Modify: `src/sepia/update.py`, `src/sepia/ui.py` (`STRINGS`), `src/sepia/cli.py`
- Test: `tests/test_update.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1's `Install`, `find_install`, `latest_release`, `is_newer`, `OLD`, `clear_old_launcher`.
- Produces: `update.run_update(console: Console, words: ui.Words, install: Install | None = None) -> int`; `update.others_running(python: str | None = None) -> int`; `PROCESS_SECONDS = 20.0`; `sepia update` on the command line.

- [ ] **Step 1: Strings** — add to `ui.STRINGS`:

```text
    "update_found": "sepia {latest} is out (you have {current})",
    "update_latest": "sepia {version} is the latest version",
    "update_offline": "Could not reach PyPI; trying the update anyway",
    "update_source": "sepia is installed from {source}, not PyPI: update it there "
    "(git pull)",
    "update_close": "Close the other sepia windows first ({count} still open), then "
    "run sepia update again",
    "update_missing": "{tool} is not on PATH; run this yourself: {command}",
    "update_failed": "The update failed; the message above says why. Try again with: "
    "{command}",
    "update_done": "Updated to sepia {version}",
    "update_done_unknown": "Updated to the latest sepia",
```

- [ ] **Step 2: Write the failing tests** — append to `tests/test_update.py` (add `import io`, `import os`, `from types import SimpleNamespace`, `from rich.console import Console`, `from sepia import ui`, and `others_running`, `run_update` to the `sepia.update` import):

```text
class Runner:
    """Stands in for `subprocess.run`: records each command, answers PowerShell's
    process list with `pids` and the installer with `code`, and can write a new
    launcher as an installer would."""

    def __init__(self, code: int = 0, pids: str = "", writes: Path | None = None):
        self.code, self.pids, self.writes = code, pids, writes
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> SimpleNamespace:
        self.calls.append(list(command))
        if command[0] == "powershell":
            return SimpleNamespace(returncode=0, stdout=self.pids)
        if self.writes is not None:
            self.writes.write_bytes(b"new launcher")
        return SimpleNamespace(returncode=self.code, stdout="")


def _rig(
    monkeypatch: pytest.MonkeyPatch,
    web,
    runner: Runner,
    platform: str = "darwin",
    latest: str | None = "99.0.0",
    tools: bool = True,
) -> io.StringIO:
    """PyPI naming `latest`, `runner` as subprocess, uv on PATH unless not
    `tools`, and `platform` as the system; returns what is printed."""
    if latest is not None:
        body = json.dumps({"info": {"version": latest}}).encode()
        web[PYPI_URL] = (body, "application/json")
    monkeypatch.setattr(update.subprocess, "run", runner)
    monkeypatch.setattr(
        update.shutil, "which", lambda name: f"/bin/{name}" if tools else None
    )
    monkeypatch.setattr(update.sys, "platform", platform)
    return io.StringIO()


def _update(out: io.StringIO, install: Install) -> int:
    console = Console(file=out, width=200, color_system=None)
    return run_update(console, ui.Words(), install)


UV = Install("uv", UV_COMMAND)


def test_run_update_already_latest_says_so_and_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, web
) -> None:
    runner = Runner()
    out = _rig(monkeypatch, web, runner, latest=__version__)
    code = _update(out, UV)
    assert code == 0, f"Exit code {code}"
    assert f"sepia {__version__} is the latest version" in out.getvalue(), out.getvalue()
    assert runner.calls == [], f"Nothing may run, ran {runner.calls}"


def test_run_update_newer_release_runs_the_installer(
    monkeypatch: pytest.MonkeyPatch, web
) -> None:
    runner = Runner()
    out = _rig(monkeypatch, web, runner)
    code = _update(out, UV)
    printed = out.getvalue()
    assert code == 0, f"Exit code {code}"
    assert runner.calls == [["/bin/uv", "tool", "upgrade", PACKAGE]], runner.calls
    for piece in ("sepia 99.0.0 is out", "uv tool upgrade sepia-cli", "Updated to sepia 99.0.0"):
        assert piece in printed, f"{piece!r} missing from {printed!r}"


def test_run_update_source_install_says_where_and_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, web
) -> None:
    runner = Runner()
    out = _rig(monkeypatch, web, runner)
    code = _update(out, Install("source", source="C:/src/sepia"))
    assert code == 0, f"Exit code {code}"
    assert "installed from C:/src/sepia, not PyPI" in out.getvalue(), out.getvalue()
    assert runner.calls == [], f"Nothing may run, ran {runner.calls}"


def test_run_update_pypi_unreachable_still_runs_the_installer(
    monkeypatch: pytest.MonkeyPatch, web
) -> None:
    runner = Runner()
    out = _rig(monkeypatch, web, runner, latest=None)
    code = _update(out, UV)
    printed = out.getvalue()
    assert code == 0, f"Exit code {code}"
    assert "Could not reach PyPI" in printed, printed
    assert "Updated to the latest sepia" in printed, printed


def test_run_update_other_windows_open_refuses_on_windows(
    monkeypatch: pytest.MonkeyPatch, web
) -> None:
    runner = Runner(pids="111\n222\n")
    out = _rig(monkeypatch, web, runner, platform="win32")
    code = _update(out, UV)
    assert code == 1, f"Exit code {code}"
    assert "2 still open" in out.getvalue(), out.getvalue()
    assert all(call[0] == "powershell" for call in runner.calls), runner.calls


def test_run_update_installer_missing_names_the_command(
    monkeypatch: pytest.MonkeyPatch, web
) -> None:
    runner = Runner()
    out = _rig(monkeypatch, web, runner, tools=False)
    code = _update(out, UV)
    assert code == 1, f"Exit code {code}"
    expected = "uv is not on PATH; run this yourself: uv tool upgrade sepia-cli"
    assert expected in out.getvalue(), out.getvalue()
    assert runner.calls == [], f"Nothing may run, ran {runner.calls}"


def test_run_update_installer_failure_returns_its_code(
    monkeypatch: pytest.MonkeyPatch, web
) -> None:
    runner = Runner(code=2)
    out = _rig(monkeypatch, web, runner)
    code = _update(out, UV)
    assert code == 2, f"The installer's code must come back, got {code}"
    assert "The update failed" in out.getvalue(), out.getvalue()


def test_run_update_on_windows_moves_the_running_launcher_aside(
    monkeypatch: pytest.MonkeyPatch, web, tmp_path: Path
) -> None:
    exe = tmp_path / "sepia.exe"
    exe.write_bytes(b"old launcher")
    runner = Runner(writes=exe)
    out = _rig(monkeypatch, web, runner, platform="win32")
    code = _update(out, Install("uv", UV_COMMAND, exe))
    assert code == 0, f"Exit code {code}"
    assert exe.read_bytes() == b"new launcher", "The installer's launcher must stay"
    old = tmp_path / "sepia.exe.old"
    assert old.read_bytes() == b"old launcher", "The running one waits beside it"


def test_run_update_on_windows_puts_the_launcher_back_when_none_was_written(
    monkeypatch: pytest.MonkeyPatch, web, tmp_path: Path
) -> None:
    exe = tmp_path / "sepia.exe"
    exe.write_bytes(b"old launcher")
    runner = Runner(code=1)
    out = _rig(monkeypatch, web, runner, platform="win32")
    _update(out, Install("uv", UV_COMMAND, exe))
    assert exe.read_bytes() == b"old launcher", "The launcher must come back"
    assert not (tmp_path / "sepia.exe.old").exists(), "Nothing may be left aside"


def test_others_running_off_windows_asks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Runner(pids="111")
    monkeypatch.setattr(update.subprocess, "run", runner)
    monkeypatch.setattr(update.sys, "platform", "darwin")
    assert others_running() == 0, "Only Windows locks running files"
    assert runner.calls == [], f"Nothing may run, ran {runner.calls}"


def test_others_running_leaves_out_this_process_and_its_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Runner(pids=f"{os.getpid()}\n{os.getppid()}\n999\n")
    monkeypatch.setattr(update.subprocess, "run", runner)
    monkeypatch.setattr(update.sys, "platform", "win32")
    assert others_running("C:/tools/python.exe") == 1, "Only process 999 is another"
```

Append to `tests/test_cli.py`:

```text
def test_main_update_command_runs_the_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sepia.update.run_update", lambda console, words: 5)
    monkeypatch.setattr("sepia.repl.run_repl", lambda: pytest.fail("prompt ran"))
    assert main(["update"]) == 5, "The update's exit code must come back"


def test_main_clears_an_old_launcher_on_every_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleared: list[bool] = []
    monkeypatch.setattr("sepia.update.clear_old_launcher", lambda: cleared.append(True))
    monkeypatch.setattr("sepia.repl.run_repl", lambda: 0)
    main([])
    assert cleared == [True], "The old launcher must be cleared at start"
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_update.py tests/test_cli.py -v`
Expected: FAIL with `ImportError: cannot import name 'others_running'`.

- [ ] **Step 4: Implement in `src/sepia/update.py`** — add imports `import shutil`, `import subprocess`, `from rich.console import Console`, `from rich.text import Text`, and change `from sepia import __version__` to `from sepia import __version__, ui`. Add after `OLD`:

```text
PROCESS_SECONDS = 20.0
"""How long counting the other sepia processes may take."""
```

Add at the end of the module:

```text
def run_update(
    console: Console, words: ui.Words, install: Install | None = None
) -> int:
    """`sepia update`: upgrade with the installer that installed sepia, in this
    terminal. Returns the exit code to leave with."""
    found = install if install is not None else find_install()
    if found.method == "source":
        console.print(ui.reply(words("update_source", source=found.source)))
        return 0
    latest = latest_release()
    if latest is None:
        console.print(ui.reply(words("update_offline")))
    elif not is_newer(latest):
        console.print(ui.reply(words("update_latest", version=__version__)))
        return 0
    else:
        found_text = words("update_found", latest=latest, current=__version__)
        console.print(ui.reply(found_text))
    command = " ".join(found.command)
    others = others_running()
    if others:
        console.print(ui.reply(words("update_close", count=others), failed=True))
        return 1
    tool = shutil.which(found.command[0])
    if tool is None:
        missing = words("update_missing", tool=found.command[0], command=command)
        console.print(ui.reply(missing, failed=True))
        return 1
    console.print(Text(f"   {command}", style=ui.MUTED))
    code = _upgrade([tool, *found.command[1:]], found.launcher)
    if code:
        console.print(ui.reply(words("update_failed", command=command), failed=True))
        return code
    done = words("update_done", version=latest) if latest else words("update_done_unknown")
    console.print(ui.reply(done))
    return 0


def others_running(python: str | None = None) -> int:
    """How many other sepia processes run from this install (prompt or picture
    windows), whose loaded modules would block an upgrade. Windows only; 0 when
    they cannot be counted."""
    if sys.platform != "win32":
        return 0
    exe = (python or sys.executable).replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.ExecutablePath -eq '{exe}' }} | "
        "ForEach-Object { $_.ProcessId }"
    )
    try:
        found = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=PROCESS_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    ids = {int(word) for word in found.stdout.split() if word.isdigit()}
    # This sepia shows up as itself and, in a venv, as the launcher that started it.
    return len(ids - {os.getpid(), os.getppid()})


def _upgrade(command: list[str], launcher: Path | None) -> int:
    """Run the installer. On Windows the running launcher is moved aside first,
    so the installer can write a new one; it comes back if none was written."""
    moving = launcher if sys.platform == "win32" else None
    aside = _move_aside(moving) if moving is not None else None
    try:
        code = subprocess.run(command, check=False).returncode
    except OSError:
        code = 1
    if aside is not None and moving is not None and not moving.exists():
        with contextlib.suppress(OSError):
            aside.replace(moving)
    return code


def _move_aside(launcher: Path) -> Path | None:
    """Rename the running `launcher`, which Windows allows; None when it cannot."""
    aside = launcher.with_name(launcher.name + OLD)
    try:
        aside.unlink(missing_ok=True)
        launcher.replace(aside)
    except OSError:
        return None
    return aside
```

Update the module docstring's last sentence if needed so it still holds (imports: standard library, rich, `sepia.ui`).

- [ ] **Step 5: Implement in `src/sepia/cli.py`** — in `build_parser`, after `--version`:

```text
    parser.add_argument(
        "command",
        nargs="?",
        choices=["update"],
        help="update: upgrade sepia to the latest release",
    )
```

In `main`, right after `args = build_parser().parse_args(argv)`:

```text
    from sepia.update import clear_old_launcher

    clear_old_launcher()
```

and before `if args.download:`:

```text
    if args.command == "update":
        from rich.console import Console

        from sepia import ui
        from sepia.update import run_update

        return run_update(Console(highlight=False), ui.Words())
```

- [ ] **Step 6: Run the tests and checks**

Run: `uv run ruff format && uv run pytest tests/test_update.py tests/test_cli.py -v && uv run mypy && uv run ruff check && uv run pytest`
Expected: all PASS.

- [ ] **Step 7: Commit**

```text
git add src/sepia/update.py src/sepia/ui.py src/sepia/cli.py tests/test_update.py tests/test_cli.py
git commit -m "feat: add sepia update" -m "Upgrading meant remembering how sepia was installed; on Windows the running sepia.exe is renamed first, since an installer cannot overwrite a running program." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BW1DAApQxrcaPKBC51LHfS"
```

---

### Task 3: The notice on start and its setting

**Files:**
- Modify: `src/sepia/config.py`, `src/sepia/ui.py`, `src/sepia/repl.py`
- Test: `tests/test_config.py`, `tests/test_ui.py`, `tests/test_repl.py`

**Interfaces:**
- Consumes: `update.notice(path) -> str`, `update.refresh_release(path)` (Task 1).
- Produces: `Settings.update_check: bool = True`, `Choices.update_check: bool | None`, env `SEPIA_UPDATE_CHECK`; `ui.release_notice(words, latest) -> Text`; `Repl(..., update_notice: str = "")` with attributes `update_notice: str` and `update_check: bool`; a third `/config` row with key `"update"`.

- [ ] **Step 1: Strings** — add to `ui.STRINGS`:

```text
    "update_notice": "sepia {latest} is out: run sepia update",
    "config.update": "Update notices",
    "config.update_summary": "say when a new sepia is out",
    "update_check_on": "Update notices on, from the next start",
    "update_check_off": "Update notices off",
```

and after `tip` in `ui.py`:

```text
def release_notice(words: Words, latest: str) -> Text:
    """The line under the tip when a newer sepia is out."""
    text = Text(" ↑ ", style=ACCENT)
    text.append(words("update_notice", latest=latest), style=MUTED)
    return text
```

- [ ] **Step 2: Write the failing tests**

`tests/test_config.py` (add `"SEPIA_UPDATE_CHECK"` to the unknown-choice parametrize list too):

```text
@pytest.mark.parametrize(
    ("environ", "expected"),
    [({}, True), ({"SEPIA_UPDATE_CHECK": " OFF "}, False)],
)
def test_load_settings_update_check_switch_sets_the_notice(
    environ: dict[str, str], expected: bool
) -> None:
    settings = load_settings(environ)
    assert settings.update_check is expected, f"{environ}: got {settings}"
```

`tests/test_ui.py`:

```text
def test_release_notice_names_the_version_and_the_command() -> None:
    text = ui.release_notice(ui.Words(), "0.4.2").plain
    assert text == " ↑ sepia 0.4.2 is out: run sepia update", f"Got {text!r}"
```

`tests/test_repl.py` (beside the other `/config` tests):

```text
def test_repl_config_turns_update_notices_off_and_remembers_it(
    rig: Rig, terminal
) -> None:
    keys, _ = terminal
    keys.send_text(f"{DOWN}{DOWN} \x1b")
    rig.say("/config")
    assert rig.repl.update_check is False, "Update notices must be off"
    assert _choices()["update_check"] is False, f"Kept {_choices()}"
    assert "Update notices off" in rig.printed(), rig.printed()


@pytest.mark.parametrize(("check", "shown"), [(True, True), (False, False)])
def test_repl_welcome_screen_shows_a_newer_release_only_when_asked(
    rig: Rig, check: bool, shown: bool
) -> None:
    rig.repl.update_notice = "9.9.9"
    rig.repl.update_check = check
    rig.say("/clear")
    present = "sepia 9.9.9 is out: run sepia update" in rig.printed()
    assert present is shown, f"update_check={check}: notice shown = {present}"
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_config.py tests/test_ui.py tests/test_repl.py -v -k "update or release"`
Expected: FAIL (`Settings` has no `update_check`; `ui` has no `release_notice`).

- [ ] **Step 4: Implement**

`config.py`: in `Settings`, after `ask`:

```text
    update_check: bool = True
    """Say on start when a newer sepia is on PyPI."""
```

in `Choices`: `update_check: bool | None = None`; in `load_settings`, after the `ask` line: `update_check = _choice(environ, "SEPIA_UPDATE_CHECK", get_args(Switch), "on")` and pass `update_check=update_check == "on",` to `Settings(...)`.

`repl.py`:
- imports: `import threading` and `from sepia import ui, update` (replace `from sepia import ui`).
- `Repl.__init__` gains a keyword parameter `update_notice: str = ""` after `search_key`; store:

```text
        self.update_notice = update_notice
        """A newer sepia on PyPI, named on the welcome screen; empty when none."""
        self.update_check = settings.update_check
```

- `_draw_screen`: after `self.console.print(ui.tip(self.words))`:

```text
        if self.update_notice and self.update_check:
            self.console.print(ui.release_notice(self.words, self.update_notice))
```

- `_configure`: add a third row after `"mature"`:

```text
                (
                    "update",
                    self.words("config.update"),
                    self.words("config.update_summary"),
                    self.update_check,
                ),
```

and after the mature handling:

```text
        if values["update"] != self.update_check:
            self.update_check = values["update"]
            remember(update_check=values["update"])
            state = _switch(values["update"])
            self.transcript.say(ui.reply(self.words(f"update_check_{state}")))
```

- `run_repl`: before `repl = Repl(...)`:

```text
    release_file = config_dir() / "update.json"
    latest = update.notice(release_file) if settings.update_check else ""
    if settings.update_check:
        # The answer shows on the next start; this one never waits for PyPI.
        threading.Thread(
            target=update.refresh_release,
            args=(release_file,),
            name="sepia-release",
            daemon=True,
        ).start()
```

and pass `update_notice=latest` to `Repl(...)`.

- [ ] **Step 5: Run the whole suite and the checks**

Run: `uv run ruff format && uv run ruff check && uv run mypy && uv run pytest`
Expected: all PASS (the existing `/config` tests still pass: the new row is the third).

- [ ] **Step 6: Commit**

```text
git add src/sepia/config.py src/sepia/ui.py src/sepia/repl.py tests/test_config.py tests/test_ui.py tests/test_repl.py
git commit -m "feat: say on start when a newer sepia is out" -m "The notice reads yesterday's answer from update.json, so the start never waits for PyPI; /config and SEPIA_UPDATE_CHECK turn it off." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BW1DAApQxrcaPKBC51LHfS"
```

---

### Task 4: Docs, landing page and changelog

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `CLAUDE.md`, `.env.example`, `site/src/data/commands.ts`, and the site component that shows the install lines if it fits there (find it with `grep -rn "install" site/src/components`).

- [ ] **Step 1: README.md**
  - In the Install section, a short "Update" paragraph: `sepia update` upgrades sepia with the installer that installed it (`uv tool upgrade sepia-cli`, `pipx upgrade sepia-cli`, or pip), keeping extras such as `[local]` and the CUDA index. On Windows, close sepia's other windows first; `sepia update` says so if one is open. An install from a folder or git checkout is updated there (`git pull`).
  - Where the start is described or near `/config`: on start sepia says when a newer release is out (it checks PyPI at most once a day, in the background, and shows the answer on the next start); `/config` → Update notices, or `SEPIA_UPDATE_CHECK=off`, turns it off.
  - The `/config` row text: "Turn clarifying questions, mature pictures and update notices on or off in one list."
  - Variables table: `| \`SEPIA_UPDATE_CHECK\` | \`on\` | Say on start when a newer sepia is out (\`on\` or \`off\`). \`/config\` changes it. |`; add `SEPIA_UPDATE_CHECK` to the invalid-value sentence; `update notices` among what `/config` keeps in `choices.json`.
- [ ] **Step 2: `.env.example`**: a `# SEPIA_UPDATE_CHECK=on   (or off: no notice of new releases)` line in the same style as the others.
- [ ] **Step 3: Site**: in `site/src/data/commands.ts`, the `/config` comment becomes "turn clarifying questions, mature pictures and update notices on or off"; add a `SEPIA_UPDATE_CHECK` entry after `SEPIA_ASK` in the same shape (`value: 'on'`, `what: 'say when a new sepia is out'`). If the install block lists commands, add `sepia update` the way its neighbours are written; otherwise skip that. Run `cd site && npm run check && npm run format:check && npm run build` (prettier the changed files if format:check fails).
- [ ] **Step 4: CLAUDE.md**: layout line `- \`src/sepia/update.py\`: \`sepia update\` (finds the installer from \`sys.prefix\`, renames the running \`sepia.exe\` on Windows) and the release notice (\`update.json\`); imports nothing with compiled modules.`; the `cli.py` line gains `update`.
- [ ] **Step 5: CHANGELOG.md** under `## [Unreleased]` → `### Added` (create the headings if `[Unreleased]` is empty):

```text
- `sepia update` upgrades sepia with the installer that installed it (uv, pipx or pip), keeping extras such as `[local]`. On Windows it renames the running `sepia.exe` first, since an installer cannot overwrite a running program, and asks to close sepia's other windows.
- On start sepia says when a newer release is out; it checks PyPI at most once a day in the background. Off with `/config` (Update notices) or `SEPIA_UPDATE_CHECK=off`.
```

- [ ] **Step 6: All checks** — `uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest`, and the three site checks. All PASS.

- [ ] **Step 7: Commit**

```text
git add README.md CHANGELOG.md CLAUDE.md .env.example site/
git commit -m "docs: describe sepia update and the release notice" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BW1DAApQxrcaPKBC51LHfS"
```

---

## Release 0.4.1 (coordinator, after the final review)

Version `0.4.1` in `pyproject.toml`, `src/sepia/__init__.py`, `site/src/data/commands.ts`, `uv lock`; CHANGELOG `[Unreleased]` → `## [0.4.1] - 2026-10-31` with links; all checks; `uv build` + `twine check`; commit `chore: release 0.4.1`; merge to `main`; push; tag `v0.4.1`; push the tag; watch the workflows.
