import http.client
import io
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from sepia import __version__, ui, update
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
    others_running,
    refresh_release,
    run_update,
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


def test_latest_release_incomplete_read_is_none(
    monkeypatch: pytest.MonkeyPatch, web
) -> None:
    import urllib.request
    from unittest.mock import MagicMock

    reply = MagicMock()
    reply.__enter__.return_value = reply
    reply.read.side_effect = http.client.IncompleteRead(b"")
    opener = MagicMock()
    opener.open.return_value = reply
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: opener)
    assert latest_release() is None, "A cut-off answer must read as no answer"


def test_find_install_uv_receipt_with_a_non_table_tool_still_upgrades_with_uv(
    tmp_path: Path,
) -> None:
    found = _find(_receipt(tmp_path, 'tool = "x"\n'))
    assert found.method == "uv", f"Got {found}"
    assert found.command == UV_COMMAND, f"Got {found}"


def test_cached_release_timezone_aware_timestamp_is_none(tmp_path: Path) -> None:
    path = tmp_path / "update.json"
    record = {"latest": "99.0.0", "checked": "2026-10-31T12:00:00+00:00"}
    path.write_text(json.dumps(record), encoding="utf-8")
    assert cached_release(path) is None, "An aware time cannot be compared"


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
    assert f"sepia {__version__} is the latest version" in out.getvalue(), (
        out.getvalue()
    )
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
    for piece in (
        "sepia 99.0.0 is out",
        "uv tool upgrade sepia-cli",
        "Updated to sepia 99.0.0",
    ):
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


def test_others_running_off_windows_asks_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


class Interrupted(Runner):
    """An installer that Ctrl+C stops."""

    def __call__(self, command: list[str], **kwargs: object) -> SimpleNamespace:
        if command[0] != "powershell":
            raise KeyboardInterrupt
        return super().__call__(command, **kwargs)


class Unstartable(Runner):
    """An installer that cannot be started."""

    def __call__(self, command: list[str], **kwargs: object) -> SimpleNamespace:
        raise OSError("access denied")


def test_run_update_interrupted_on_windows_puts_the_launcher_back(
    monkeypatch: pytest.MonkeyPatch, web, tmp_path: Path
) -> None:
    exe = tmp_path / "sepia.exe"
    exe.write_bytes(b"old launcher")
    out = _rig(monkeypatch, web, Interrupted(), platform="win32")
    with pytest.raises(KeyboardInterrupt):
        _update(out, Install("uv", UV_COMMAND, exe))
    assert exe.read_bytes() == b"old launcher", "The launcher must come back"
    assert not (tmp_path / "sepia.exe.old").exists(), "Nothing may be left aside"


def test_run_update_installer_that_cannot_start_says_why(
    monkeypatch: pytest.MonkeyPatch, web
) -> None:
    out = _rig(monkeypatch, web, Unstartable())
    code = _update(out, UV)
    assert code == 1, f"Exit code {code}"
    assert "Could not start uv: access denied" in out.getvalue(), out.getvalue()


def test_run_update_pip_command_with_spaces_is_quoted_for_pasting(
    monkeypatch: pytest.MonkeyPatch, web
) -> None:
    runner = Runner(code=1)
    out = _rig(monkeypatch, web, runner, platform="win32")
    pip = Install("pip", ("C:/My Tools/python.exe", "-m", "pip"))
    _update(out, pip)
    assert '"C:/My Tools/python.exe" -m pip' in out.getvalue(), out.getvalue()


def test_others_running_quotes_a_python_path_with_an_apostrophe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Runner()
    monkeypatch.setattr(update.subprocess, "run", runner)
    monkeypatch.setattr(update.sys, "platform", "win32")
    others_running("C:/o'brien/python.exe")
    assert "'C:/o''brien/python.exe'" in runner.calls[0][-1], runner.calls
