import os
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sepia import video
from sepia.video import (
    MAX_BYTES,
    MAX_SECONDS,
    Video,
    VideoError,
    VideoFile,
    discard,
    fetch,
    new_folder,
    sweep,
    video_installed,
    video_seconds,
)

LINK = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
ZOO: dict[str, Any] = {
    "title": "Me at the zoo",
    "duration": 19,
    "live_status": "not_live",
}


class FakeDownloader:
    """Stands in for yt-dlp's `YoutubeDL`, which reaches the web: answers the probe
    with `info` (or, for a link it names, with `elsewhere[link]`) and "downloads"
    by reporting `progress` to the progress hooks and writing a small file where
    the options say, or fails as yt-dlp does."""

    def __init__(
        self,
        info: dict[str, Any] | None = None,
        writes: str | None = "video.mp4",
        error: Exception | None = None,
        elsewhere: dict[str, dict[str, Any]] | None = None,
        progress: tuple[int, ...] = (),
    ) -> None:
        self.info = dict(ZOO if info is None else info)
        self.writes = writes
        self.error = error
        self.elsewhere = elsewhere or {}
        self.progress = progress
        self.options: dict[str, Any] = {}
        self.probed: list[str] = []
        self.processed: list[bool] = []
        """`process` of each probe: True resolves every entry of a playlist."""
        self.downloaded = False

    def __call__(self, options: dict[str, Any]) -> "FakeDownloader":
        self.options = options
        return self

    def __enter__(self) -> "FakeDownloader":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def extract_info(
        self,
        url: str,
        download: bool = True,
        ie_key: str | None = None,
        extra_info: dict[str, Any] | None = None,
        process: bool = True,
    ) -> dict[str, Any]:
        assert not download, "The probe must not download"
        self.probed.append(url)
        self.processed.append(process)
        if self.error is not None:
            raise self.error
        return dict(self.elsewhere.get(url, self.info))

    def process_ie_result(
        self, ie_result: dict[str, Any], download: bool = True
    ) -> dict[str, Any]:
        self.downloaded = download
        for done in self.progress:
            for hook in self.options["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": done})
        if self.writes is not None:
            folder = Path(self.options["outtmpl"]["default"]).parent
            (folder / self.writes).write_bytes(b"not really a video")
        return ie_result


class FakeReader:
    """Stands in for `cv2.VideoCapture` on a file: gives `frames` in turn, then
    nothing, as a file does at its end."""

    def __init__(
        self,
        frames: list[np.ndarray] | None = None,
        fps: float = 30.0,
        count: float | None = None,
        opened: bool = True,
        endless: bool = False,
    ) -> None:
        self.frames = list(frames if frames is not None else [_bgr((0, 0, 0))])
        self.fps = fps
        self.count = float(len(self.frames)) if count is None else count
        self.opened = opened
        self.endless = endless
        self.reads = 0
        self.released = False

    def isOpened(self) -> bool:
        return self.opened

    def read(self) -> tuple[bool, np.ndarray | None]:
        self.reads += 1
        if self.endless:
            return True, self.frames[0]
        if self.frames:
            return True, self.frames.pop(0)
        return False, None

    def get(self, prop: int) -> float:
        return {video.CAP_PROP_FPS: self.fps, video.CAP_PROP_FRAME_COUNT: self.count}[
            prop
        ]

    def release(self) -> None:
        self.released = True


def _bgr(*pixels: tuple[int, int, int]) -> np.ndarray:
    """One row of BGR pixels, as OpenCV gives them."""
    return np.array([pixels], dtype=np.uint8)


def _eventually(condition: Callable[[], bool], seconds: float = 2.0) -> bool:
    """Whether `condition` turns true before `seconds` pass (a video plays on a
    thread of its own)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every host resolves to a public address, without asking a DNS server."""
    public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("142.250.74.14", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: public)


# --- fetch -------------------------------------------------------------------------


def test_fetch_short_video_downloads_it_into_the_folder(
    tmp_path: Path, public_dns: None
) -> None:
    downloader = FakeDownloader()
    found = fetch(LINK, tmp_path, make=downloader)
    expected = Video(tmp_path / "video.mp4", "Me at the zoo", 19.0, "www.youtube.com")
    assert found == expected, f"Got {found}"
    assert downloader.probed == [LINK], f"Probed {downloader.probed}"
    assert downloader.downloaded, "A short video must be downloaded"


