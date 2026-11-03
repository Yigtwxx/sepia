# /play: a video link, played as text

`/play <link>` downloads a short video to a temporary folder, plays it in the
picture window the way `/cam` shows the webcam, and deletes it afterwards.

## Decisions

- Started only by `/play <link>` (no quotes). A link pasted in a request keeps
  its current meaning: a reference picture (a YouTube link gives its thumbnail).
- Videos longer than **60 seconds** are refused, as are live streams and
  playlists that are not a single video. Nothing is downloaded when the length
  is known beforehand; when it is not, the file is measured after the download
  and deleted if it is too long.
- The video goes to a temporary file, never streamed, and is deleted when it
  ends, when it is stopped, and when sepia closes. Leftovers from a crash are
  removed the next time sepia starts.
- Picture only, no sound. Played once at its own speed, not mirrored.
- No API key: yt-dlp needs none, and neither Claude nor Cloudflare is called.

## Dependencies

New optional extra:

```toml
# /play: videos from YouTube and other sites (about 100 MB with Deno).
video = ["yt-dlp[default,deno]>=2026.10.26", "opencv-python-headless>=5.0.0.93"]
```

YouTube needs a JavaScript runtime for its challenges. yt-dlp's `deno` extra
installs the `deno` package from PyPI, whose binary lands in the environment's
scripts folder, the first place yt-dlp looks (`yt_dlp/utils/_jsruntime.py`,
`_find_exe`). `default` brings `yt-dlp-ejs`, the challenge scripts. No ffmpeg:
only single, video-only (or combined) formats are chosen, so nothing is merged.

mypy treats `yt_dlp` like `cv2`: missing imports ignored, used through small
Protocols. Both are imported inside functions only.

## Flow

```
/play <link>
  prompt: check link (https, public host) → video extra installed?
  prompt: stop camera / video that is live
  prompt (spinner "fetching the video"): yt-dlp probe → refuse long/live
          → download ≤480p, ≤100 MB into sepia-video-XXXX/
  prompt → viewer: {"type": "video", "path": ".../video.mp4"}
  viewer: VideoFile opens it, first frame → {"type": "video", "state": "on"}
  prompt: "Playing: <title> · 0:42 — /play off stops it", status "· video"
  viewer: last frame (or 60 s) → {"type": "video", "state": "ended", "path": …}
  prompt (reader thread): video off, folder deleted
```

`/play off` sends `{"type": "video", "on": false}`; the viewer stops and
replies `{"type": "video", "state": "off", "path": …}`, and the prompt deletes
the folder on that reply. The viewer has let go of the file before it replies,
so Windows allows the delete.

## Units

### `src/sepia/video.py` (new)

- `video_installed() -> bool`: `yt_dlp` and `cv2` are importable.
- `VideoError(Exception)`: carries a `reason` for the interface:
  `unusable` (not https or not public), `too_long`, `live`, `not_a_video`
  (a playlist or channel), `too_big`, `failed` (yt-dlp's own short message,
  without its `ERROR:` prefix or color codes).
- `Video` (frozen dataclass): `path`, `title`, `seconds` (float or None),
  `host`.
- `fetch(url, folder) -> Video`: checks the link with `reference.check_link`
  (the current `_check`, made public), probes with
  `YoutubeDL.extract_info(download=False, process=False)` so that a playlist
  or channel is refused before its entries are resolved, follows `url` and
  `url_transparent` results at most three times, refuses as above, then
  `process_ie_result(info, download=True)`. A progress hook stops the
  download past 100 MB (a stream in pieces announces no size, so
  `max_filesize` alone misses it) and when sepia closes (`cancel`). Errors are
  raised outside the `except` block, so yt-dlp's frames, which hold the
  unfinished file open, are gone before the prompt deletes the folder. Titles
  and messages lose terminal control characters. Options: format
  `bv*[height<=480][vcodec^=avc1]/bv*[height<=480]/b[height<=480]/wv*/w`,
  `outtmpl` `video.%(ext)s` in the folder, `noplaylist`, `max_filesize`
  100 MB, a silent logger (nothing prints over the prompt), short socket
  timeout. No file afterwards means `too_big`. Unknown length is measured with
  `video_seconds` and refused over 60 s (plus one second of slack).
