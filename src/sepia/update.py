"""`sepia update` and the notice of a newer release.

It finds how sepia was installed, asks that installer to upgrade it, and checks
PyPI for a newer version. On Windows a running program locks the compiled
modules it has loaded while an upgrade replaces them, so this module imports
only the standard library, rich and `sepia` (`__version__`, `ui`), never
`sepia.config`, pydantic, numpy or Pillow.
"""

import contextlib
import http.client
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from rich.console import Console
from rich.text import Text

from sepia import __version__, ui

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
PROCESS_SECONDS = 20.0
"""How long counting the other sepia processes may take."""
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
    found = data.get("tool")
    tool: dict[str, Any] = found if isinstance(found, dict) else {}
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
    except (OSError, ValueError, http.client.HTTPException):
        return None
    info = data.get("info") if isinstance(data, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    return version.strip() if isinstance(version, str) and version.strip() else None


def cached_release(path: Path) -> Release | None:
    """The last answer kept in `path`; None when there is none or it is unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        checked = datetime.fromisoformat(data["checked"])
        latest = str(data["latest"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    # An aware time cannot be compared with the naive local one.
    return Release(latest, checked) if checked.tzinfo is None else None


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
    done = (
        words("update_done", version=latest) if latest else words("update_done_unknown")
    )
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