def test_fetch_options_pick_one_small_file_quietly(
    tmp_path: Path, public_dns: None
) -> None:
    downloader = FakeDownloader()
    fetch(LINK, tmp_path, make=downloader)
    options = downloader.options
    assert options["format"] == video.FORMAT, f"Format {options['format']}"
    assert "+" not in options["format"], "Merging two files needs ffmpeg"
    assert options["noplaylist"] is True, "A video in a playlist is that video"
    assert options["max_filesize"] == MAX_BYTES, "Downloads must have a size limit"
    assert options["quiet"] and options["noprogress"], "Nothing prints over the bar"
    assert options["logger"] is not None, "yt-dlp's messages must not reach the screen"
    template = Path(options["outtmpl"]["default"])
    assert template.parent == tmp_path, f"Downloads to {template}"


def test_fetch_video_over_sixty_seconds_is_refused_without_downloading(
    tmp_path: Path, public_dns: None
) -> None:
    downloader = FakeDownloader({**ZOO, "duration": MAX_SECONDS + 1})
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=downloader)
    assert raised.value.reason == "too_long", f"Reason {raised.value.reason}"
    assert raised.value.seconds == MAX_SECONDS + 1, "Its length is named"
    assert not downloader.downloaded, "Nothing is downloaded when it is too long"


def test_fetch_video_of_exactly_sixty_seconds_is_played(
    tmp_path: Path, public_dns: None
) -> None:
    downloader = FakeDownloader({**ZOO, "duration": MAX_SECONDS})
    assert fetch(LINK, tmp_path, make=downloader).seconds == MAX_SECONDS


@pytest.mark.parametrize(
    "info",
    [
        {"title": "News", "is_live": True},
        {"title": "News", "live_status": "is_live"},
        {"title": "Soon", "live_status": "is_upcoming"},
    ],
)
def test_fetch_live_stream_is_refused(
    tmp_path: Path, public_dns: None, info: dict[str, Any]
) -> None:
    downloader = FakeDownloader(info)
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=downloader)
    assert raised.value.reason == "live", f"{info}: reason {raised.value.reason}"
    assert not downloader.downloaded, "A live stream is never downloaded"


@pytest.mark.parametrize("kind", ["playlist", "multi_video"])
def test_fetch_playlist_is_refused(tmp_path: Path, public_dns: None, kind: str) -> None:
    downloader = FakeDownloader({"_type": kind, "title": "Mix", "entries": []})
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=downloader)
    assert raised.value.reason == "not_a_video", f"Reason {raised.value.reason}"


@pytest.mark.parametrize(
    "link", ["http://www.youtube.com/watch?v=x", "ftp://example.com/a.mp4", "youtube"]
)
def test_fetch_link_without_https_is_unusable(
    tmp_path: Path, public_dns: None, link: str
) -> None:
    downloader = FakeDownloader()
    with pytest.raises(VideoError) as raised:
        fetch(link, tmp_path, make=downloader)
    assert raised.value.reason == "unusable", f"{link}: {raised.value.reason}"
    assert downloader.probed == [], "yt-dlp must not be asked"


def test_fetch_link_to_a_private_host_is_unusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: private)
    downloader = FakeDownloader()
    with pytest.raises(VideoError) as raised:
        fetch("https://nas.local/clip.mp4", tmp_path, make=downloader)
    assert raised.value.reason == "unusable", f"Reason {raised.value.reason}"
    assert downloader.probed == [], "yt-dlp must not be asked"


def test_fetch_probe_never_resolves_every_entry_of_a_playlist(
    tmp_path: Path, public_dns: None
) -> None:
    downloader = FakeDownloader({"_type": "playlist", "title": "NASA", "entries": []})
    with pytest.raises(VideoError):
        fetch("https://www.youtube.com/@NASA", tmp_path, make=downloader)
    assert downloader.processed == [False], f"Probed with {downloader.processed}"


def test_fetch_link_to_another_link_follows_it(
    tmp_path: Path, public_dns: None
) -> None:
    short = {"_type": "url", "url": LINK, "ie_key": "Youtube"}
    downloader = FakeDownloader(short, elsewhere={LINK: ZOO})
    found = fetch("https://youtu.be/jNQXAC9IVRw", tmp_path, make=downloader)
    assert downloader.probed[1:] == [LINK], f"Probed {downloader.probed}"
    assert downloader.processed == [False, False], "No probe resolves entries"
    assert found.title == "Me at the zoo", f"Got {found}"


def test_fetch_link_to_a_playlist_is_refused(tmp_path: Path, public_dns: None) -> None:
    hop = {"_type": "url_transparent", "url": "https://example.com/list"}
    playlist = {"_type": "playlist", "entries": []}
    downloader = FakeDownloader(hop, elsewhere={"https://example.com/list": playlist})
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=downloader)
    assert raised.value.reason == "not_a_video", f"Reason {raised.value.reason}"
    assert not downloader.downloaded, "A playlist is never downloaded"


