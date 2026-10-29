# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Pre-release versions are written the PEP 440 way (`0.2.0a1`, not
`0.2.0-alpha.1`), because that is the string the wheel, PyPI and the release
tag all carry.

## [Unreleased]

### Changed

- The art director paints what a request usually looks like, the picture a
  web search shows first for it, instead of reinterpreting it ("multiverse" is
  bubble universes again, not a hallway of doors). Ask for something creative
  or surprising and it still finds its own twist.

## [0.3.1] - 2026-10-29

### Added

- `/model [haiku|sonnet|opus|fable]` switches the art director between Claude
  Haiku 5.5, Sonnet 5.5, Opus 5.5 and Fable 5.1, from the next request on;
  without a name it opens a menu. The bottom bar and `/usage` show the model
  in use. `SEPIA_MODEL` still sets the one sepia starts with.
- Pictures are painted by Cloudflare Workers AI with FLUX.2 [klein] 4B, the
  same model the local fallback runs. A free Cloudflare account paints about
  100 pictures a day (10,000 neurons, reset at 00:00 UTC). Set
  `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`; without them sepia
  paints only on the local GPU. `/add` sends the previous picture, so the API
  edits it instead of repainting from the prompt.
- `/api` paints with Cloudflare and falls back to the local model when it
  fails; it also tries Cloudflare again after a rate limit or a used-up day.
  `/local` paints only on this machine. The bottom bar shows which is in use.
  A picture Cloudflare's safety filter flags is painted locally, and the
  reply says the filter flagged it.
- What you pick with `/model`, `/effort`, `/style`, `/charset`, `/mature`,
  `/api` or `/local` is kept in `choices.json` in the config folder, so the
  next sepia starts with it instead of asking again. A kept choice wins over
  its `SEPIA_*` variable.

### Changed

- Typing `/` opens a menu of the matching commands above the chat bar, with
  their descriptions: ↑↓ move, Tab completes, Enter runs the highlighted one.
  It replaces the grey completion inside the input line.
- `/usage` opens as a panel, as in Claude Code: Esc, Enter or q closes it, and
  it leaves nothing in the transcript. It shows Claude's tokens, searches and
  cost only; the pictures bar with its painters is gone.
- Claude may write up to 32,000 tokens a request (was 8,000), so Opus and
  Fable thinking at high effort or above are not cut off. Only what is
  written is billed.

### Removed

- Pollinations, keyed and keyless, and `POLLINATIONS_KEY`. Its free endpoint
  was slow, added a logo and ignored reference pictures; the keyed one cost
  pollen.

### Fixed

- A share.google link copied from Google Images now gives its picture: the
  Google page it opens has no preview picture, so the picture's own address is
  taken from the page's link. The message for an unusable link says that 256 px
  is the smallest size taken, not the largest.

## [0.3.0] - 2026-10-29

### Added

- A landing page at https://sepia-cli.vercel.app, built from `site/` (Astro).
  Its pictures are drawn by sepia's own code: public-domain cuttlefish plates
  and a real run of the prompt window, converted by `scripts/site_art.py`.

### Changed

- The spinner counts the seconds since the request began ("painting · 12s",
  then "2m 05s"). It no longer names Pollinations, which it did even while
  the local GPU was painting; the reply under the picture still says which
  painter drew it.
- The package's homepage link points at the landing page.

## [0.2.1] - 2026-10-29

### Added

- `/effort [low|medium|high|xhigh|max]` sets how long Claude thinks about each
  picture, from the next request on; without a name it opens a menu. The
  bottom bar shows the current effort next to the model.
- `/mature [on|off]` (and `SEPIA_MATURE`, off by default) lets Claude paint
  sexy, hot, dark and violent scenes of adults as asked instead of toning
  them down: glamour, boudoir, lingerie, artistic or implied nudity. Explicit
  sex, anyone who looks under 18 and real people undressed stay off limits;
  such a request gets the nearest acceptable picture instead of a refusal.
- Paste a picture link into a request ("yunara https://…") to paint from
  that picture: sepia downloads it first, Claude sees it and writes the
  subject's look into the prompt without a web search, and the image model
  copies it. A link without a usable picture is reported.