- `new_folder() -> Path`: `tempfile.mkdtemp(prefix="sepia-video-")`.
- `discard(folder)`: delete it, ignoring errors.
- `sweep(root=tempdir, older_than=3600 s)`: delete `sepia-video-*` folders
  older than an hour. A running sepia's video is never that old (60 s), so a
  second sepia window is never disturbed.
- `video_seconds(path) -> float | None`: frame count over frame rate.
- `VideoFile`: the same shape as `Camera` (`start`, `latest`, `stop`,
  `failed`) plus `ended` and `path`. Reads on a thread, paced by the video's
  own frame rate (30 when the file does not say), skipping frames when behind,
  ending at the last frame or at 60 s. Frames are BGR to RGB, not mirrored.
  `start` raises `VideoError` when OpenCV cannot open the file. The playing
  thread releases the file itself as it ends (OpenCV is not safe to release
  during a read); an error while reading marks it failed. The reader is
  injected (`open_video`) so tests never touch OpenCV.

### `src/sepia/camera.py`

`Camera` gains `ended = False` (a camera never ends), so both sources share one
shape: a `FrameSource` Protocol in `viewer.py`.

### `src/sepia/viewer.py`

`LiveView` holds one `FrameSource` at a time and the message type it answers
with (`camera` or `video`):

- `{"type": "camera", "on": true}` / `keep` / `on: false`: as today.
- `{"type": "video", "path": p}`: stop any live source, start `VideoFile(p)`;
  error replies `{"type": "video", "error": …, "path": p}`.
- `{"type": "video", "on": false}`: stop the video; reply `state: off` with its
  path. An `off` for the other kind is ignored.
- `step`: the first frame says `state: on`; `ended` stops and replies
  `state: ended` with the path; `failed` stops and replies an error.

Drawing, frame rate (15 a second at most) and the redraw of the picture
afterwards are the camera's.

### `src/sepia/repl.py`

- `/play` without a link says how to use it; `/play off` stops the video
  ("Video off"); `/play <link>` as in the flow.
- `video_live` beside `camera_live`; `_stop_camera` becomes `_stop_live`,
  which stops either. Requests, `/again`, `/undo`, `/clear` and `/cam` stop a
  video; `/play` stops the camera.
- The camera reply queue carries video replies too (`on` and errors);
  `_on_viewer_message` handles `ended`, `off` and errors with a path by marking
  the video off and deleting the folder, only if it is one this session made.
- On exit a playing video is stopped first and the window gets up to three
  seconds to let go of it; a download in progress is cancelled; then every
  folder this session made is deleted. A folder that could not be deleted
  (still open) stays on the list and is tried again on exit. On start
  `sweep()` runs.
- A video whose every frame came too late to draw ends before "on": the
  prompt says it ended before a frame could be shown.
- Status line: `· video` while playing.

### `src/sepia/ui.py`

New strings (`video_usage`, `video_missing`, `fetching_video`,
`video_opening`, `video_on`, `video_off`, `video_failed.*`, `video_silent`)
and a `/play <link|off>` row in `COMMANDS`, after `/cam`.

### Docs

README (feature line, install `sepia-cli[video]`, the command row, privacy:
the link goes to the video's site through yt-dlp, the file stays local and is
deleted), CHANGELOG under `[Unreleased]`.

## Errors

| Case | Said |
|---|---|
| extra missing | needs `sepia-cli[video]` |
| not https / private host | link unusable |
| longer than 60 s | "That video is 3:12; /play takes up to 60 seconds" |
| live stream / playlist | refused with the reason |
| yt-dlp fails (bot check, removed video, network) | its short message |
| over 100 MB at 480p | too big |
| viewer cannot open the file | the error, folder deleted |
| viewer does not answer | "did not answer in time", video stopped |

## Tests

No network, no OpenCV, no real yt-dlp:

- `tests/test_video.py`: `fetch` with a fake `YoutubeDL` (refuses long, live,
  playlists; downloads into the folder; `too_big` without a file; maps
  `DownloadError`; unknown length measured); `sweep` age rule; `discard`;
  `VideoFile` with a fake reader (pacing with a fake clock, RGB not mirrored,
  ends at the last frame and at 60 s, fails to open).
- `tests/test_viewer.py`: video on/off/ended/error replies, a video replaces a
  live camera, `off` for the other kind is ignored.
- `tests/test_repl.py`: `/play` usage, missing extra, refused video, success
  (status, reply), `/play off`, ended deletes the folder, exit deletes it,
  a request stops the video.
