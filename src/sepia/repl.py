"""The prompt window: read requests, direct them, paint them, show them."""

import shutil
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeVar, cast, get_args

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style as PromptStyle
from rich.console import Console
from rich.live import Live
from rich.text import Text

from sepia import ui
from sepia.ascii_art import ArtStyle, Charset
from sepia.config import (
    ConfigError,
    Settings,
    api_key,
    config_dir,
    load_environment,
    load_settings,
    pollinations_key,
    save_api_key,
)
from sepia.director import Director, DirectorError, create_client
from sepia.ipc import Host, Message
from sepia.launcher import VIEWER_COLS, VIEWER_ROWS, LaunchError, open_viewer
from sepia.painter import FallbackPainter, PainterError, Painting, build_painter
from sepia.painter import image_size as paint_size
from sepia.scene import Canvas, Scene

T = TypeVar("T")

VIEWER_CONNECT_SECONDS = 15
"""How long to wait for a freshly opened picture window to connect."""
RELAUNCH_GAP_SECONDS = 10
"""Don't open a second window while the first one is still starting."""
KEEP_SESSIONS = 10
"""Picture folders from older sessions are deleted beyond this many."""
FRAME_SECONDS = 0.1


@dataclass(frozen=True)
class Command:
    name: str
    argument: str


def parse_command(line: str) -> Command | None:
    """`/style ink` -> Command("style", "ink"); None for an ordinary request."""
    if not line.startswith("/"):
        return None
    name, _, argument = line[1:].partition(" ")
    return Command(name.strip().lower(), argument.strip().lower())


def toggle(current: str, options: tuple[str, ...], requested: str) -> str:
    """The requested option if valid, otherwise the next one after `current`."""
    if requested in options:
        return requested
    return options[(options.index(current) + 1) % len(options)]


def new_session_dir(root: Path, keep: int = KEEP_SESSIONS) -> Path:
    """A fresh folder for this session's pictures; prunes the oldest ones."""
    root.mkdir(parents=True, exist_ok=True)
    folder = root / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    folder.mkdir()
    for old in sorted(p for p in root.iterdir() if p.is_dir())[:-keep]:
        shutil.rmtree(old, ignore_errors=True)
    return folder


class BottomBar:
    """Keeps the chat bar on the bottom rows while the transcript scrolls above it.

    A terminal scroll region (DECSTBM) covers every row except the bar's, so output
    that reaches the region's bottom scrolls only the region: the welcome box moves up
    and out of view like any old line, and the bar never moves.
    """

    SAVE, RESTORE, RESET = "\x1b7", "\x1b8", "\x1b[r"

    def __init__(self, write: Callable[[str], None], rows: Callable[[], int]) -> None:
        self._write = write
        self._rows = rows

    def start(self) -> None:
        """Set the region; this also homes the cursor, where the transcript begins."""
        self._write(self._region())

    def to_bar(self) -> None:
        """Remember the transcript position and move to the bar's first row."""
        height = self._rows()
        # Re-applying the region follows window resizes; it homes the cursor, so
        # the transcript position is saved first and put back afterwards.
        self._write(self.SAVE + self._region() + self.RESTORE + self.SAVE)
        self._write(f"\x1b[{max(height - ui.BAR_ROWS + 1, 1)};1H")

    def to_transcript(self) -> None:
        self._write(self.RESTORE)

    def stop(self) -> None:
        """Give the whole screen back and leave the cursor on the last row."""
        self._write(f"{self.RESET}\x1b[{self._rows()};1H\n")

    def _region(self) -> str:
        return f"\x1b[1;{max(self._rows() - ui.BAR_ROWS, 1)}r"


