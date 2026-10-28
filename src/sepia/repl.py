"""The prompt window: read requests, direct them, paint them, show them."""

import shutil
import time
import urllib.parse
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeVar, cast, get_args

from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.live import Live
from rich.text import Text

from sepia import ui
from sepia.ascii_art import ArtStyle, Charset
from sepia.chatbar import BottomBar, ChatBar
from sepia.config import (
    ConfigError,
    Effort,
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
from sepia.picker import choose
from sepia.reference import find_reference
from sepia.scene import Canvas, Scene
from sepia.usage import SESSION_FORMAT, Ledger, Usage, estimate_earlier

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
    """`/add Snowy Peaks` -> Command("add", "Snowy Peaks"); None for a request.

    The name is lowercased; the argument keeps its case, since for /add it is part
    of the picture's description.
    """
    if not line.startswith("/"):
        return None
    name, _, argument = line[1:].partition(" ")
    return Command(name.strip().lower(), argument.strip())


def named_option(options: tuple[str, ...], argument: str) -> str | None:
    """The option `argument` names (`/style ink`), or None to ask with a menu."""
    name = argument.strip().lower()
    return name if name in options else None


def new_session_dir(root: Path, keep: int = KEEP_SESSIONS) -> Path:
    """A fresh folder for this session's pictures; prunes the oldest ones."""
    root.mkdir(parents=True, exist_ok=True)
    folder = root / datetime.now().strftime(SESSION_FORMAT)
    folder.mkdir()
    for old in sorted(p for p in root.iterdir() if p.is_dir())[:-keep]:
        shutil.rmtree(old, ignore_errors=True)
    return folder


class Repl:
    def __init__(
        self,
        console: Console,
        words: ui.Words,
        settings: Settings,
        director: Director,
        painter: FallbackPainter,
        folder: Path,
        ledger: Ledger,
    ) -> None:
        self.console = console
        self.words = words
        self.settings = settings
        self.director = director
        self.painter = painter
        self.folder = folder
        self.scene = Scene()
        self.usage = Usage()
        self.ledger = ledger
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
        bar = ChatBar(
            history=FileHistory(str(config_dir() / "history")),
            commands=self.words.commands,
            placeholder=self.words("placeholder"),
            status=self._status,
        )
        try:
            while True:
                self.bar.to_bar()
                try:
                    line = bar.read().strip()
                except KeyboardInterrupt:
                    continue
                finally:
                    # The live bar erased itself; a still copy keeps it in view.
                    self.bar.hold(bar.still(shutil.get_terminal_size().columns))
                    self.bar.to_transcript()
                if not line:
                    continue
                self.console.print(ui.echo(line))
                if not self._handle(line):
                    return 0
                if parse_command(line) != Command("clear", ""):
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
            self._draw(line, add=False)
            return True
        if command.name in ("exit", "quit", "q"):
            return False
        if command.name == "help":
            self.console.print(ui.help_table(self.words))
        elif command.name == "usage":
            all_time = self.ledger.read()
            view = ui.usage_view(
                self.words,
                self.usage,
                all_time,
                self.settings.model,
                self.console.width,
            )
            self.console.print(view)
        elif command.name == "clear":
            self.scene.reset()
            self.host.send({"type": "clear"})
            self._open_screen()
        elif command.name == "add":
            if command.argument:
                self._draw(command.argument, add=True)
            else:
                self.console.print(ui.reply(self.words("add_usage"), failed=True))
        elif command.name == "effort":
            levels = cast(tuple[str, ...], get_args(Effort))
            effort = self.director.effort
            picked = self._pick("effort", levels, effort, command.argument)
            if picked is not None:
                self.director.effort = cast(Effort, picked)
                self.console.print(ui.reply(self.words("effort_set", effort=picked)))
        elif command.name in ("style", "charset"):
            if command.name == "style":
                styles = cast(tuple[str, ...], get_args(ArtStyle))
                picked = self._pick("style", styles, self.style, command.argument)
                if picked is None:
                    return True
                self.style = cast(ArtStyle, picked)
            else:
                sets = cast(tuple[str, ...], get_args(Charset))
                picked = self._pick("charset", sets, self.charset, command.argument)
                if picked is None:
                    return True
                self.charset = cast(Charset, picked)
            self.host.send(
                {"type": "style", "style": self.style, "charset": self.charset}
            )
            message = self.words("style_set", style=self.style, charset=self.charset)
            self.console.print(ui.reply(message))
        else:
            unknown = self.words("unknown", command=f"/{command.name}")
            self.console.print(ui.reply(unknown, failed=True))
        return True

    def _pick(
        self, kind: str, options: tuple[str, ...], current: str, argument: str
    ) -> str | None:
        """The option named after the command, else one picked from a menu; None
        when the menu is closed without a choice."""
        named = named_option(options, argument)
        if named is not None:
            return named
        return choose(
            self.words(f"pick_{kind}"),
            [(option, self.words(f"{kind}.{option}")) for option in options],
            current,
            self.words("pick_hint"),
        )

    def _draw(self, request: str, add: bool) -> None:
        """Paint `request`: a new picture, or with `add` an addition to this one.

        /add on an empty scene simply paints a new picture.
        """
        add = add and not self.scene.is_empty
        if not add:
            self.scene.reset()
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
        self._tally(lambda usage: usage.add_direction(direction))
        # A new picture starts from an empty scene; /add keeps the last reference.
        likeness = self.scene.likeness
        if direction.references:
            found = self._wait(
                lambda: find_reference(direction.references), self.words("looking")
            )
            likeness = found or likeness
        self.host.wait_connected(timeout=VIEWER_CONNECT_SECONDS)
        reference = self.scene.image if add else None
        size = paint_size(self.canvas.aspect)
        try:
            painting: Painting = self._wait(
                lambda: self.painter.paint(
                    direction.prompt, size, self.scene.seed, reference, likeness
                ),
                self.words("painting", source=self.words("source.api")),
            )
        except PainterError as exc:
            message = self.words("failure.paint", error=str(exc))
            self.console.print(ui.reply(message, failed=True))
            return
        self.scene.record(request, direction.prompt, painting.image, likeness)
        # The keyless API ignores reference pictures, so such a picture had none.
        used = likeness if painting.source != "keyless" else None
        self._tally(
            lambda usage: usage.add_painting(painting, referenced=used is not None)
        )
        self._count += 1
        path = self.folder / f"{self._count:02d}.png"
        painting.image.save(path)
        self._show(path)
        detail = f"{self.words(f'source.{painting.source}')} · {painting.seconds:.1f}s"
        if used is not None:
            host = urllib.parse.urlsplit(used.url).hostname or used.url
            detail += f" · {self.words('reference', host=host)}"
        self.console.print(ui.reply(direction.message, detail))

    def _tally(self, change: Callable[[Usage], None]) -> None:
        """Count something used, for this session and for all time."""
        change(self.usage)
        self.ledger.add(change)

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
        """A clean window: welcome box on top, the chat bar on the bottom rows.

        The transcript starts under the welcome box and scrolls it away once it
        reaches the bar, which never moves.
        """
        if self.console.is_terminal:
            self._write(ui.CLEAR)
        self.bar.start()
        self.console.print(ui.welcome(self.words, self.console.width))
        self.console.print(ui.tip(self.words))
        self.console.print()

    def _write(self, sequence: str) -> None:
        self.console.file.write(sequence)
        self.console.file.flush()

    def _status(self) -> str:
        window = "●" if self.host.connected else "○"
        model = (
            f"{self.settings.model.removeprefix('claude-')} ({self.director.effort})"
        )
        return f"  /help · {model} · {self.style}/{self.charset} · {window} window"


def run_repl() -> int:
    console = Console(highlight=False)
    load_environment()  # first: settings may come from a .env file
    words = ui.Words()
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
    ledger = Ledger(
        config_dir() / "usage.json",
        lambda: estimate_earlier(
            config_dir() / "history", config_dir() / "sessions", settings.model
        ),
    )
    # Before this session's requests reach the history and its folder prunes one.
    ledger.read()
    folder = new_session_dir(config_dir() / "sessions")
    return Repl(console, words, settings, director, painter, folder, ledger).run()


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
