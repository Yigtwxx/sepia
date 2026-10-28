# sepia design

Date: 2026-10-28
Revised: 2026-10-29 (photographs instead of SVG, see below)
Status: approved

## Goal

`sepia` opens a chat-style prompt in the terminal. The user describes a picture ("waterfall"). A second terminal window
opens and shows the picture as colored text characters. Follow-up requests change the same scene ("mountains" gives the
waterfall with mountains behind it). sepia only makes pictures.

Constraints:

- Runs on, and can be developed on, both macOS (Apple Silicon) and Windows.
- Cheap enough to use casually: the only paid service is the Claude API, and it is used for text only.
- The prompt window shows only the user's text and short replies.
- The viewer window shows only the picture: no shell command line, no app header, and on Windows no title or tab bar.

## Revision 2026-10-29: photographs instead of SVG

The first version had Claude draw each scene as SVG, which was rasterized with resvg and converted to symbols. Spikes
showed that SVG could not reach photographic quality: even detailed, layered illustrations read as flat clip art once
reduced to characters. The goal is photo-quality symbol art at the level of the ASCII-photo edits seen in Instagram
reels, and that needs real photographs as input.

Image generation APIs cost money per picture, so the pipeline was rebuilt around free painters:

- **Claude becomes the art director, not the artist.** Claude Haiku (low effort) writes a detailed photo prompt from the
  request and the scene history. That costs about $0.0003 per request instead of about $0.10 per SVG picture on Opus.
- **Pollinations paints first.** Its web API is free, keyless at a low rate or with a free key.
- **FLUX.2 [klein] 4B paints locally when the API fails or rate limits.** It is Apache 2.0, distilled to four steps, and
  edits from a reference image. It is an optional extra so the base install stays small.

The modules `artist` (SVG from Claude) and the resvg rasterizer were removed. `director`, `painter` and the new `raster`
replace them.

## Name

sepia is the cuttlefish genus. Cuttlefish release ink and paint colored patterns across their skin, which is what this
tool does to a terminal. The PyPI name `sepia` is taken by an abandoned 2018 project, so the package is published as
`sepia-cli` and installs a `sepia` command.

## Architecture

Two processes, one per terminal window, joined by an authenticated loopback socket.

```
terminal 1: sepia (prompt)                              terminal 2: sepia --viewer <session file> (spawned)
  prompt_toolkit input, rich output                       alternate screen, hidden cursor, echo off
  Director -> Claude -> {message, prompt, edit}
  Painter  -> Pollinations | local FLUX.2 -> PNG
  saves the PNG in the session folder   -- {"type":"image","path",...} -->  PNG -> enhance -> crop -> symbols -> rich
  prints Claude's one-line reply        -- {"type":"style"|"clear"|"bye"} -->
  paints at the viewer's aspect ratio   <-- {"type":"size","cols","rows"} --  re-renders on resize, no API call
```

### Units

| Module | Responsibility | Depends on |
|---|---|---|
| `cli` | Argument parsing; starts the prompt, the viewer, or the model download | `repl`, `viewer`, `painter` |
| `config` | Settings and API key lookup, key storage, config folder | `platformdirs`, `python-dotenv` |
| `scene` | Requests, prompts, latest picture and fixed seed; viewer size (`Canvas`) | `pillow` |
| `director` | One Claude call: request + scene in, `Direction(message, prompt, edit)` out | `anthropic`, `pydantic` |
| `painter` | Pollinations and local FLUX.2 painters, fallback chain, device choice | `urllib`, optional `torch`, `diffusers` |
| `raster` | Contrast and color boost; cover-crop to the grid | `pillow`, `numpy` |
| `ascii_art` | RGB array to a grid of colored symbols | `numpy`, `rich` |
| `ipc` | Authenticated JSON messages over `127.0.0.1` | `multiprocessing.connection` |
| `launcher` | Opens the viewer in a new window on each OS | `subprocess` |
| `viewer` | Full-screen picture display, redraw on resize | `ipc`, `raster`, `ascii_art`, `rich` |
| `ui` | Wordmark, palette, replies, interface strings (English) | `rich` |
| `repl` | The prompt loop, commands, spinner, session folders | `director`, `painter`, `ipc`, `launcher`, `ui` |

## Request pipeline

1. **Direct.** Each request is built fresh from a fixed system prompt (`prompts/director.md`) plus one user message
   (`prompts/request.md`) holding the earlier requests of the scene, the last prompt, and the new request. Assistant
   turns are never replayed, so cost stays flat as a scene grows. Structured output returns
   `{"message", "prompt", "edit"}`: a one-sentence reply in the user's language, a 40 to 80 word English photo prompt
   (one clear subject, strong directional light, saturated color, no text), and whether to edit the current picture.
   `edit` is forced to false on an empty scene. Model `claude-haiku-5-5` at effort `low` (`SEPIA_MODEL`,
   `SEPIA_EFFORT`); models that support it get Anthropic's server-side fallback.
2. **Paint.** The picture size follows the viewer's aspect ratio, about 1024x640 pixels in area, in multiples of 16.
   The chain is: Pollinations with the user's key (`gen.pollinations.ai`, `flux.2-klein-4b`), then keyless Pollinations
   (`image.pollinations.ai`, `private=true`, about one picture per 15 s, small logo), then the local model. A 429 or 402
   answer skips that endpoint for 120 s. Every request in a scene uses the scene's fixed seed.
