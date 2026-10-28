import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sepia import launcher
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


def test_windows_terminal_command_opens_new_focus_mode_window() -> None:
    args = windows_terminal_command("wt.exe", ["python", "-m", "sepia"])
    head = args[: args.index("new-tab")]
    assert head[:3] == ["wt.exe", "--window", "new"], f"Not a new window: {head}"
    assert "--focus" in head, f"Focus mode hides tab and title bars: {head}"
    assert args[-4:] == ["--", "python", "-m", "sepia"], f"Command not last: {args}"


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
