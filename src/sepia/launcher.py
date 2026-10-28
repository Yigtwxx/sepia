"""Open the picture window in a new terminal window."""

import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

VIEWER_COLS = 110
VIEWER_ROWS = 36
"""Window size in cells of the default font; the small profile font fits about
1.8x as many in each direction."""
VIEWER_FONT_SIZE = 6
"""Points. More, smaller cells give the picture more detail."""
LAUNCH_TIMEOUT_SECONDS = 15
PROFILE_NAME = "sepia"
PROFILE_GUID = "{6f1c2b9e-3a57-4d0e-9c84-5e2f7a1d3b60}"


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
        "--profile",
        PROFILE_NAME,
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


def windows_profile() -> dict[str, object]:
    """A Windows Terminal profile for the picture: tiny font, black, no padding."""
    return {
        "guid": PROFILE_GUID,
        "name": PROFILE_NAME,
        "commandline": "cmd.exe",
        "font": {"face": "Cascadia Mono", "size": VIEWER_FONT_SIZE},
        "padding": "0",
        "background": "#000000",
        "scrollbarState": "hidden",
        "closeOnExit": "always",
        "bellStyle": "none",
    }


def install_windows_profile(local_app_data: Path | None = None) -> Path | None:
    """Write sepia's profile as a Windows Terminal fragment; None when not possible.

    Fragments live in their own folder, so the user's settings.json is never touched,
    and deleting the folder removes the profile again.
    """
    base = local_app_data or Path(os.environ.get("LOCALAPPDATA", ""))
    if not base.is_dir():
        return None
    target = (
        base / "Microsoft" / "Windows Terminal" / "Fragments" / "sepia" / "sepia.json"
    )
    content = json.dumps({"profiles": [windows_profile()]}, indent=2)
    with contextlib.suppress(OSError):
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return target
    return None


def find_windows_terminal(local_app_data: Path | None = None) -> str | None:
    """wt.exe from PATH, or from its app alias folder, which PATH may not include."""
    found = shutil.which("wt")
    if found is not None:
        return found
    base = local_app_data or Path(os.environ.get("LOCALAPPDATA", ""))
    alias = base / "Microsoft" / "WindowsApps" / "wt.exe"
    return str(alias) if alias.is_file() else None


def _open_windows(command: list[str]) -> None:
    wt = find_windows_terminal()
    if wt is not None:
        install_windows_profile()
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
