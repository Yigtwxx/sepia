"""The prompt window: read requests, direct them, paint them, show them."""

import contextlib
import os
import queue
import shutil
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeVar, cast, get_args

from PIL import Image, UnidentifiedImageError
from prompt_toolkit.history import FileHistory
from rich.console import Console, RenderableType
from rich.live import Live
from rich.text import Text

from sepia import ui, update
from sepia.ascii_art import ArtStyle, Charset
from sepia.camera import camera_installed
from sepia.chatbar import BottomBar, ChatBar, Resized
from sepia.config import (
    MODELS,
    ConfigError,
    Effort,
    ModelName,
    Settings,
    Switch,
    api_key,
    cloudflare_key,
    config_dir,
    load_choices,
    load_environment,
    load_settings,
    remember,
    save_keys,
    search_key,
    user_env_file,
)
from sepia.director import Answer, Direction, Director, DirectorError, create_client
from sepia.ipc import Host, Message
from sepia.keys import KEYS, Key, ask_secret, ask_values, is_set, key_named
from sepia.launcher import VIEWER_COLS, VIEWER_ROWS, LaunchError, open_viewer
from sepia.painter import (
    FallbackPainter,
    LocalPainter,
    Painter,
    PainterError,
    Painting,
    Source,
    build_painter,
    download_local_model,
    local_installed,
    local_model_ready,
)
from sepia.painter import image_size as paint_size
from sepia.picker import choose, show, toggles
from sepia.questions import ask as ask_questions
from sepia.raster import letterbox
from sepia.reference import Reference, find_reference, find_subject, split_links
from sepia.scene import Canvas, History, Scene, new_seed
from sepia.snapshot import pictures_dir, save_snapshot, snapshot
from sepia.usage import SESSION_FORMAT, Ledger, Usage, estimate_earlier

T = TypeVar("T")

VIEWER_CONNECT_SECONDS = 15
"""How long to wait for a freshly opened picture window to connect."""
RELAUNCH_GAP_SECONDS = 10
"""Don't open a second window while the first one is still starting."""
KEEP_SESSIONS = 10
"""Picture folders from older sessions are deleted beyond this many."""
FRAME_SECONDS = 0.1
EXIT_SECONDS = 2.0
"""A second Ctrl+C within this long of the first closes sepia."""
RESIZE_SETTLE_SECONDS = 0.15
"""A resize drag fires many sizes; redraw once the window has stopped changing."""
CAMERA_SECONDS = 15.0
"""How long to wait for the camera to come on, or for a kept frame."""
CAMERA_HINTS = {"win32": "camera_hint_windows", "darwin": "camera_hint_macos"}
"""Where each system lets a program use the camera."""