def test_fetch_links_that_never_end_are_refused(
    tmp_path: Path, public_dns: None
) -> None:
    loop = {"_type": "url", "url": LINK}
    downloader = FakeDownloader(loop)
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=downloader)
    assert raised.value.reason == "not_a_video", f"Reason {raised.value.reason}"
    assert len(downloader.probed) == video.MAX_HOPS + 1, f"{downloader.probed}"


def test_fetch_stream_past_the_size_limit_is_stopped_as_too_big(
    tmp_path: Path, public_dns: None
) -> None:
    # A stream in pieces announces no size, so max_filesize never sees it.
    downloader = FakeDownloader(progress=(MAX_BYTES // 2, MAX_BYTES + 1))
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=downloader)
    assert raised.value.reason == "too_big", f"Reason {raised.value.reason}"


def test_fetch_cancelled_stops_the_download(tmp_path: Path, public_dns: None) -> None:
    cancel = threading.Event()
    cancel.set()
    downloader = FakeDownloader(progress=(1024,))
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=downloader, cancel=cancel)
    assert raised.value.detail == "cancelled", f"Detail {raised.value.detail!r}"


def test_fetch_failure_holds_no_reference_to_yt_dlp(
    tmp_path: Path, public_dns: None
) -> None:
    # yt-dlp's frames keep its unfinished file open, which Windows cannot delete.
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=FakeDownloader(error=RuntimeError("HTTP 403")))
    assert raised.value.__cause__ is None, "The failure must not chain yt-dlp's error"
    assert raised.value.__context__ is None, "Nor keep it as its context"


def test_fetch_title_and_errors_lose_terminal_control_characters(
    tmp_path: Path, public_dns: None
) -> None:
    sly = {**ZOO, "title": "Me\x1b[2J at the\x07 zoo\x9b"}
    assert fetch(LINK, tmp_path, make=FakeDownloader(sly)).title == "Me[2J at the zoo"
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=FakeDownloader(error=RuntimeError("bad\x1b]0;x")))
    assert raised.value.detail == "bad]0;x", f"Detail {raised.value.detail!r}"


def test_fetch_without_a_file_afterwards_is_too_big(
    tmp_path: Path, public_dns: None
) -> None:
    # yt-dlp skips a file over max_filesize without raising.
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=FakeDownloader(writes=None))
    assert raised.value.reason == "too_big", f"Reason {raised.value.reason}"


def test_fetch_ignores_unfinished_parts(tmp_path: Path, public_dns: None) -> None:
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=FakeDownloader(writes="video.mp4.part"))
    assert raised.value.reason == "too_big", "A .part file is not a video"


def test_fetch_yt_dlp_error_gives_its_short_message(
    tmp_path: Path, public_dns: None
) -> None:
    message = (
        "\x1b[0;31mERROR:\x1b[0m [youtube] abc: Sign in to confirm you're not a bot\n"
        "Use --cookies-from-browser"
    )
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=FakeDownloader(error=RuntimeError(message)))
    assert raised.value.reason == "failed", f"Reason {raised.value.reason}"
    expected = "[youtube] abc: Sign in to confirm you're not a bot"
    assert raised.value.detail == expected, f"Detail {raised.value.detail!r}"


def test_fetch_unknown_length_is_measured_after_the_download(
    tmp_path: Path, public_dns: None
) -> None:
    downloader = FakeDownloader({"title": "clip"})
    found = fetch(LINK, tmp_path, make=downloader, measure=lambda path: 12.5)
    assert found.seconds == 12.5, f"Measured {found.seconds}"


def test_fetch_unknown_length_over_sixty_seconds_is_refused(
    tmp_path: Path, public_dns: None
) -> None:
    downloader = FakeDownloader({"title": "clip"})
    with pytest.raises(VideoError) as raised:
        fetch(LINK, tmp_path, make=downloader, measure=lambda path: 75.0)
    assert raised.value.reason == "too_long", f"Reason {raised.value.reason}"
    assert raised.value.seconds == 75.0, "The measured length is named"


def test_fetch_unknown_length_within_a_second_over_is_played(
    tmp_path: Path, public_dns: None
) -> None:
    # Frame counts are estimates; a 60 s clip may count a few frames more.
    downloader = FakeDownloader({"title": "clip"})
    found = fetch(LINK, tmp_path, make=downloader, measure=lambda path: 60.5)
    assert found.seconds == 60.5, "A clip a fraction over is still played"


