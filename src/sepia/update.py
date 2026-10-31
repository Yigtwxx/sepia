"""`sepia update` and the notice of a newer release.

It finds how sepia was installed, asks that installer to upgrade it, and checks
PyPI for a newer version. On Windows a running program locks the compiled
modules it has loaded while an upgrade replaces them, so this module imports
only the standard library and `sepia` itself.
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
