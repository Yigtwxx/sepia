# /undo, /again and /cam

Three commands for the prompt window. `/undo` steps back through the session's
pictures, `/again` paints the latest prompt again with fresh noise, and `/cam`
shows the webcam live in the picture window and keeps a frame as the picture.

## /undo and /again

### Scene history

`Scene` gets two fields and a copy:

- `path: Path | None`: where the picture is kept in the session folder; the
  viewer reads it there, and `/undo` shows it again from there.
- `base: Image | None`: the picture the latest one was painted over (`/add`),
  so `/again` paints over the same one.
- `copy()`: a scene to change while the current one stays as it was. Lists are
  copied; pictures are shared, since nothing changes a picture in place.

`History` (in `scene.py`) keeps earlier scenes, newest last, at most
`UNDO_LIMIT = 20` (a picture is about 2 MB). `Scene.reset` goes: every change
builds a new scene and the prompt window *commits* it, which pushes the scene it
replaces.

A change is committed only once it succeeded:

- a painted picture (request or `/add`), a picture shown as found, `/again`,
  a kept camera frame: push the old scene, the new one becomes current;
- `/clear` with a picture: push it, an empty scene becomes current.

A new request no longer empties the scene before it is painted. Today a failed
request leaves the scene empty while the window still shows the old picture,
so `/save` says there is nothing to save; now the old picture stays.

### Commands

- `/undo`: the scene before the current one comes back with its requests,
  prompts, seed and reference, and the window shows its picture (or clears, for
  the empty scene before the first picture). A following `/add` builds on it.
  With nothing left: "Nothing to undo". There is no redo.
- `/again`: paints `prompts[-1]` with a new seed, over `base` when the picture
  was an `/add`, with the scene's reference. No call to Claude. The reply shows
  the painter and time as a request does, and usage counts the picture. A
  picture shown as found (a link, a search result, a camera frame) has no
  prompt: "That picture was shown as it is, so there is nothing to paint again".
  An empty scene: "Nothing to paint again yet".

## /cam

### Choice

The viewer opens the camera and draws it. The prompt window only sends
`camera` messages; frames never cross the channel. (Sending ANSI over the
channel would be about 3 MB/s of JSON in the process that runs the spinner, and
PNG files would be 15 writes a second.)

### Install

Optional extra `cam = ["opencv-python-headless>=5.0.0.93"]`, imported inside
functions only, like torch. `/cam` without it says to install
`sepia-cli[cam]`. mypy ignores the missing `cv2` stubs, as for torch.

### Messages

Prompt to viewer:

- `{"type": "camera", "on": true}`: open the camera and show it live.
- `{"type": "camera", "on": false}`: stop; the window shows its picture again.
- `{"type": "camera", "keep": "<path>"}`: save the newest frame there as a
  PNG, stop, and show it.

Viewer to prompt:

- `{"type": "camera", "state": "on"}` once the camera gives frames.
- `{"type": "camera", "state": "kept", "path": "<path>"}` after a keep.
- `{"type": "camera", "error": "<reason>"}` when it cannot open, loses the
  camera, or has no frame to keep. The live view stops.

The prompt waits for the reply to `on` and `keep` with the spinner, at most
`CAMERA_SECONDS = 15`. Replies arrive on the host's reader thread and go
through a queue; an error that arrives later only marks the camera off.

### Prompt window

- `/cam`: opens the window if needed, then the camera ("Camera on: /cam again
  keeps this frame, /cam off stops it"). While live, `/cam` keeps the frame:
  the prompt crops it to the window's shape (`ImageOps.fit` to the paint size),
  saves it over the kept file, records a scene with the request "a frame from
  the camera" and an empty prompt, commits it and shows it.
- `/cam off`: stops without keeping.
- While live, `/add <text>` and `/save` keep the frame first; a request,
  `/again`, `/undo` and `/clear` stop the camera first. Every other command
  leaves it running; `/style` and `/charset` change the live view too.
- The status line shows `· camera` while live.
- A failure says why, with where to allow camera access: Settings › Privacy &
  security › Camera on Windows, System Settings › Privacy & Security › Camera
  for the terminal on macOS.

### Viewer

- `camera.py`: `Camera` opens device 0 (`CAP_DSHOW` on Windows,
  `CAP_AVFOUNDATION` on macOS, asks for 1280x720) and reads it on a thread;
  `latest()` is the newest frame as RGB, mirrored like a selfie
  (`frame[:, ::-1, ::-1]`). `failed` turns true when a read fails.
  `camera_installed()` checks for `cv2`.
- The live view draws at most `LIVE_FPS = 15` frames a second: the frame is
  cover-cropped with a bilinear resize to 4x8 pixels a cell (`fit_image` gets a
  `resample` argument), enhanced, turned into symbol art in the current style
  and charset, and written by the new `ascii_art.to_ansi` (each row placed with
  a cursor move; rich's `Text` takes about 120 ms a frame, raw ANSI about 3 ms).
- No ripples while live. When the live view stops, the picture is drawn again.
- `bye` and the viewer's exit release the camera.

## Testing

`cv2` is replaced by a fake capture; no test opens a camera.

- `test_scene.py`: copy independence, history order and limit.
- `test_repl.py`: undo after paint, add, clear and the first picture; undo
  with nothing; again with a new seed, over the base, without Claude, refusing
  shown pictures; a failed request keeps the old scene; cam not installed, on,
  failure, keep, off, keep before `/add` and `/save`, stop before a request.
- `test_camera.py`: mirrored RGB, failure flag, stop releases.
- `test_viewer.py`: camera messages, the live view's frame rate, keep writes the
  PNG and replies, error replies.
- `test_ascii_art.py`: `to_ansi` draws every row from its first column with the
  colors of `to_text`.