def test_fetch_length_that_cannot_be_measured_is_played(
    tmp_path: Path, public_dns: None
) -> None:
    downloader = FakeDownloader({"title": "clip"})
    found = fetch(LINK, tmp_path, make=downloader, measure=lambda path: None)
    assert found.seconds is None, "VideoFile stops at 60 s on its own"


# --- folders -----------------------------------------------------------------------


def test_new_folder_is_named_for_sepia(tmp_path: Path) -> None:
    folder = new_folder(tmp_path)
    assert folder.is_dir() and folder.parent == tmp_path, f"Made {folder}"
    assert folder.name.startswith(video.FOLDER_PREFIX), f"Named {folder.name}"


def test_discard_deletes_the_folder_and_its_video(tmp_path: Path) -> None:
    folder = new_folder(tmp_path)
    (folder / "video.mp4").write_bytes(b"x")
    discard(folder)
    assert not folder.exists(), "The folder must be gone"


def test_discard_of_a_missing_folder_does_nothing(tmp_path: Path) -> None:
    discard(tmp_path / "gone")  # must not raise


def test_sweep_deletes_only_old_sepia_folders(tmp_path: Path) -> None:
    old, fresh = new_folder(tmp_path), new_folder(tmp_path)
    other = tmp_path / "someone-else"
    other.mkdir()
    now = time.time()
    for folder in (old, other):
        os.utime(folder, (now - 7200, now - 7200))
    sweep(tmp_path, now=now)
    assert not old.exists(), "A folder left from a crash must be deleted"
    assert fresh.exists(), "Another sepia's video playing now must stay"
    assert other.exists(), "Folders that are not sepia's are never touched"


# --- video_seconds -----------------------------------------------------------------


def test_video_seconds_is_frames_over_frame_rate(tmp_path: Path) -> None:
    reader = FakeReader(fps=30.0, count=90.0)
    assert video_seconds(tmp_path / "v.mp4", lambda path: reader) == 3.0
    assert reader.released, "The file must be let go"


@pytest.mark.parametrize(
    "reader",
    [FakeReader(fps=0.0, count=90.0), FakeReader(count=0.0), FakeReader(opened=False)],
)
def test_video_seconds_unknown_is_none(tmp_path: Path, reader: FakeReader) -> None:
    assert video_seconds(tmp_path / "v.mp4", lambda path: reader) is None


def test_video_seconds_when_opening_fails_is_none(tmp_path: Path) -> None:
    def refuse(path: str) -> FakeReader:
        raise RuntimeError("no codec")

    assert video_seconds(tmp_path / "v.mp4", refuse) is None


# --- VideoFile ---------------------------------------------------------------------


def test_video_file_frames_are_rgb_and_not_mirrored() -> None:
    reader = FakeReader([_bgr((1, 2, 3), (4, 5, 6))])
    playing = VideoFile("v.mp4", lambda path: reader)
    playing.start()
    assert _eventually(lambda: playing.latest() is not None), "No frame came"
    frame = playing.latest()
    assert frame is not None and frame.tolist() == [[[3, 2, 1], [6, 5, 4]]], (
        f"Got {None if frame is None else frame.tolist()}"
    )
    assert frame.flags["C_CONTIGUOUS"], "Pillow and numpy want a plain array"
    playing.stop()


def test_video_file_ends_after_its_last_frame() -> None:
    reader = FakeReader([_bgr((0, 0, 0))] * 3, fps=200.0)
    playing = VideoFile("v.mp4", lambda path: reader)
    playing.start()
    assert _eventually(lambda: playing.ended), "The video must end"
    assert not playing.failed, "An ending is not a failure"
    playing.stop()
    assert reader.released, "Stopping must let go of the file"


def test_video_file_stops_at_sixty_seconds() -> None:
    reader = FakeReader(fps=1.0, endless=True)
    far_behind = iter([0.0, *[1e9] * 1000])  # every frame is already late
    playing = VideoFile("v.mp4", lambda path: reader, clock=lambda: next(far_behind))
    playing.start()
    assert _eventually(lambda: playing.ended), "A long file must end at 60 s"
    playing.stop()
    assert reader.reads == MAX_SECONDS + 1, f"Read {reader.reads} frames"


