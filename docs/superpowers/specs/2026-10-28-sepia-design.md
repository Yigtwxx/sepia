# Sepia design

Date: 2026-10-28
Status: approved

## Goal

`sepia` opens a chat-style prompt in the terminal. The user describes a picture ("waterfall"). Claude draws it, and a
second terminal window opens to show the picture as colored symbols (`.'^+%&/()…`). Follow-up prompts edit the same
scene ("mountains" gives a waterfall with mountains). Sepia only makes pictures.

Constraints:

- Runs on, and can be developed on, both macOS (Apple Silicon) and Windows.
- The only paid service is the Claude API. Claude cannot output raster images, so it draws vector graphics (SVG).
- The prompt window shows only the user's text and short replies ("working on it…").
- The viewer window shows only the picture: no shell command line, no title or tab bar, no app header.

## Name

Sepia is the cuttlefish genus. Cuttlefish release ink and paint colored patterns across their skin, which is what this
tool does to a terminal. The PyPI name `sepia` is taken by an abandoned 2018 project, so the package is published as
`sepia-cli` and installs a `sepia` command.

## Architecture

Two processes, one per terminal window, joined by an authenticated local socket.

```
terminal 1: sepia (prompt)                         terminal 2: sepia --viewer (spawned)
  prompt_toolkit input -> Scene                      alternate screen, hidden cursor
  spinner while Claude works                         receives SVG
  Artist -> Claude API -> SVG + short message        SVG -> resvg -> RGB -> symbol grid -> rich
  prints the short message   -- {"svg": ...} -->     re-renders locally when resized (no API call)
                             <-- {"cols","rows"} --  reports its size so Claude can match the aspect ratio
```

### Units

| Module | Responsibility | Depends on |
|---|---|---|
| `cli` | Argument parsing; starts the prompt or the viewer | `repl`, `viewer` |
| `config` | Settings and API key lookup | `platformdirs`, `python-dotenv` |
| `scene` | Prompt history, current SVG, viewer size | none |
| `artist` | One Claude call: scene in, `SceneReply(message, svg)` out | `anthropic`, `pydantic` |
| `raster` | SVG string to an RGB array | `resvg-py`, `pillow`, `numpy` |
| `ascii_art` | RGB array to a grid of colored symbols | `numpy` |
| `ipc` | Authenticated JSON messages over `127.0.0.1` | `multiprocessing.connection` |
| `launcher` | Opens the viewer in a new window on each OS | `subprocess` |
| `viewer` | Full-screen picture display, redraw on resize | `ipc`, `raster`, `ascii_art`, `rich` |
| `repl` | The prompt loop, commands, status output | `scene`, `artist`, `ipc`, `launcher` |

## Drawing pipeline

1. **Claude writes SVG.** Each request is built fresh from a fixed system prompt plus one user message containing the
   earlier requests, the current SVG, the new request, and the target aspect ratio. Assistant turns are never replayed,
   so cost stays bounded and replayed thinking blocks can't break anything. Structured output returns
   `{"message": str, "svg": str}`. Model: `claude-opus-5-5` (override with `SEPIA_MODEL`), with server-side refusal fallback.
2. **The system prompt directs the art toward what reads well as symbols:** a full-bleed background, bold layered shapes,
   strong value contrast, gradients for sky, water and light, no text, no hairline strokes. On a follow-up it edits the
   existing SVG instead of starting over.
3. **resvg renders** the SVG at about 8×16 px per terminal cell. That is a supersample: each cell averages many pixels.
4. **Cell to symbol.** The mean color of each cell, averaged in linear light, gives a luminance. The luminance picks a
   symbol from a density-ordered ramp. A Sobel pass finds strong edges and draws them with `/ \ | - _` according to the
   edge direction. The foreground color is the cell color with a slight lift so dark cells stay visible. An optional
   `fill` style also paints the cell background.
5. **rich prints** the grid. It falls back to 256 colors on terminals without truecolor.

## Windows and terminals

- Windows: `wt.exe -w new --focus` opens a new Windows Terminal window in focus mode, which hides the tab and title bar.
  If Windows Terminal is missing, Sepia falls back to a new console window.
- macOS: `osascript` asks Terminal.app to run the viewer in a new window. Terminal.app cannot hide its title bar.
- The viewer switches to the alternate screen and clears it, so the launching command line is never visible.
- One viewer window per session. Later prompts update it in place. If the user closes it, the next prompt reopens it.

## Prompt UX

- `› ` prompt with history. A spinner shows a short "working on it" line, followed by Claude's one-sentence reply.
- Commands: `/new` starts a fresh scene, `/help` lists commands, `/exit` (or Ctrl+D) closes both windows.

## Configuration and secrets

- `ANTHROPIC_API_KEY` is read from the environment, then a `.env` in the working directory (development), then a `.env`
  in the user config directory. If no key is found, Sepia asks once with hidden input and stores it in the user config
  directory. The key is never logged.
- `SEPIA_MODEL`, `SEPIA_EFFORT`, `SEPIA_STYLE` adjust the model, the effort level and the rendering style.

## Errors

- API errors are mapped to short messages in the prompt window: missing key, rate limit, connection lost, refusal,
  truncated output. The scene stays unchanged, so the user can just retry.
- Invalid SVG from Claude (render fails) counts as a failed turn. The previous picture stays on screen.
- If the viewer window is gone, the prompt reopens it on the next send.

## Testing

- Unit tests for `ascii_art` (ramp order, edge glyphs, grid size and aspect), `scene`, `ipc` (round trip), `launcher`
  (command built per OS with `subprocess` mocked) and `artist` (mocked client: request shape, refusal and truncation
  handling, schema validation).
- A quality spike script renders real prompts in both styles for a human to judge before the interactive parts are built.
- CI runs ruff, mypy and pytest on `windows-latest` and `macos-latest`.

## Cost

About $0.10 per picture on Claude Opus 5.5 (≈ 4k output tokens including thinking, ≈ 4k input), so a $100 credit
covers roughly 1,000 pictures.
