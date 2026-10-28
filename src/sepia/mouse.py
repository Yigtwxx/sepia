"""Where the mouse is over the picture window, from the terminal's own reports.

The viewer asks the terminal to report every pointer movement (mode 1003) in the SGR
encoding (mode 1006), so each move arrives on stdin as `ESC [ < button ; col ; row M`.
Nothing else is read from the keyboard; other input is dropped.
"""

import re
import sys

MOUSE_ON = "\x1b[?1003h\x1b[?1006h"
MOUSE_OFF = "\x1b[?1006l\x1b[?1003l"
_REPORT = re.compile(r"\x1b\[<\d+;(\d+);(\d+)[Mm]")
_MAX_PENDING = 32
"""A report is at most ~20 characters; a longer unfinished tail is noise."""


class MouseParser:
    """Turns raw terminal input into the latest pointer cell."""

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, text: str) -> tuple[int, int] | None:
        """The last pointer position (col, row), 0-based, reported in `text`.

        A report split across two reads is kept and completed by the next one.
        """
        data = self._pending + text
        latest: tuple[int, int] | None = None
        end = 0
        for match in _REPORT.finditer(data):
            latest = (int(match[1]) - 1, int(match[2]) - 1)
            end = match.end()
        rest = data[end:]
        start = rest.rfind("\x1b")
        self._pending = rest[start:][-_MAX_PENDING:] if start >= 0 else ""
        return latest


if sys.platform == "win32":

    def read_input() -> str:
        """Whatever the console has buffered, without waiting."""
        import msvcrt

        chars: list[str] = []
        while msvcrt.kbhit():
            chars.append(msvcrt.getwch())
        return "".join(chars)

else:

    def read_input() -> str:
        """Whatever stdin has buffered, without waiting."""
        import os
        import select

        fd = sys.stdin.fileno()
        chunks: list[bytes] = []
        while select.select([fd], [], [], 0)[0]:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="ignore")
