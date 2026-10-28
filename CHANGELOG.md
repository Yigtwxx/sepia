# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Pre-release versions are written the PEP 440 way (`0.2.0a1`, not
`0.2.0-alpha.1`), because that is the string the wheel, PyPI and the release
tag all carry.

## [Unreleased]

### Added

- `/clear` clears the screen and starts a fresh picture.

### Changed

- The chat bar is one framed block (border, input, border, status) that
  starts under the welcome box and moves down with the conversation, as in
  Claude Code; once it reaches the bottom the welcome box scrolls away.
- Starting sepia clears the screen and the scrollback.
- The wordmark uses the ANSI Shadow font, like spiyweb's.
- With the local model downloaded, a keyed request that runs out of
  credit falls back to the local model before the keyless API.
- The interface and Claude's replies are English only.

### Removed

- `SEPIA_LANG` and the Turkish interface strings.

## [0.1.0] - 2026-10-29

The first release. Type a short request, and a second terminal window shows it
as a photograph made of colored text characters.

### Added

- The prompt window (`sepia`): an ANSI Shadow wordmark banded pink to purple, a `›`
  prompt with history and slash-command completion, a spinner while work is
  in progress, and a one-line `⏺` reply with the picture's source and time.
  Commands: `/new`, `/style [ink|fill]`, `/charset [classic|symbols]`,
  `/help` and `/exit` (also Ctrl+D). The interface speaks English and
  Turkish, chosen by `SEPIA_LANG` or the system language.
- Scenes: follow-up requests build on the current picture ("waterfall",
  then "mountains"), with one fixed seed per scene so a repainted picture
  keeps its composition. `/new` starts a fresh scene.
- The art director: Claude (`claude-haiku-5-5` at low effort by default)
  turns the request and the scene history into a detailed English photo
  prompt tuned for symbol rendering, decides whether to edit the current
  picture or start a new one, and writes a one-sentence reply in the user's
  language. The reply comes back through structured output. About $0.0003
  per request.
- Painting through Pollinations: the keyed endpoint with `flux.2-klein-4b`
  when `POLLINATIONS_KEY` is set (a free key from enter.pollinations.ai, no
  logo), otherwise the free keyless endpoint, sent with `private=true`.
- Local painting with FLUX.2 [klein] 4B (Apache 2.0) when the API fails or
  rate limits, with a 120 second cooldown after a 429 or 402 answer. It is
  an optional extra (`sepia-cli[local]`); `sepia --download` fetches the
  model (about 16 GB). It runs on CUDA (4-bit nf4, about 5 GB of VRAM), then
  Apple Silicon MPS (bf16), then CPU, and edits from the previous picture.
- The viewer window: a second terminal window that shows only the picture
  and redraws it on resize without new API calls. On Windows it is a Windows
  Terminal window in focus mode with a small-font `sepia` profile installed
  as a fragment, falling back to a console window; on macOS a Terminal.app
  window opened through `osascript`.
- An authenticated loopback channel between the two windows: an HMAC
  handshake with a one-time key from a user-only session file, and JSON
  messages that are never unpickled.
- Rendering: contrast stretch and saturation boost, a cover-crop to the
  window, per-cell averages in linear light, a measured character ramp
  (`classic` with 31 levels of the ASCII-art alphabet, or `symbols` with
  punctuation), a midtone Bayer dither, and truecolor per character with
  colors weighted toward each cell's brightest pixels. Two styles: `ink`
  colors the characters on the terminal background, `fill` also paints the
  cell backgrounds. Optional Sobel outlines in the library.
- Configuration through the environment or `.env` files:
  `ANTHROPIC_API_KEY` (asked for on the first run and saved with user-only
  permissions), `POLLINATIONS_KEY`, `SEPIA_MODEL`, `SEPIA_EFFORT`,
  `SEPIA_STYLE`, `SEPIA_CHARSET`, `SEPIA_IMAGE_MODEL` and `SEPIA_LANG`.
- Pictures are saved per session in the user config folder; the newest 10
  sessions are kept.

[Unreleased]: https://github.com/Yigtwxx/sepia/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Yigtwxx/sepia/releases/tag/v0.1.0