3. **Local model.** FLUX.2 [klein] 4B through diffusers, 4 steps, guidance 1.0, at most 768x512 (640x416 for edits).
   Device order CUDA, then MPS, then CPU. On CUDA the transformer and text encoder load in 4-bit nf4 (bitsandbytes),
   about 5 GB of VRAM and about 3 s per 768x512 picture on an RTX 4070 laptop GPU; MPS uses bf16, CPU float32. The model is
   downloaded once with `sepia --download` (about 16 GB) and loads on first use.
4. **Edit.** The local model receives the previous picture as a reference image. The API cannot see it, so it repaints
   from the full prompt with the same seed, which keeps the composition close.
5. **Show.** The prompt saves the PNG in the session folder and sends its path to the viewer.

## Rendering

1. Autocontrast (1% cutoff) and a 1.25 saturation boost.
2. Cover-crop with Lanczos to `cols x 8` by `rows x 16` pixels, so each cell averages an 8x16 block and any window shape
   is filled without bars or distortion.
3. Per cell, the mean color in linear light gives a luminance. A partial contrast stretch (2nd to 98th percentile) and
   a 0.5 gamma lift dark surfaces so they read as texture.
4. A 4x4 Bayer dither, strongest in the midtones and faded out toward black and white, breaks gradients into mixed
   symbols instead of bands.
5. The nearest density in a measured ramp picks the character: `classic` has 31 levels from the ASCII-art alphabet,
   `symbols` 15 levels of punctuation.
6. Color is weighted toward each cell's brightest pixels, so a small light keeps its color. `ink` boosts saturation and
   sets a brightness floor, then colors the symbol on the terminal background. `fill` lightens the symbol and paints
   the cell background with a darker version of the cell color.
7. Optional outlines from a thinned Sobel edge map, drawn with `| / - _ \` along the edge. Off in the viewer.
8. rich prints the grid in truecolor, or 256 colors where the terminal lacks truecolor.

## Windows and terminals

- Windows: `wt.exe --window new --focus` opens a new Windows Terminal window in focus mode, which hides the tab and title
  bar. It uses a `sepia` profile (6 pt Cascadia Mono, black, no padding, hidden scrollbar) that sepia writes as a
  fragment to `%LOCALAPPDATA%\Microsoft\Windows Terminal\Fragments\sepia\sepia.json`, so the user's `settings.json` is
  never touched. The small font gives the picture several times more cells. If Windows Terminal is missing, sepia
  falls back to a new console window.
- macOS: `osascript` asks Terminal.app to run the viewer in a new window (`exec`, so the window closes with the viewer).
  The first run triggers the Automation permission prompt. Terminal.app cannot hide its title bar; the user can zoom out
  with ⌘- for more cells.
- Linux: no viewer window; not supported.
- The viewer switches to the alternate screen, hides the cursor and turns off echo, so neither the launching command nor
  stray keystrokes are visible. It reports its size on start and on every resize and redraws once the size settles.
- One viewer window per session. If the user closes it, the next request reopens it.

## Prompt UX

- A panel with the wordmark in the figlet font ANSI Shadow, like spiyweb's (letters banded pink to purple, shadow in deep purple), a tip line, then
  a `›` prompt with file history, slash-command completion and a bottom bar (model, style/charset, window status).
- While working, a `✻✽✶✳✢·` spinner with "Working on it…"; then a `⏺` reply with the source and time.
- Commands: `/add <text>` (build on the current picture; plain requests start a new one), `/clear`, `/style [ink|fill]`, `/charset [classic|symbols]`, `/help`, `/exit` (also `/quit`, `/q`, Ctrl+D).
- The interface and Claude's replies are English only.

## Configuration and secrets

- `ANTHROPIC_API_KEY` is read from the environment, then a `.env` in the working directory, then a `.env` in the user
  config folder. If none is found, sepia asks once with hidden input and stores it in the user config `.env` with
  user-only permissions. Keys are never printed or logged.
- Optional: `POLLINATIONS_KEY`, `SEPIA_MODEL`, `SEPIA_EFFORT`, `SEPIA_STYLE` (default `ink`), `SEPIA_CHARSET` (default
  `classic`), `SEPIA_IMAGE_MODEL`.
- Pictures are saved per session under the user config folder; the newest 10 sessions are kept.
- The IPC session file (port and one-time 32-byte key) is written with user-only permissions. Messages are JSON and are
  never unpickled.

## Errors

- Claude errors map to short messages in the user's language: rejected key, rate limit, server error, connection lost,
  bad request, refusal, truncated or malformed output. The scene is unchanged, so the user can retry.
- A painter failure falls through to the next painter. If all fail, the message names the last error, and the previous
  picture stays on screen.
- If the viewer window is gone, the prompt reopens it and waits up to 15 s for it to connect.

## Testing

- Unit tests per module: `ascii_art` (ramp order, outlines, grid shape, styles), `raster`, `scene`, `director` (mocked
  client: request shape, failures, schema validation), `painter` (request URLs, fallback and cooldown, device order),
  `ipc` (round trip, wrong key), `launcher` (commands per OS, profile fragment), `viewer`, `repl`, `ui`, `config`.
- `scripts/spike.py` runs real requests through the director and painter and saves previews of both styles for a human
  to judge.
- CI runs ruff, mypy and pytest on `windows-latest` and `macos-latest`, without the local extra.

## Cost

About $0.0003 per request on Claude Haiku at low effort. Pollinations and the local model are free.
