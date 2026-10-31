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
    { name = "sepia", install-path = "C:/Users/me/.local/bin/sepia.exe" },
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
    web[PYPI_URL] = (
        json.dumps({"info": {"version": "0.4.2"}}).encode(),
        "application/json",
    )
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
    refresh_release(
        path, now=NOW + timedelta(hours=5), fetch=lambda: pytest.fail("asked")
    )
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
    assert cached_release(path) == Release("0.4.1", old), (
        "A failed check changes nothing"
    )


@pytest.mark.parametrize("text", ["", "{", '{"latest": "1"}', "[]"])
def test_cached_release_unreadable_file_is_none(tmp_path: Path, text: str) -> None:
    path = tmp_path / "update.json"
    path.write_text(text, encoding="utf-8")
    assert cached_release(path) is None, f"{text!r} must read as nothing"


@pytest.mark.parametrize(
    ("latest", "expected"), [("99.0.0", "99.0.0"), (__version__, "")]
)
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