class Repl:
    def __init__(
        self,
        console: Console,
        words: ui.Words,
        settings: Settings,
        director: Director,
        painter: FallbackPainter,
        folder: Path,
    ) -> None:
        self.console = console
        self.words = words
        self.settings = settings
        self.director = director
        self.painter = painter
        self.folder = folder
        self.scene = Scene()
        self.style: ArtStyle = settings.style
        self.charset: Charset = settings.charset
        self.canvas = Canvas(VIEWER_COLS, VIEWER_ROWS)
        self.host = Host(self._on_viewer_message)
        self.session_file = folder / "viewer.json"
        self.host.session.save(self.session_file)
        self._launched_at = 0.0
        self._count = 0
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sepia-work")
        self.bar = BottomBar(self._write, lambda: shutil.get_terminal_size().lines)

    def run(self) -> int:
        self._open_screen()
        session: PromptSession[str] = PromptSession(
            erase_when_done=True,  # the bar is redrawn at the bottom every turn
            reserve_space_for_menu=0,
            history=FileHistory(str(config_dir() / "history")),
            completer=WordCompleter(
                [usage.split()[0] for usage, _ in self.words.commands],
                meta_dict={
                    usage.split()[0]: text for usage, text in self.words.commands
                },
                sentence=True,
            ),
            style=PromptStyle.from_dict(
                {
                    "bottom-toolbar": f"noreverse {ui.MUTED}",
                    "prompt": f"bold {ui.ACCENT}",
                    "frame": ui.FRAME,
                    "rprompt": ui.FRAME,
                }
            ),
        )
        try:
            while True:
                self.bar.to_bar()
                try:
                    line = session.prompt(
                        self._bar_message,
                        rprompt=[("class:frame", "│")],
                        placeholder=[(f"fg:{ui.MUTED}", self.words("placeholder"))],
                        bottom_toolbar=self._toolbar,
                    ).strip()
                except KeyboardInterrupt:
                    continue
                finally:
                    self.bar.to_transcript()
                if not line:
                    continue
                self.console.print(ui.echo(line))
                if not self._handle(line):
                    return 0
                self.console.print()
        except EOFError:
            return 0
        finally:
            self.bar.stop()
            self.host.send({"type": "bye"})
            self.host.close()
            self._pool.shutdown(wait=False, cancel_futures=True)

    def _handle(self, line: str) -> bool:
        """Act on one line; False means exit."""
        command = parse_command(line)
        if command is None:
            self._draw(line)
            return True
        if command.name in ("exit", "quit", "q"):
            return False
        if command.name == "help":
            self.console.print(ui.help_table(self.words))
        elif command.name == "new":
            self.scene.reset()
            self.host.send({"type": "clear"})
            self.console.print(ui.reply(self.words("new_scene")))
        elif command.name in ("style", "charset"):
            if command.name == "style":
                styles = cast(tuple[str, ...], get_args(ArtStyle))
                self.style = cast(
                    ArtStyle, toggle(self.style, styles, command.argument)
                )
            else:
                sets = cast(tuple[str, ...], get_args(Charset))
                self.charset = cast(
                    Charset, toggle(self.charset, sets, command.argument)
                )
            self.host.send(
                {"type": "style", "style": self.style, "charset": self.charset}
            )
            message = self.words("style_set", style=self.style, charset=self.charset)
            self.console.print(ui.reply(message))
        else:
            unknown = self.words("unknown", command=f"/{command.name}")
            self.console.print(ui.reply(unknown, failed=True))
        return True

    def _draw(self, request: str) -> None:
        self._ensure_viewer()
        try:
            direction = self._wait(
                lambda: self.director.direct(request, self.scene),
                self.words("directing"),
            )
        except DirectorError as exc:
            self.console.print(
                ui.reply(self.words(f"failure.{exc.failure}"), failed=True)
            )
            return
        self.host.wait_connected(timeout=VIEWER_CONNECT_SECONDS)
        reference = self.scene.image if direction.edit else None
        size = paint_size(self.canvas.aspect)
        try:
            painting: Painting = self._wait(
                lambda: self.painter.paint(
                    direction.prompt, size, self.scene.seed, reference
                ),
                self.words("painting", source=self.words("source.api")),
            )
        except PainterError as exc:
            message = self.words("failure.paint", error=str(exc))
            self.console.print(ui.reply(message, failed=True))
            return
        self.scene.record(request, direction.prompt, painting.image)
        self._count += 1
        path = self.folder / f"{self._count:02d}.png"
        painting.image.save(path)
        self._show(path)
        detail = f"{self.words(f'source.{painting.source}')} · {painting.seconds:.1f}s"
        self.console.print(ui.reply(direction.message, detail))

    def _show(self, path: Path) -> None:
        message: Message = {
            "type": "image",
            "path": str(path),
            "style": self.style,
            "charset": self.charset,
        }
        if self.host.send(message):
            return
        self._ensure_viewer(force=True)
        if self.host.wait_connected(timeout=VIEWER_CONNECT_SECONDS):
            self.host.send(message)

    def _ensure_viewer(self, force: bool = False) -> None:
        if self.host.connected:
            return
        recently = time.monotonic() - self._launched_at < RELAUNCH_GAP_SECONDS
        if recently and not force:
            return
        self.host.accept_in_background()
        try:
            open_viewer(self.session_file)
        except LaunchError as exc:
            self.console.print(
                ui.reply(self.words("no_window", error=exc), failed=True)
            )
            return
        self._launched_at = time.monotonic()

    def _wait(self, work: Callable[[], T], label: str) -> T:
        """Run `work` on the worker thread while a spinner turns."""
        future: Future[T] = self._pool.submit(work)
        frames = ui.SPINNER
        with Live(console=self.console, transient=True, refresh_per_second=12) as live:
            tick = 0
            while not future.done():
                frame = frames[tick % len(frames)]
                live.update(Text.assemble((f" {frame} ", ui.ACCENT), (label, ui.MUTED)))
                tick += 1
                time.sleep(FRAME_SECONDS)
        return future.result()

    def _on_viewer_message(self, message: Message) -> None:
        cols, rows = message.get("cols"), message.get("rows")
        if message.get("type") != "size":
            return
        if isinstance(cols, int) and isinstance(rows, int) and cols > 0 and rows > 0:
            self.canvas = Canvas(cols, rows)

    def _open_screen(self) -> None:
        """Welcome box at the top of the scroll region, chat bar on the bottom rows."""
        self.console.clear()
        self.bar.start()
        self.console.print(ui.welcome(self.words, self.console.width))
        self.console.print(ui.tip(self.words))
        self.console.print()

    def _write(self, sequence: str) -> None:
        self.console.file.write(sequence)
        self.console.file.flush()

    def _bar_message(self) -> FormattedText:
        width = shutil.get_terminal_size().columns
        return FormattedText(
            [
                ("class:frame", ui.bar_top(width) + "\n"),
                ("class:frame", "│"),
                ("class:prompt", ui.PROMPT),
            ]
        )

    def _toolbar(self) -> FormattedText:
        width = shutil.get_terminal_size().columns
        window = "●" if self.host.connected else "○"
        model = self.settings.model.removeprefix("claude-")
        status = f"  /help · {model} · {self.style}/{self.charset} · {window} window"
        return FormattedText(
            [("class:frame", ui.bar_bottom(width) + "\n"), ("", status)]
        )


def run_repl() -> int:
    console = Console(highlight=False)
    load_environment()  # first: SEPIA_LANG and the rest may come from a .env file
    words = ui.Words(ui.detect_language())
    try:
        settings = load_settings()
    except ConfigError as exc:
        console.print(ui.reply(str(exc), failed=True))
        return 2
    key = api_key()
    if key is None:
        key = _ask_for_key(console, words)
        if key is None:
            return 1
    director = Director(create_client(key), settings.model, settings.effort)
    painter, _ = build_painter(pollinations_key(), settings.image_model)
    folder = new_session_dir(config_dir() / "sessions")
    return Repl(console, words, settings, director, painter, folder).run()


def _ask_for_key(console: Console, words: ui.Words) -> str | None:
    from prompt_toolkit import prompt

    from sepia.config import user_env_file

    console.print(ui.reply(words("key_missing")))
    try:
        key = prompt(
            words("key_prompt", path=user_env_file()), is_password=True
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not key:
        return None
    save_api_key(key)
    return key