class Interrupts:
    """Ctrl+C in the chat bar: the first clears the line, a second one soon after
    closes sepia, as in Claude Code."""

    def __init__(
        self, window: float = EXIT_SECONDS, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._window = window
        self._clock = clock
        self._last = float("-inf")

    def press(self) -> bool:
        """Count one Ctrl+C; True when it is the second within the window."""
        leave = self.armed
        self._last = self._clock()
        return leave

    @property
    def armed(self) -> bool:
        """Whether a Ctrl+C now would close sepia."""
        return self._clock() - self._last < self._window


class Transcript:
    """What the prompt window printed under the welcome box.

    A terminal reflows its old lines when the window changes size, which breaks
    boxes and rules apart; so the window is cleared and all of it printed again.
    """

    def __init__(self, console: Console) -> None:
        self._console = console
        self._said: list[RenderableType] = []

    def say(self, renderable: RenderableType = "") -> None:
        self._said.append(renderable)
        self._console.print(renderable)

    def clear(self) -> None:
        self._said.clear()

    def replay(self) -> None:
        """Print everything said again, at the console's current width."""
        for renderable in self._said:
            self._console.print(renderable)


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


def _host(url: str) -> str:
    """The site a picture came from, for the reply under it."""
    return urllib.parse.urlsplit(url).hostname or url


def _switch(on: bool) -> str:
    return "on" if on else "off"


def _clarified(request: str, answers: Sequence[Answer]) -> str:
    """`request` with the answers to Claude's questions, as the scene keeps it for
    a later /add: "universe (Subject: A black hole; Mood: Calm)"."""
    if not answers:
        return request
    given = "; ".join(f"{a.header}: {', '.join(a.choices)}" for a in answers)
    return f"{request} ({given})"


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
        api: FallbackPainter | None,
        local: LocalPainter,
        folder: Path,
        ledger: Ledger,
        search_key: str | None = None,
        update_notice: str = "",
    ) -> None:
        self.console = console
        self.words = words
        self.settings = settings
        self.director = director
        self.api = api
        """Cloudflare with the local model behind it; None without a Cloudflare key."""
        self.local = local
        # The painter picked last time; the local model while Cloudflare has no key.
        self.paint_with: Source = settings.painter if api is not None else "local"
        """What /api and /local switch between."""
        self.folder = folder
        self.scene = Scene()
        self.history = History()
        """Earlier scenes, for /undo."""
        self.camera_live = False
        """The picture window shows the camera (/cam)."""
        self._camera_replies: queue.Queue[Message] = queue.Queue()
        """What the viewer answers about the camera, for the command waiting."""
        self.usage = Usage()
        self.ledger = ledger
        self.search_key = search_key
        """Brave Search API key: named subjects come from an image search."""
        self.update_notice = update_notice
        """A newer sepia on PyPI, named on the welcome screen; empty when none."""
        self.update_check = settings.update_check
        self.style: ArtStyle = settings.style
        self.charset: Charset = settings.charset
        self.canvas = Canvas(VIEWER_COLS, VIEWER_ROWS)
        self.host = Host(self._on_viewer_message)
        self.session_file = folder / "viewer.json"
        self.host.session.save(self.session_file)
        self._launched_at = 0.0
        self._started = time.monotonic()
        """When the request being worked on began; the spinner counts from it."""
        self._count = 0
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sepia-work")
        self.bar = BottomBar(self._write, lambda: shutil.get_terminal_size().lines)
        self.transcript = Transcript(console)
        self.interrupts = Interrupts()
        self._drawn_size = shutil.get_terminal_size()
        """The window's size when the screen was last drawn."""

    def run(self) -> int:
        self._open_screen()
        bar = ChatBar(
            history=FileHistory(str(config_dir() / "history")),
            commands=self.words.commands,
            placeholder=self.words("placeholder"),
            status=self._status,
            make_room=self.bar.make_room,
        )
        draft = ""
        try:
            while True:
                if shutil.get_terminal_size() != self._drawn_size:
                    self._redraw()
                self.bar.to_bar()
                try:
                    line, draft = bar.read(draft).strip(), ""
                except Resized as resized:
                    draft = resized.draft
                    continue
                except KeyboardInterrupt:
                    if self.interrupts.press():
                        return 0
                    continue
                finally:
                    # The live bar erased itself; a still copy keeps it in view.
                    self.bar.hold(bar.still(shutil.get_terminal_size().columns))
                    self.bar.to_transcript()
                if not line:
                    continue
                self.transcript.say(ui.echo(line))
                if not self._handle(line):
                    return 0
                if parse_command(line) != Command("clear", ""):
                    self.transcript.say()
        except (EOFError, KeyboardInterrupt):
            # Ctrl+D, or Ctrl+C while a request is being worked on.
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
            self.transcript.say(ui.help_table(self.words))
        elif command.name == "usage":
            all_time = self.ledger.read()
            view = ui.usage_view(
                self.words,
                self.usage,
                all_time,
                self.director.model,
                self.console.width,
            )
            # A panel to read and close, as in Claude Code: it leaves no trace.
            with self.console.capture() as captured:
                self.console.print(view)
            show(captured.get().rstrip("\n"), self.words("close_hint"))
        elif command.name == "model":
            names = {model: name for name, model in MODELS.items()}
            # A SEPIA_MODEL outside the four leaves no option checked.
            current = names.get(self.director.model, "")
            picked = self._pick("model", tuple(MODELS), current, command.argument)
            if picked is not None:
                self.director.model = MODELS[cast(ModelName, picked)]
                remember(model=self.director.model)
                model = self.director.model.removeprefix("claude-")
                self.transcript.say(ui.reply(self.words("model_set", model=model)))
        elif command.name == "clear":
            self._stop_camera()
            if not self.scene.is_empty:
                self.history.push(self.scene)
            self._enter(Scene())
            self._open_screen()
        elif command.name == "add":
            if not command.argument:
                self.transcript.say(ui.reply(self.words("add_usage"), failed=True))
            elif not self.camera_live or self._keep_frame():
                # A live camera's frame is what /add paints over.
                self._draw(command.argument, add=True)
        elif command.name == "again":
            self._again()
        elif command.name == "undo":
            self._undo()
        elif command.name == "cam":
            self._camera(command.argument)
        elif command.name == "effort":
            levels = cast(tuple[str, ...], get_args(Effort))
            effort = self.director.effort
            picked = self._pick("effort", levels, effort, command.argument)
            if picked is not None:
                self.director.effort = cast(Effort, picked)
                remember(effort=picked)
                self.transcript.say(ui.reply(self.words("effort_set", effort=picked)))
        elif command.name == "config":
            self._configure()
        elif command.name == "mature":
            switches = cast(tuple[str, ...], get_args(Switch))
            current = "on" if self.director.mature else "off"
            picked = self._pick("mature", switches, current, command.argument)
            if picked is not None:
                self.director.mature = picked == "on"
                remember(mature=self.director.mature)
                self.transcript.say(ui.reply(self.words(f"mature_{picked}")))
        elif command.name in ("api", "local"):
            self._switch_painter(cast(Source, command.name))
        elif command.name == "keys":
            self._set_keys(command.argument)
        elif command.name in ("style", "charset"):
            if command.name == "style":
                styles = cast(tuple[str, ...], get_args(ArtStyle))
                picked = self._pick("style", styles, self.style, command.argument)
                if picked is None:
                    return True
                self.style = cast(ArtStyle, picked)
                remember(style=self.style)
            else:
                sets = cast(tuple[str, ...], get_args(Charset))
                picked = self._pick("charset", sets, self.charset, command.argument)
                if picked is None:
                    return True
                self.charset = cast(Charset, picked)
                remember(charset=self.charset)
            self.host.send(
                {"type": "style", "style": self.style, "charset": self.charset}
            )
            message = self.words("style_set", style=self.style, charset=self.charset)
            self.transcript.say(ui.reply(message))
        elif command.name == "save":
            self._save()
        else:
            unknown = self.words("unknown", command=f"/{command.name}")
            self.transcript.say(ui.reply(unknown, failed=True))
        return True

    def _save(self) -> None:
        """Keep the picture in the window, drawn as its characters, as a PNG."""
        if self.camera_live and not self._keep_frame():
            return
        if self.scene.image is None:
            self.transcript.say(ui.reply(self.words("save_empty"), failed=True))
            return
        picture = snapshot(self.scene.image, self.canvas, self.style, self.charset)
        try:
            path = save_snapshot(picture, pictures_dir(), datetime.now())
        except OSError as exc:
            failed = self.words("save_failed", error=exc)
            self.transcript.say(ui.reply(failed, failed=True))
            return
        self.transcript.say(ui.reply(self.words("saved", path=path)))

    def _switch_painter(self, source: Source) -> None:
        """Paint with Cloudflare (the local model when it fails) or only on this
        machine, from the next picture on. /api also tries Cloudflare again after
        a cooldown or a used-up day."""
        if source == "api":
            if self.api is None:
                self.transcript.say(ui.reply(self.words("api_missing"), failed=True))
                return
            self.api.retry_primary()
        elif local_model_ready(self.settings.image_model):
            self.local.load_in_background()
        elif not local_installed():
            self.transcript.say(ui.reply(self.words("local_missing"), failed=True))
            return
        elif not self._download_local():
            return
        self.paint_with = source
        remember(painter=source)
        self.transcript.say(ui.reply(self.words(f"painter_{source}")))

    def _download_local(self) -> bool:
        """Ask before downloading the local model, then download it and start
        loading it; False, after saying why, when declined or failed."""
        model = self.settings.image_model
        picked = choose(
            self.words("pick_download", model=model),
            [(answer, self.words(f"download.{answer}")) for answer in ("yes", "no")],
            "yes",
            self.words("pick_hint"),
        )
        if picked != "yes":
            self.transcript.say(ui.reply(self.words("download_declined")))
            return False
        self._started = time.monotonic()
        try:
            self._wait(lambda: download_local_model(model), "downloading")
        except PainterError as exc:
            message = self.words("download_failed", error=exc)
            self.transcript.say(ui.reply(message, failed=True))
            return False
        self.local.load_in_background()
        return True

    def _set_keys(self, argument: str) -> None:
        """Set the key named after the command (/keys cloudflare), else one picked
        from a menu, and use it from the next request on."""
        names = tuple(key.name for key in KEYS)
        picked = named_option(names, argument) or choose(
            self.words("pick_keys"),
            [(key.name, self._key_state(key)) for key in KEYS],
            names[0],
            self.words("pick_hint"),
        )
        if picked is None:
            return
        try:
            values = _ask_key(self.transcript.say, self.words, key_named(picked))
        except (EOFError, KeyboardInterrupt):
            values = {}
        if not values:
            self.transcript.say(ui.reply(self.words("keys_unchanged")))
            return
        save_keys(values)
        os.environ.update(values)
        self._use_keys()
        if picked == "cloudflare":
            # A Cloudflare key just set is meant to paint.
            self.paint_with = "api"
            remember(painter="api")
        self.transcript.say(ui.reply(self.words("keys_saved", name=picked)))

    def _key_state(self, key: Key) -> str:
        state = self.words("keys_set" if is_set(key) else "keys_not_set")
        return f"{state} · {self.words(f'keys.{key.name}')}"

    def _use_keys(self) -> None:
        """Write prompts, paint and search with the keys now in the environment."""
        key = api_key()
        if key is not None:
            director = self.director
            self.director = Director(
                create_client(key),
                director.model,
                director.effort,
                mature=director.mature,
                ask=director.ask,
            )
        try:
            cloudflare = cloudflare_key()
        except ConfigError:
            cloudflare = None
        # The local painter stays, with its model if it is loaded.
        self.api, _ = build_painter(cloudflare, self.settings.image_model, self.local)
        self.search_key = search_key()

    @property
    def source(self) -> Source:
        """Where the next picture is painted: /api paints locally while there is
        no usable Cloudflare key, so the choice alone does not say."""
        return "api" if self.paint_with == "api" and self.api is not None else "local"

    @property
    def painter(self) -> Painter:
        """What paints the next picture."""
        if self.paint_with == "api" and self.api is not None:
            return self.api
        return self.local

    def _api_failure(self) -> PainterError | None:
        """Why Cloudflare did not paint the last picture, while /api is on."""
        if self.paint_with == "api" and self.api is not None:
            return self.api.last_error
        return None

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

    def _configure(self) -> None:
        """/config: the on/off settings in one list. Each one changed is applied,
        kept for the next session and confirmed; /mature is a shortcut to one."""
        values = toggles(
            self.words("config_title"),
            [
                (
                    "ask",
                    self.words("config.ask"),
                    self.words("config.ask_summary"),
                    self.director.ask,
                ),
                (
                    "mature",
                    self.words("config.mature"),
                    self.words("config.mature_summary"),
                    self.director.mature,
                ),
                (
                    "update",
                    self.words("config.update"),
                    self.words("config.update_summary"),
                    self.update_check,
                ),
            ],
            self.words("config_hint"),
        )
        if values["ask"] != self.director.ask:
            self.director.ask = values["ask"]
            remember(ask=values["ask"])
            self.transcript.say(ui.reply(self.words(f"ask_{_switch(values['ask'])}")))
        if values["mature"] != self.director.mature:
            self.director.mature = values["mature"]
            remember(mature=values["mature"])
            state = _switch(values["mature"])
            self.transcript.say(ui.reply(self.words(f"mature_{state}")))
        if values["update"] != self.update_check:
            self.update_check = values["update"]
            remember(update_check=values["update"])
            state = _switch(values["update"])
            self.transcript.say(ui.reply(self.words(f"update_check_{state}")))

    def _draw(self, request: str, add: bool) -> None:
        """Paint `request`: a new picture, or with `add` an addition to this one.

        /add on an empty scene simply paints a new picture. A bare name ("yunara
        lol") or a bare picture link shows the subject's picture as it is. The
        current scene stays until the new picture is there. A vague new picture may
        first get Claude's questions; the answers go back to Claude before anything
        is painted.
        """
        self._started = time.monotonic()
        self._stop_camera()
        add = add and not self.scene.is_empty
        scene = self.scene.copy() if add else Scene()
        self._ensure_viewer()
        words, links = split_links(request)
        found: Reference | None = None
        if links:
            found = self._wait(lambda: find_reference(links), "looking")
            if found is None:
                self.transcript.say(ui.reply(self.words("link_unusable"), failed=True))
                if not words:
                    return
            elif not words and not add:
                self._present(request, found, self.words("showing_link"), scene)
                return
        direction = self._direct(words, found, scene)
        if direction is None:
            return
        answers: tuple[Answer, ...] = ()
        if direction.questions:
            asked = self._ask(direction)
            if asked is None:
                return
            answers = asked
            if answers:
                direction = self._direct(words, found, scene, answers)
                if direction is None:
                    return
        told = _clarified(words or request, answers)
        if found is None and (direction.subject or direction.references):
            found = self._find_subject(direction)
            if found is not None and direction.show:
                self._present(told, found, direction.message, scene)
                return
            if found is not None:
                # Claude now sees the picture, so the prompt describes the real look.
                direction = self._direct(words, found, scene, answers) or direction
        # A new picture starts from an empty scene; /add keeps the last reference.
        likeness = found or scene.likeness
        base = scene.image
        painting = self._paint(direction.prompt, scene.seed, base, likeness)
        if painting is None:
            return
        path = self._keep(painting.image)
        scene.record(
            told,
            direction.prompt,
            painting.image,
            likeness,
            path=path,
            base=base,
        )
        self._commit(scene)
        detail = self._painted(painting, likeness)
        self.transcript.say(ui.reply(direction.message, detail))

    def _again(self) -> None:
        """Paint the latest prompt again with fresh noise, over the picture an /add
        painted over; Claude is not asked."""
        self._stop_camera()
        if self.scene.is_empty:
            self.transcript.say(ui.reply(self.words("again_empty"), failed=True))
            return
        prompt = self.scene.prompts[-1]
        if not prompt:
            self.transcript.say(ui.reply(self.words("again_shown"), failed=True))
            return
        self._started = time.monotonic()
        self._ensure_viewer()
        scene = self.scene.copy()
        scene.seed = new_seed()
        painting = self._paint(prompt, scene.seed, scene.base, scene.likeness)
        if painting is None:
            return
        scene.image, scene.path = painting.image, self._keep(painting.image)
        self._commit(scene)
        detail = self._painted(painting, scene.likeness)
        self.transcript.say(ui.reply(self.words("again_done"), detail))

    def _undo(self) -> None:
        """Go back to the scene before this one; there is no redo."""
        self._stop_camera()
        earlier = self.history.pop()
        if earlier is None:
            self.transcript.say(ui.reply(self.words("undo_empty"), failed=True))
            return
        self._enter(earlier)
        if earlier.is_empty:
            message = self.words("undo_blank")
        else:
            message = self.words("undo_done", request=earlier.requests[-1])
        self.transcript.say(ui.reply(message))

    def _camera(self, argument: str) -> None:
        """/cam turns the camera on in the picture window, /cam again keeps its
        frame as the picture, /cam off stops it."""
        if argument.strip().lower() == "off":
            self._stop_camera()
            self.transcript.say(ui.reply(self.words("camera_off")))
        elif self.camera_live:
            self._keep_frame()
        else:
            self._start_camera()

    def _start_camera(self) -> None:
        if not camera_installed():
            self.transcript.say(ui.reply(self.words("camera_missing"), failed=True))
            return
        self._started = time.monotonic()
        self._ensure_viewer()
        self.host.wait_connected(timeout=VIEWER_CONNECT_SECONDS)
        reply = self._ask_camera({"type": "camera", "on": True}, "camera_opening")
        if reply is None or "error" in reply:
            # A camera that opens after all must not stay on unseen.
            self.host.send({"type": "camera", "on": False})
            if reply is not None:
                self._camera_failed(reply)
            return
        self.camera_live = True
        self.transcript.say(ui.reply(self.words("camera_on")))

    def _keep_frame(self) -> bool:
        """Make the camera's newest frame the picture, as the window shows it;
        False after saying why not. The camera stops either way."""
        self._started = time.monotonic()
        path = self._next_path()
        reply = self._ask_camera({"type": "camera", "keep": str(path)}, "keeping")
        self.camera_live = False
        if reply is None:
            return False
        if "error" in reply:
            self._camera_failed(reply)
            return False
        try:
            with Image.open(path) as kept:
                image = kept.convert("RGB")
        except (OSError, UnidentifiedImageError) as exc:
            self._camera_failed({"error": str(exc)})
            return False
        scene = Scene()
        scene.record(self.words("camera_request"), "", image, path=path)
        self._commit(scene)
        self.transcript.say(ui.reply(self.words("camera_kept")))
        return True

    def _stop_camera(self) -> None:
        """Stop the live camera, if it is on; the window shows its picture again."""
        if self.camera_live:
            self.host.send({"type": "camera", "on": False})
            self.camera_live = False

    def _ask_camera(self, message: Message, step: str) -> Message | None:
        """Send `message` to the viewer and wait for its camera reply under the
        spinner; None after saying why none came."""
        while not self._camera_replies.empty():  # a late error from earlier
            self._camera_replies.get_nowait()
        if not self.host.send(message):
            self.transcript.say(ui.reply(self.words("camera_no_window"), failed=True))
            return None

        def answer() -> Message | None:
            try:
                return self._camera_replies.get(timeout=CAMERA_SECONDS)
            except queue.Empty:
                return None

        reply = self._wait(answer, step)
        if reply is None:
            self.transcript.say(ui.reply(self.words("camera_silent"), failed=True))
        return reply

    def _camera_failed(self, reply: Message) -> None:
        """Say why the camera did not work, and where its access is allowed."""
        message = self.words("camera_failed", error=reply.get("error", ""))
        hint = CAMERA_HINTS.get(sys.platform)
        detail = self.words(hint) if hint is not None else ""
        self.transcript.say(ui.reply(message, detail, failed=True))

    def _paint(
        self,
        prompt: str,
        seed: int,
        base: Image.Image | None,
        likeness: Reference | None,
    ) -> Painting | None:
        """Paint `prompt` over `base` (None for a new picture) and count it; None
        after saying why it failed."""
        self.host.wait_connected(timeout=VIEWER_CONNECT_SECONDS)
        size = paint_size(self.canvas.aspect)
        try:
            painting: Painting = self._wait(
                lambda: self.painter.paint(prompt, size, seed, base, likeness),
                "painting",
            )
        except PainterError as exc:
            failure = self._api_failure()
            error = str(exc) if failure in (None, exc) else f"{failure}; {exc}"
            message = self.words("failure.paint", error=error)
            # Without Cloudflare only the local model paints; say how to add it.
            hint = self.words("api_missing") if self.api is None else ""
            self.transcript.say(ui.reply(message, hint, failed=True))
            return None
        self._tally(
            lambda usage: usage.add_painting(painting, referenced=likeness is not None)
        )
        return painting

    def _painted(self, painting: Painting, likeness: Reference | None) -> str:
        """The detail under a painted picture: what painted it, how long it took,
        why Cloudflare did not, and after which picture."""
        detail = f"{self.words(f'source.{painting.source}')} · {painting.seconds:.1f}s"
        failure = self._api_failure()
        if painting.source == "local" and failure is not None:
            detail += f" · {failure}"
        if likeness is not None:
            detail += f" · {self.words('reference', host=_host(likeness.url))}"
        return detail

    def _direct(
        self,
        words: str,
        found: Reference | None,
        scene: Scene,
        answers: Sequence[Answer] = (),
    ) -> Direction | None:
        """Claude's direction for `words` in `scene`, shown `found` when there is
        one and told the person's `answers`; None after saying why it failed."""
        picture = found.image if found is not None else None
        try:
            direction = self._wait(
                lambda: self.director.direct(words, scene, picture, answers),
                "directing",
            )
        except DirectorError as exc:
            self.transcript.say(
                ui.reply(self.words(f"failure.{exc.failure}"), failed=True)
            )
            return None
        self._tally(lambda usage: usage.add_direction(direction))
        return direction

    def _ask(self, direction: Direction) -> tuple[Answer, ...] | None:
        """The person's answers to Claude's questions: empty when they skipped
        them (Claude's guess paints), None when they cancelled the request. The
        spinner's clock starts again once they are done."""
        asked = ask_questions(direction.questions, self.words)
        self.bar.redraw()  # the menu erased the bar below it
        if asked.cancelled:
            self.transcript.say(ui.reply(self.words("questions_cancelled")))
            return None
        if asked.answers:
            rows = [(a.header, ", ".join(a.choices)) for a in asked.answers]
            self.transcript.say(ui.answers(rows))
        else:
            self.transcript.say(ui.note(self.words("questions_skipped")))
        self._started = time.monotonic()
        return asked.answers

    def _find_subject(self, direction: Direction) -> Reference | None:
        """The picture of the subject Claude named: an image search first, with a
        key, then Claude's links. Says so when none of them has a usable one."""
        found, searches = self._wait(
            lambda: find_subject(
                direction.subject,
                direction.references,
                self.search_key,
                mature=self.director.mature,
            ),
            "looking",
        )
        if searches:
            self._tally(lambda usage: usage.add_image_searches(searches))
        if found is None:
            subject = direction.subject or self.words("the_subject")
            message = self.words("no_reference", subject=subject)
            self.transcript.say(ui.reply(message, failed=True))
        return found

    def _present(
        self, request: str, found: Reference, message: str, scene: Scene
    ) -> None:
        """Show `found` itself as the picture, whole and on black: what a search
        shows for a bare name, or the picture a bare link points to."""
        width, height = paint_size(self.canvas.aspect)
        image = letterbox(found.cutout or found.image, width, height)
        self.host.wait_connected(timeout=VIEWER_CONNECT_SECONDS)
        scene.record(request, "", image, found, path=self._keep(image))
        self._commit(scene)
        detail = self.words("shown", host=_host(found.url))
        self.transcript.say(ui.reply(message, detail))

    def _commit(self, scene: Scene) -> None:
        """Make `scene` the current one and show it; /undo brings back the one it
        replaces."""
        self.history.push(self.scene)
        self._enter(scene)

    def _enter(self, scene: Scene) -> None:
        """Make `scene` the current one and show its picture, or an empty window."""
        self.scene = scene
        if scene.path is None:
            self.host.send({"type": "clear"})
        else:
            self._show(scene.path)

    def _keep(self, image: Image.Image) -> Path:
        """Save a new picture to the session folder."""
        path = self._next_path()
        image.save(path)
        return path

    def _next_path(self) -> Path:
        """Where the session's next picture goes: 01.png, 02.png, and so on."""
        self._count += 1
        return self.folder / f"{self._count:02d}.png"

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
            self.transcript.say(
                ui.reply(self.words("no_window", error=exc), failed=True)
            )
            return
        self._launched_at = time.monotonic()

    def _wait(self, work: Callable[[], T], step: str) -> T:
        """Run `work` on the worker thread while a spinner turns, labelled with
        `step` and the seconds since the request began."""
        future: Future[T] = self._pool.submit(work)
        frames = ui.SPINNER
        with Live(console=self.console, transient=True, refresh_per_second=12) as live:
            tick = 0
            while not future.done():
                frame = frames[tick % len(frames)]
                seconds = ui.elapsed(time.monotonic() - self._started)
                label = self.words(step, elapsed=seconds)
                live.update(Text.assemble((f" {frame} ", ui.ACCENT), (label, ui.MUTED)))
                tick += 1
                time.sleep(FRAME_SECONDS)
        return future.result()

    def _on_viewer_message(self, message: Message) -> None:
        """A message from the viewer, on the host's reader thread."""
        if message.get("type") == "camera":
            if "error" in message:
                self.camera_live = False  # also when the camera is lost later
            self._camera_replies.put(message)
            return
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
        self.transcript.clear()
        self._draw_screen()

    def _redraw(self) -> None:
        """Draw the window anew at its new size, once it has stopped changing."""
        size = shutil.get_terminal_size()
        while True:
            time.sleep(RESIZE_SETTLE_SECONDS)
            settled = shutil.get_terminal_size()
            if settled == size:
                break
            size = settled
        self._draw_screen()

    def _draw_screen(self) -> None:
        """Welcome box, tip and transcript on a cleared window, at its width."""
        self._drawn_size = shutil.get_terminal_size()
        if self.console.is_terminal:
            self._write(ui.CLEAR)
        self.bar.start()
        self.console.print(ui.welcome(self.words, self.console.width))
        self.console.print(ui.tip(self.words))
        if self.update_notice and self.update_check:
            self.console.print(ui.release_notice(self.words, self.update_notice))
        self.console.print()
        self.transcript.replay()

    def _write(self, sequence: str) -> None:
        self.console.file.write(sequence)
        self.console.file.flush()

    def _status(self) -> str:
        if self.interrupts.armed:
            return f"  {self.words('exit_hint')}"
        window = "●" if self.host.connected else "○"
        model = (
            f"{self.director.model.removeprefix('claude-')} ({self.director.effort})"
        )
        if self.director.mature:
            model += " · mature"
        painter = self.words(f"source.{self.source}")
        art = f"{self.style}/{self.charset}"
        if self.camera_live:
            art += " · camera"
        return f"  /help · {model} · {painter} · {art} · {window} window"


