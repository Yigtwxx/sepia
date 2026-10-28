"""Open the picture window in a new terminal window."""

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

VIEWER_COLS = 120
VIEWER_ROWS = 40
LAUNCH_TIMEOUT_SECONDS = 15


class LaunchError(RuntimeError):
    """The picture window could not be opened."""


def viewer_command(session_file: Path) -> list[str]:
    """The command the new window runs; same interpreter, so it works in any venv."""
    return [sys.executable, "-m", "sepia", "--viewer", str(session_file)]


def open_viewer(session_file: Path) -> None:
    command = viewer_command(session_file)
    try:
        if sys.platform == "win32":
            _open_windows(command)
        elif sys.platform == "darwin":
            _open_macos(command)
        else:
            raise LaunchError("the picture window opens on Windows and macOS only")
    except (OSError, subprocess.SubprocessError) as exc:
        raise LaunchError(f"could not open the picture window: {exc}") from exc


def windows_terminal_command(wt: str, command: list[str]) -> list[str]:
    """A new Windows Terminal window in focus mode: no tab bar and no title bar."""
    return [
        wt,
        "--window",
        "new",
        "--focus",
        "--size",
        f"{VIEWER_COLS},{VIEWER_ROWS}",
        "new-tab",
        "--title",
        "sepia",
        "--suppressApplicationTitle",
        "--",
        *command,
    ]


def macos_script(command: list[str]) -> str:
    """AppleScript that runs `command` in a new Terminal.app window.

    `exec` replaces the shell, so the window closes when the viewer exits.
    """
    shell_line = "exec " + shlex.join(command)
    quoted = shell_line.replace("\\", "\\\\").replace('"', '\\"')
    return f'tell application "Terminal"\n  do script "{quoted}"\n  activate\nend tell'


def _open_windows(command: list[str]) -> None:
    wt = shutil.which("wt")
    if wt is not None:
        subprocess.run(
            windows_terminal_command(wt, command),
            check=True,
            timeout=LAUNCH_TIMEOUT_SECONDS,
        )
        return
    if sys.platform == "win32":  # narrows the type for the console flag
        subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_CONSOLE)


def _open_macos(command: list[str]) -> None:
    subprocess.run(
        ["osascript", "-e", macos_script(command)],
        check=True,
        capture_output=True,
        timeout=LAUNCH_TIMEOUT_SECONDS,
    )
