import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sepia import launcher, ui
from sepia.launcher import (
    LaunchError,
    macos_script,
    open_viewer,
    viewer_command,
    windows_terminal_command,
)

SESSION = Path("/tmp/sepia session/viewer.json")


def test_viewer_command_runs_sepia_viewer_with_current_python() -> None:
    command = viewer_command(SESSION)
    expected = [sys.executable, "-m", "sepia", "--viewer", str(SESSION)]
    assert command == expected, f"Got {command}"


def test_windows_terminal_command_opens_new_window_with_tab_row() -> None:
    args = windows_terminal_command("wt.exe", ["python", "-m", "sepia"])
    head = args[: args.index("new-tab")]
    assert head[:3] == ["wt.exe", "--window", "new"], f"Not a new window: {head}"
    assert "--focus" not in head, f"Focus mode hides the tab row: {head}"
    assert args[-4:] == ["--", "python", "-m", "sepia"], f"Command not last: {args}"


def test_windows_terminal_command_names_the_tab_sepia_in_purple() -> None:
    args = windows_terminal_command("wt.exe", ["python"])
    title = args[args.index("--title") + 1]
    color = args[args.index("--tabColor") + 1]
    assert title == "sepia", f"Wrong tab title: {args}"
    assert color == launcher.TAB_COLOR == ui.ACCENT, f"Tab not in theme: {args}"
    assert "--suppressApplicationTitle" in args, f"Title can be overwritten: {args}"


def test_macos_script_escapes_quotes_and_execs_viewer() -> None:
    script = macos_script(["/Applications/My App/python", "-m", 'say "hi"'])
    assert 'tell application "Terminal"' in script, f"Wrong app: {script}"
    assert "do script \"exec '/Applications/My App/python' -m" in script, script
    assert '\\"hi\\"' in script, f"Quotes not escaped: {script}"


@pytest.mark.parametrize(
    ("platform", "which", "program"),
    [("win32", "C:/wt.exe", "C:/wt.exe"), ("darwin", None, "osascript")],
)
def test_open_viewer_runs_platform_launcher(
    monkeypatch: pytest.MonkeyPatch, platform: str, which: str | None, program: str
) -> None:
    run = MagicMock()
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(launcher.shutil, "which", lambda _: which)
    monkeypatch.setattr(launcher.subprocess, "run", run)
    monkeypatch.setattr(launcher, "install_windows_profile", lambda: None)
    open_viewer(SESSION)
    called = run.call_args.args[0]
    assert called[0] == program, f"Expected {program}, got {called}"


def test_open_viewer_unsupported_platform_raises_launch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(LaunchError, match="Windows and macOS"):
        open_viewer(SESSION)


def test_open_viewer_failed_launch_raises_launch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    failure = subprocess.CalledProcessError(1, "osascript")
    monkeypatch.setattr(launcher.subprocess, "run", MagicMock(side_effect=failure))
    with pytest.raises(LaunchError, match="could not open"):
        open_viewer(SESSION)


def test_windows_terminal_command_uses_the_sepia_profile() -> None:
    args = windows_terminal_command("wt.exe", ["python"])
    index = args.index("--profile")
    assert args[index + 1] == launcher.PROFILE_NAME, f"Wrong profile: {args}"


def test_install_windows_profile_writes_fragment_once(tmp_path: Path) -> None:
    target = launcher.install_windows_profile(tmp_path)
    assert target is not None and target.is_file(), "Fragment was not written"
    profile = json.loads(target.read_text(encoding="utf-8"))["profiles"][0]
    assert profile["name"] == "sepia", f"Wrong profile: {profile}"
    assert profile["font"]["size"] == launcher.VIEWER_FONT_SIZE, f"Got {profile}"
    stamp = target.stat().st_mtime_ns
    launcher.install_windows_profile(tmp_path)
    assert target.stat().st_mtime_ns == stamp, "An unchanged fragment was rewritten"


def test_install_windows_profile_without_app_data_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    assert launcher.install_windows_profile(missing) is None, "Expected no fragment"


def test_find_windows_terminal_falls_back_to_the_app_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
    alias = tmp_path / "Microsoft" / "WindowsApps" / "wt.exe"
    alias.parent.mkdir(parents=True)
    alias.write_bytes(b"")
    assert launcher.find_windows_terminal(tmp_path) == str(alias), "Alias not found"
    alias.unlink()
    assert launcher.find_windows_terminal(tmp_path) is None, "Expected no terminal"