def run_repl() -> int:
    console = Console(highlight=False)
    load_environment()  # first: settings may come from a .env file
    words = ui.Words()
    if api_key() is None and not _first_run(console, words):
        return 1
    try:
        settings = load_settings(chosen=load_choices())
        cloudflare = cloudflare_key()
    except ConfigError as exc:
        console.print(ui.reply(str(exc), failed=True))
        return 2
    key = api_key()
    if key is None:
        return 1
    director = Director(
        create_client(key),
        settings.model,
        settings.effort,
        settings.mature,
        settings.ask,
    )
    api, local = build_painter(cloudflare, settings.image_model)
    if local_model_ready(settings.image_model):
        # About 5 GB of VRAM from now on, but no wait on the first local picture.
        local.load_in_background()
    ledger = Ledger(
        config_dir() / "usage.json",
        lambda: estimate_earlier(
            config_dir() / "history", config_dir() / "sessions", settings.model
        ),
    )
    # Before this session's requests reach the history and its folder prunes one.
    ledger.read()
    folder = new_session_dir(config_dir() / "sessions")
    release_file = config_dir() / "update.json"
    latest = update.notice(release_file) if settings.update_check else ""
    if settings.update_check:

        def refresh() -> None:
            # A convenience must not draw a traceback over the prompt window.
            with contextlib.suppress(Exception):
                update.refresh_release(release_file)

        # The answer shows on the next start; this one never waits for PyPI.
        threading.Thread(target=refresh, name="sepia-release", daemon=True).start()
    repl = Repl(
        console,
        words,
        settings,
        director,
        api,
        local,
        folder,
        ledger,
        search_key(),
        update_notice=latest,
    )
    return repl.run()


def _first_run(console: Console, words: ui.Words) -> bool:
    """Ask for each key in turn, keeping each as it is typed: the Anthropic key is
    needed, Cloudflare and Brave can be skipped with Enter. False without the
    Anthropic key, or on Ctrl+C or Ctrl+D."""
    console.print(ui.reply(words("setup"), words("setup_where", path=user_env_file())))
    try:
        for key in KEYS:
            values = _ask_key(console.print, words, key)
            if values:
                save_keys(values)
                os.environ.update(values)
            elif key.name == "anthropic":
                return False
    except (EOFError, KeyboardInterrupt):
        return False
    return True


def _ask_key(
    say: Callable[[RenderableType], None], words: ui.Words, key: Key
) -> dict[str, str]:
    """Say what `key` is for and where to get it, then ask for it, hidden."""
    say(ui.reply(words(f"keys.{key.name}"), words(f"keys.{key.name}.where")))
    return ask_values(
        key, lambda variable: ask_secret(words("keys.ask", variable=variable))
    )
