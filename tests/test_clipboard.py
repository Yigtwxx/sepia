import subprocess
import sys
from typing import Any

import pytest
from PIL import Image

from sepia import clipboard
from sepia.scene import Canvas

Run = tuple[list[str], bytes]


def _longest(size: Canvas) -> int:
    """The fenced text's length with every row full."""
    return size.rows * (size.cols + 1) + 2 * len(clipboard.FENCE) + 1


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> list[Run]:
    """Commands `copy_text` runs, with their input; no tool is started."""
    calls: list[Run] = []

    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, options["input"]))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(clipboard.subprocess, "run", run)
    return calls


# --- copy_size ---------------------------------------------------------------------


def test_copy_size_wide_window_is_80_columns_in_its_shape() -> None:
    size = clipboard.copy_size(Canvas(200, 50))
    assert size == Canvas(80, 20), f"Expected 80x20, got {size}"


def test_copy_size_tall_window_shrinks_to_fit_one_message() -> None:
    size = clipboard.copy_size(Canvas(100, 80))
    assert _longest(size) <= clipboard.COPY_LIMIT, f"{size} is too long"
    assert abs(size.rows - size.cols * 80 / 100) <= 1, f"{size} lost the shape"


def test_copy_size_narrow_window_keeps_its_width() -> None:
    size = clipboard.copy_size(Canvas(60, 20))
    assert size == Canvas(60, 20), f"Expected 60x20, got {size}"


def test_copy_size_absurd_window_still_fits_one_message() -> None:
    size = clipboard.copy_size(Canvas(1, 5000))
    assert _longest(size) <= clipboard.COPY_LIMIT, f"{size} is too long"
    assert size.cols >= 1 and size.rows >= 1, f"{size} must not be empty"


# --- fence and art_text ------------------------------------------------------------


def test_fence_wraps_lines_and_drops_backticks_and_trailing_spaces() -> None:
    text = clipboard.fence(["`@ ", "  ``` "])
    assert text == "```\n.@\n  ...\n```", f"Got {text!r}"


def test_art_text_gradient_fits_the_copy_grid_inside_a_fence() -> None:
    image = Image.linear_gradient("L").convert("RGB")
    canvas = Canvas(200, 50)
    text = clipboard.art_text(image, canvas, "classic")
    lines = text.split("\n")
    size = clipboard.copy_size(canvas)
    assert lines[0] == lines[-1] == clipboard.FENCE, f"Not fenced: {lines[0]!r}"
    assert len(lines) - 2 == size.rows, f"Expected {size.rows} rows"
    assert all(len(line) <= size.cols for line in lines[1:-1]), "A row is too wide"
    assert "`" not in "".join(lines[1:-1]), "A backtick would close the fence"
    assert len(text) <= clipboard.COPY_LIMIT, f"{len(text)} characters"


# --- copy_text ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "command"), [("win32", ["clip"]), ("darwin", ["pbcopy"])]
)
def test_copy_text_runs_the_platform_tool_with_the_text(
    monkeypatch: pytest.MonkeyPatch, runs: list[Run], platform: str, command: list[str]
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    clipboard.copy_text("```\n@@\n```")
    assert runs == [(command, b"```\n@@\n```")], f"Ran {runs}"


def test_copy_text_linux_uses_the_first_installed_tool(
    monkeypatch: pytest.MonkeyPatch, runs: list[Run]
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        clipboard.shutil,
        "which",
        lambda name: "/usr/bin/xclip" if name == "xclip" else None,
    )
    clipboard.copy_text("@")
    expected = [(["xclip", "-selection", "clipboard"], b"@")]
    assert runs == expected, f"Ran {runs}"


def test_copy_text_linux_without_a_tool_raises_clipboard_error(
    monkeypatch: pytest.MonkeyPatch, runs: list[Run]
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: None)
    with pytest.raises(clipboard.ClipboardError, match="no clipboard tool"):
        clipboard.copy_text("@")
    assert runs == [], f"Nothing must run: {runs}"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (subprocess.CalledProcessError(1, ["clip"]), "clip exited with code 1"),
        (subprocess.TimeoutExpired(["clip"], 5.0), "clip did not finish in time"),
        (FileNotFoundError(2, "not found"), "could not run clip"),
    ],
)
def test_copy_text_failing_tool_raises_clipboard_error_with_the_reason(
    monkeypatch: pytest.MonkeyPatch, error: Exception, reason: str
) -> None:
    def fail(command: list[str], **options: Any) -> None:
        raise error

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(clipboard.subprocess, "run", fail)
    with pytest.raises(clipboard.ClipboardError, match=reason):
        clipboard.copy_text("@")
