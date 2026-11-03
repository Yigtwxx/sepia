# /play Implementation Plan

> Executed inline (light process for small features): one implementation pass,
> then one review of the whole diff.

**Goal:** `/play <link>` downloads a video of at most 60 seconds to a temporary
folder, plays it in the picture window as text, and deletes it afterwards.

**Architecture:** the prompt fetches with yt-dlp under the spinner
(`video.fetch`), the viewer plays the file through the camera's `LiveView`
with a `VideoFile` source, and the prompt deletes the folder when the viewer
says the video ended or stopped. Spec:
`docs/superpowers/specs/2026-11-03-play-video-design.md`.

**Tech Stack:** yt-dlp (with Deno and yt-dlp-ejs), OpenCV, the existing IPC
channel and live view.

## Global Constraints

- Optional extra `video = ["yt-dlp[default,deno]>=2026.10.26",
  "opencv-python-headless>=5.0.0.93"]`; `yt_dlp` and `cv2` imported inside
  functions only.
- 60 s limit (`MAX_SECONDS = 60`), refused not cut; 480p, 100 MB at most.
- https and public hosts only (`reference.check_link`).
- No network, OpenCV or yt-dlp in tests; every assert has a message; names
  `test_<unit>_<scenario>_<expected>`.
- Strings in `ui.STRINGS`, English only. mypy strict, ruff clean.

---

### Task 1: `video.py` (fetch, folders, VideoFile)

**Files:** create `src/sepia/video.py`, `tests/test_video.py`; modify
`src/sepia/reference.py` (`_check` → `check_link`), `pyproject.toml` (extra,
mypy override for `yt_dlp`).

**Produces:** `video_installed() -> bool`, `VideoError(reason, detail="")`,
`Video(path, title, seconds, host)`, `fetch(url, folder, make=…) -> Video`,
`new_folder(root=None) -> Path`, `discard(folder) -> None`,
`sweep(root=None, older_than=3600, now=None) -> None`,
`video_seconds(path, open_video=…) -> float | None`,
`VideoFile(path, open_video=…, clock=…)` with `start/latest/stop/failed/ended/path`.

- [ ] Tests first: refusals (long, live, playlist, unusable link), download
  into the folder, `too_big`, `DownloadError` mapping, unknown length measured,
  sweep age rule, `VideoFile` pacing, colors, end at last frame and at 60 s,
  open failure.
- [ ] Implement; `uv run pytest tests/test_video.py`.

### Task 2: the viewer plays videos

**Files:** `src/sepia/viewer.py`, `src/sepia/camera.py` (`ended = False`),
`tests/test_viewer.py`.

**Consumes:** `VideoFile`, `VideoError`.
**Produces:** messages `{"type": "video", "path"}`, `{"type": "video", "on":
false}`; replies `state: on | off | ended` (with `path`) and `error` (with
`path`).

- [ ] Tests: video on replies on; off replies off with path; ended replies
  ended; open failure replies error; a video replaces a live camera; `off` for
  the other kind ignored; camera tests unchanged.
- [ ] Generalize `LiveView` over a `FrameSource` Protocol.

### Task 3: `/play` in the prompt

**Files:** `src/sepia/repl.py`, `src/sepia/ui.py`, `tests/test_repl.py`.

- [ ] Tests: usage, missing extra, refused video says why and deletes the
  folder, success sends the path and says playing, status `· video`, `/play
  off`, ended/off replies delete the folder, exit deletes folders, a request
  stops the video, `/cam` stops the video, sweep at start.
- [ ] Implement `_play`, `_stop_live`, reply handling, cleanup.

### Task 4: docs and checks

- [ ] README (features, install, command row, privacy), CHANGELOG
  `[Unreleased]`.
- [ ] `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`,
  `uv run pytest`.
- [ ] One review of the whole diff.