- A bare name ("yunara lol") shows the subject's picture as it is, whole and
  on black, instead of a painting of a stranger. With a scene ("yunara on a
  beach") Claude now sees the picture before writing the prompt, so the
  description matches the real look.
- With `BRAVE_SEARCH_API_KEY`, a named subject's picture comes from the top
  results of an image search, as a search engine shows them; without it,
  from the wiki pages Claude links. `/usage` counts the image searches.
- `/usage` shows all-time totals under the session's, kept in `usage.json` in
  the config folder and shared by every sepia window. Use from before tracking
  began is estimated once from the prompt history and the saved sessions.

### Changed

- Moving the mouse over the picture sends ripples out from the pointer
  instead of glitching it: rings that bend the picture a cell or two, light
  up at their crest with a darker trough either side, and fade as they
  spread. Moving the pointer leaves a trail of them.
- The art director looks for an idea before writing the prompt: a striking,
  concrete scene instead of the first cliché ("multiverse" no longer means a
  row of glowing spheres). Prompts are 60 to 100 words.
- Claude's default effort is `high` (was `low`). On Haiku 5.5 it costs about
  the same, about $0.001 a request.
- `/usage` session bars are drawn against the all-time totals on a gray track,
  so the empty part of a bar reads as empty.
- A downloaded local model starts loading in the background when sepia
  opens, so the first local picture no longer waits about 12 seconds for it.
  It holds about 5 GB of VRAM from then on.

### Fixed

- A subject whose only links were fandom wikis, which refuse sepia's
  downloads, was painted without its picture and without a word. Claude now
  prefers the official wiki, and sepia says when it finds no usable picture.
- A wiki page whose preview picture is an SVG logo no longer becomes the
  reference.
- `/usage` bars no longer leave a stray empty cell when the parts round down.
- Web searches are priced even when the model has no known price.
- Loading the local model no longer fills the prompt window with progress
  bars, library warnings and a deprecation note.
- Once Pollinations answers that the key is out of pollen (HTTP 402), sepia
  stops asking it until it restarts, instead of every two minutes.

## [0.2.0] - 2026-10-29

### Added

- `/add <text>` adds to the current picture; a plain request now always
  starts a new one.
- `/clear` clears the screen and starts a fresh picture.
- `/usage` shows what the session used, laid out like Claude Code's: Claude's
  tokens, web searches and estimated cost, and the pictures painted per
  source, each with a bar of what the total is made of.
- `/style` and `/charset` without a name open a menu of their options: move
  with the arrow keys, pick with Enter or the option's number, Esc to cancel.
- Enter on a partial command runs the command it suggests: `/us` opens
  `/usage`.
- Moving the mouse over the picture glitches it around the pointer: torn rows,
  corrupted glyphs and split colors that fade out when the pointer stops.
- Named characters, creatures, products and landmarks are painted from a
  reference picture: Claude links the subject's wiki page, sepia takes the
  page's preview picture and the image model copies the look from it, so
  "yunara lol" paints Yunara instead of a stranger. /add keeps the reference.
  It works with a Pollinations key and with the local model; the keyless API
  ignores reference pictures.

### Changed

- The chat bar is one block (rule, input, rule, status) that starts under the
  welcome box and moves down with the conversation, as in Claude Code; once it
  reaches the bottom the welcome box scrolls away. The rules have open ends,
  with no corners or side borders, and the bar stays on screen while a request
  is being worked on.
- The picture window has its tab row again, so it can be moved; the tab reads
  "sepia" on the theme's pinkish purple.
- Starting sepia clears the screen and the scrollback.
- The wordmark uses the ANSI Shadow font, like spiyweb's.
- With the local model downloaded, a keyed request that runs out of
  credit falls back to the local model before the keyless API.
- The interface and Claude's replies are English only.

### Removed

- `/new`: a plain request starts a new picture now.
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

[Unreleased]: https://github.com/Yigtwxx/sepia/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/Yigtwxx/sepia/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Yigtwxx/sepia/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Yigtwxx/sepia/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Yigtwxx/sepia/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Yigtwxx/sepia/releases/tag/v0.1.0