def test_video_file_without_a_limit_plays_past_a_minute() -> None:
    frames = MAX_SECONDS + 5
    reader = FakeReader([_bgr((0, 0, 0))] * frames, fps=1.0)
    far_behind = iter([0.0, *[1e9] * 1000])  # every frame is already late
    playing = VideoFile(
        "v.mp4", lambda path: reader, clock=lambda: next(far_behind), limit=None
    )
    playing.start()
    assert _eventually(lambda: playing.ended), "The video must end at its last frame"
    playing.stop()
    assert reader.reads == frames + 1, f"Read {reader.reads} frames, not all"


def test_video_file_late_frames_are_skipped() -> None:
    first, late = _bgr((0, 0, 255)), _bgr((255, 0, 0))
    reader = FakeReader([first, late], fps=1.0)
    times = iter([0.0, 0.0, 5.0, 5.0, 5.0])
    playing = VideoFile("v.mp4", lambda path: reader, clock=lambda: next(times, 5.0))
    playing.start()
    assert _eventually(lambda: playing.ended), "The video must end"
    frame = playing.latest()
    assert frame is not None and frame.tolist() == [[[255, 0, 0]]], (
        "The first frame is shown; the second, four seconds late, is skipped"
    )
    playing.stop()


def test_video_file_waits_for_each_frame_time() -> None:
    reader = FakeReader([_bgr((0, 0, 0))] * 4, fps=20.0)
    playing = VideoFile("v.mp4", lambda path: reader)
    began = time.monotonic()
    playing.start()
    assert _eventually(lambda: playing.ended), "The video must end"
    taken = time.monotonic() - began
    assert taken >= 0.12, f"Four frames at 20 a second took only {taken:.3f}s"
    playing.stop()


def test_video_file_without_a_frame_rate_plays_at_thirty() -> None:
    reader = FakeReader([_bgr((0, 0, 0))] * 2, fps=0.0)
    playing = VideoFile("v.mp4", lambda path: reader)
    playing.start()
    assert _eventually(lambda: playing.ended), "A file without a rate still plays"
    playing.stop()


def test_video_file_that_cannot_be_opened_raises_and_lets_go() -> None:
    reader = FakeReader(opened=False)
    with pytest.raises(VideoError):
        VideoFile("v.mp4", lambda path: reader).start()
    assert reader.released, "A file that never opened must be released"


def test_video_file_when_opening_fails_names_the_error() -> None:
    def refuse(path: str) -> FakeReader:
        raise RuntimeError("no codec")

    with pytest.raises(VideoError, match="no codec"):
        VideoFile("v.mp4", refuse).start()


def test_video_file_lets_go_of_the_file_when_it_ends() -> None:
    # Before stop: the prompt deletes the file once the window says it ended.
    reader = FakeReader([_bgr((0, 0, 0))], fps=200.0)
    playing = VideoFile("v.mp4", lambda path: reader)
    playing.start()
    assert _eventually(lambda: reader.released), "An ended video must let go"
    playing.stop()


def test_video_file_read_error_fails_and_lets_go() -> None:
    reader = FakeReader()

    def broken() -> tuple[bool, None]:
        raise RuntimeError("decoder crashed")

    reader.read = broken  # type: ignore[method-assign]
    playing = VideoFile("v.mp4", lambda path: reader)
    playing.start()
    assert _eventually(lambda: playing.failed), "A read error is a failure"
    assert _eventually(lambda: reader.released), "The file must be let go"
    playing.stop()


def test_video_file_without_any_frame_fails() -> None:
    reader = FakeReader([])
    playing = VideoFile("v.mp4", lambda path: reader)
    playing.start()
    assert _eventually(lambda: playing.failed), "A file without frames failed"
    playing.stop()


def test_video_file_stop_ends_the_wait_at_once() -> None:
    reader = FakeReader([_bgr((0, 0, 0))] * 2, fps=0.2)  # five seconds a frame
    playing = VideoFile("v.mp4", lambda path: reader)
    playing.start()
    assert _eventually(lambda: playing.latest() is not None), "No frame came"
    began = time.monotonic()
    playing.stop()
    assert time.monotonic() - began < 1.0, "Stopping must not wait for the next frame"
    assert reader.released, "Stopping must let go of the file"


# --- the extra ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("present", "expected"),
    [({"yt_dlp", "cv2"}, True), ({"cv2"}, False), ({"yt_dlp"}, False)],
)
def test_video_installed_needs_yt_dlp_and_opencv(
    monkeypatch: pytest.MonkeyPatch, present: set[str], expected: bool
) -> None:
    def find_spec(name: str) -> object | None:
        return object() if name in present else None

    monkeypatch.setattr(video.importlib.util, "find_spec", find_spec)
    assert video_installed() is expected, f"With {present}: {not expected}"
