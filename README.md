<div align="center">

# sepia

**Describe a picture and watch it appear as colored text in a second terminal window.**

[![PyPI](https://img.shields.io/pypi/v/sepia-cli?color=9b59d0)](https://pypi.org/project/sepia-cli/)
[![Python](https://img.shields.io/pypi/pyversions/sepia-cli)](https://pypi.org/project/sepia-cli/)
[![CI](https://github.com/Yigtwxx/sepia/actions/workflows/ci.yml/badge.svg)](https://github.com/Yigtwxx/sepia/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/Yigtwxx/sepia/blob/main/LICENSE)

<img src="https://raw.githubusercontent.com/Yigtwxx/sepia/main/docs/assets/waterfall.png" alt="A waterfall falling into a green pool in a mossy gorge, drawn in colored text characters" width="820">

<sub><code>› waterfall</code>, drawn by the viewer as 9,520 characters, each chosen and colored to match the patch of the picture under it.</sub>

[Website](https://sepia-cli.vercel.app) · [Quick start](#quick-start) · [Usage](#usage) · [Configuration](#configuration) · [How it works](#how-it-works) · [Privacy](#privacy)

</div>

## Overview

sepia is a command-line tool that turns short requests into pictures made of text. You type what you want to see in one terminal window; Claude writes a photo prompt for it, an image model paints it, and a second window draws the result as colored characters.

```text
› waterfall
 ⏺ Painting a tall waterfall in a mossy gorge.
   cloudflare · 6.2s
› /add mountains
 ⏺ Adding snowy mountains behind the waterfall.
   cloudflare · 5.8s
```

Every request starts a new picture; `/add` builds on the current one. sepia only makes pictures; it is not a chat assistant.

## Features

- **An art director, not a prompt box.** Claude looks for a striking scene instead of the first cliché, writes a detailed English photo prompt tuned for text rendering, and decides whether a request edits the current picture or starts a new one.
- **Free to paint, local when you need it.** [FLUX.2 [klein] 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) paints every picture: on [Cloudflare Workers AI](https://developers.cloudflare.com/workers-ai/) with a free account (about 100 pictures a day), or, with the optional `local` extra, on your own GPU (CUDA or Apple Silicon) whenever the API fails or rate limits. `/local` keeps it on your GPU.
- **Real subjects stay recognizable.** Name a character, creature, product or landmark, or paste a link to a picture, and sepia paints from a reference picture instead of inventing a stranger.
- **Made for the terminal.** 24-bit color, two styles and two character sets, a redraw on every resize without new API calls, and ripples that spread from the mouse pointer over the picture.
- **Costs you can see.** `/usage` shows Claude's tokens, searches and estimated cost, for the session and for all time.
- **Nothing hidden.** The two windows talk over an authenticated loopback socket, and sepia has no telemetry.

## Quick start

You need Windows 10/11 or macOS, [uv](https://docs.astral.sh/uv/), an [Anthropic API key](https://console.anthropic.com/), and somewhere to paint: a free [Cloudflare account](#cloudflare-workers-ai) or the [local model](#install) on your GPU. uv provides Python 3.12 if you do not have it.

```bash
uv tool install sepia-cli
sepia
```

On the first run sepia asks for your Anthropic API key (hidden input) and saves it to the user config folder. Put `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` in the environment or in the `.env` file in that folder (see [Cloudflare Workers AI](#cloudflare-workers-ai)). Type `waterfall` and press Enter: the viewer window opens with the picture. Keep it next to the prompt window, then try `/add mountains`.

## Install

**Cloudflare painting only.** A small install that needs no GPU:

```bash
uv tool install sepia-cli
```

**With the local fallback model.** About 3 GB of packages plus a 16 GB model download:

```bash
# macOS (Apple Silicon)
uv tool install "sepia-cli[local]"

# Windows: CUDA builds of torch are not on PyPI, so point uv at the PyTorch index
uv tool install "sepia-cli[local]" --index https://download.pytorch.org/whl/cu130 --index-strategy unsafe-best-match
```

Then download the model once:

```bash
sepia --download
```

## Usage

Start sepia with `sepia`. The first request opens the viewer window; if you close it, the next request opens it again.

### Commands

| Command | What it does |
| --- | --- |
| `/add <text>` | Add to the current picture instead of starting a new one. |
| `/clear` | Clear the screen and start a fresh picture. |
| `/style [ink\|fill]` | `ink` colors the characters on the terminal's own background and suits dark themes; `fill` also paints each cell's background and works on any theme. |
| `/charset [classic\|symbols]` | `classic` uses 31 density levels of the ASCII-art alphabet (letters, digits, punctuation); `symbols` uses punctuation only. |
| `/model [haiku\|sonnet\|opus\|fable]` | Which Claude writes the prompts, from the next request on: Haiku 5.5 (the default), Sonnet 5.5, Opus 5.5 or Fable 5.1. |
| `/effort [low\|medium\|high\|xhigh\|max]` | How long Claude thinks about each picture, from the next request on. |
| `/mature [on\|off]` | Mature pictures; see [Mature mode](#mature-mode). Off by default. |
| `/api` | Paint with Cloudflare Workers AI, and with the local model when it fails. Also makes sepia try Cloudflare again after a rate-limit pause or a used-up day; see [Painting backends](#painting-backends). |
| `/local` | Paint only on this machine's GPU. Refused, with a hint, while the local model is not ready. |
| `/usage` | What Claude used in this session and in all sessions: tokens, web searches and estimated cost. Esc closes it. |
| `/help` | List the commands. |
| `/exit` | Close sepia and the viewer window. `/quit`, `/q` and Ctrl+D do the same. |

`/style`, `/charset`, `/model`, `/effort` and `/mature` without an argument open a menu: the arrow keys and Enter (or the option's number) pick, Esc cancels. `/usage` opens a panel that Esc (or Enter) closes without leaving it in the transcript. Its session bar is drawn against the all-time total, so its gray rest is earlier use; use from before tracking began is estimated once from the prompt history and the saved sessions.

### Keys and the viewer

- Up and down arrows walk the request history. Typing `/` opens a menu of the matching commands, with their descriptions, above the chat bar: the up and down arrows move through it, Tab completes the highlighted command, and Enter runs it.
- The status line under the chat bar shows the painter, the model and its effort (and `mature` when it is on), the current style and charset, and whether the viewer window is connected (`●`) or not (`○`).
- Moving the mouse over the viewer window sends ripples out from the pointer: rings that bend the picture, light up at their crest and fade. Windows Terminal and iTerm2 report pointer movement; macOS Terminal.app may not.

### Named subjects and reference pictures

The image models know no names, so when a request names a specific character, creature, product or landmark ("yunara lol"), Claude names the subject and sepia finds its picture: the top result of an image search when a Brave Search key is set, otherwise the preview picture of the wiki page Claude links.

- **A bare name** ("yunara lol") shows that picture as it is, whole and on black.
- **A name in a scene** ("yunara on a beach") lets Claude see the picture and describe the subject from it, and the image model paints from it, so the subject keeps its real look.
- **A pasted link** to a picture, or to a page with a preview picture ("yunara https://…"), becomes the reference directly: Claude sees it and no search is made.

Reference pictures work with both painters: Cloudflare receives the picture as an input image, downscaled to at most 512 px a side, and the local model paints from it the same way.

### Mature mode

With `/mature on` (or `SEPIA_MATURE=on`), Claude paints sexy, hot, dark and violent scenes of adults as asked instead of toning them down: glamour, boudoir, lingerie, artistic or implied nudity. It is never explicit (no sex acts, no visible genitals), never shows anyone who is or looks under 18, and never shows a real person undressed; such a request gets the nearest acceptable picture instead of a refusal.

### Command-line flags

| Flag | What it does |
| --- | --- |
| `--download` | Download the local model (about 16 GB) from Hugging Face. Needs `sepia-cli[local]`. |
| `--version` | Print the version. |
| `--help` | Print usage. |

## Configuration

sepia reads settings from the environment, then from `.env` in the current directory, then from `.env` in the user config folder. A value that is already set is never overridden by a later source. See [.env.example](https://github.com/Yigtwxx/sepia/blob/main/.env.example).

| Variable | Default | Meaning |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | none | Required. Asked for on the first run if missing and saved to the user config `.env`. |
| `BRAVE_SEARCH_API_KEY` | none | Optional key from [brave.com/search/api](https://brave.com/search/api) (monthly free credits, about 1,000 searches). Named subjects come from the top pictures of an image search instead of wiki pages. |
| `CLOUDFLARE_ACCOUNT_ID` | none | Your Cloudflare account ID, for painting on [Cloudflare Workers AI](#cloudflare-workers-ai). Goes together with `CLOUDFLARE_API_TOKEN`. |
| `CLOUDFLARE_API_TOKEN` | none | A Workers AI API token. Without the two Cloudflare settings, sepia paints only with the local model. |
| `SEPIA_MODEL` | `claude-haiku-5-5` | The starting art director model. `/model` switches between `claude-haiku-5-5`, `claude-sonnet-5-5` (about 20 times the price), `claude-opus-5-5` (about 40 times) and `claude-fable-5-1` (about 100 times) while sepia runs. |
| `SEPIA_EFFORT` | `high` | Starting Claude effort: `low`, `medium`, `high`, `xhigh` or `max`. `/effort` changes it while sepia runs. |
| `SEPIA_STYLE` | `ink` | Starting style: `ink` or `fill`. |
| `SEPIA_CHARSET` | `classic` | Starting character set: `classic` or `symbols`. |
| `SEPIA_MATURE` | `off` | Start with mature pictures `on` or `off`. `/mature` changes it while sepia runs. |
| `SEPIA_IMAGE_MODEL` | `black-forest-labs/FLUX.2-klein-4B` | Hugging Face id of the local model. |

An invalid value for `SEPIA_EFFORT`, `SEPIA_STYLE`, `SEPIA_CHARSET` or `SEPIA_MATURE` stops sepia at startup. So does setting only one of `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`.

What you pick with `/model`, `/effort`, `/style`, `/charset`, `/mature`, `/api` or `/local` is kept in `choices.json` in the user config folder, and the next sepia starts with it. A kept choice wins over its `SEPIA_*` variable, which only sets what you have never picked; delete the file to start from the variables again. sepia starts with Cloudflare until you pick `/local`.

The user config folder is `%LOCALAPPDATA%\sepia` on Windows and `~/Library/Application Support/sepia` on macOS. It holds the key file, the request history, the all-time usage totals (`usage.json`), the choices kept between sessions (`choices.json`), and one folder per session with that session's pictures (`01.png`, `02.png`, ...). The newest 10 session folders are kept.

### Cloudflare Workers AI

A free Cloudflare account is enough, with no credit card:

1. In the Cloudflare dashboard, open [Workers AI](https://dash.cloudflare.com/?to=/:account/ai/workers-ai) and choose **Use REST API**.
2. Choose **Create a Workers AI API Token**, review the prefilled permissions, choose **Create**, and copy the token into `CLOUDFLARE_API_TOKEN`.
3. Copy the **Account ID** shown on the same page into `CLOUDFLARE_ACCOUNT_ID`.

Your tokens are listed at [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens).

The free tier gives 10,000 neurons a day, reset at 00:00 UTC. At sepia's picture size (about 1024x640) one picture costs roughly 80 to 105 neurons, so the free tier paints about 100 pictures a day. That is an estimate from Cloudflare's per-tile price; see [Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/).

## How it works

```text
prompt window                                                  viewer window
-------------                                                  -------------
"mountains" + earlier requests
        |
        v
Claude (art director) -> English photo prompt, edit or new, one-line reply
        |
        v
Cloudflare Workers AI --- fails or rate limited ----> FLUX.2 [klein] 4B on your GPU
        |                                                      |
        +------------------------> PNG <-----------------------+
                                    |
                                    +--- path over a loopback socket --->  photo -> colored characters
```

1. **Direct.** Claude (`claude-haiku-5-5` at high effort by default) looks for an idea, then turns the request and the scene so far into a detailed English photo prompt written for symbol rendering: one dominant shape, strong light, saturated color, no text. It also decides whether the request edits the current picture or starts a new one, and writes a one-sentence reply. The reply is structured output: JSON with a fixed schema.
2. **Paint.** The prompt goes to Cloudflare Workers AI first, which runs FLUX.2 [klein] 4B (Apache 2.0). If the API fails or rate limits, sepia paints the picture locally with the same model, if you installed the local extra. `/local` paints only locally; `/api` goes back to Cloudflare first. The picture is painted at the viewer window's aspect ratio.
3. **Show.** The picture is saved as a PNG and the viewer window is told where it is. The viewer stretches contrast, boosts saturation, crops the picture to the window, and draws every cell as one character whose density matches the brightness, in 24-bit color where the terminal supports it (256 colors otherwise).

The two windows are two processes that talk over an authenticated loopback socket; see [SECURITY.md](https://github.com/Yigtwxx/sepia/blob/main/SECURITY.md).

## Painting backends

| Backend | When it runs | Notes |
| --- | --- | --- |
| Cloudflare Workers AI (`@cf/black-forest-labs/flux-2-klein-4b`) | First, when `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` are set; never under `/local` | FLUX.2 [klein] 4B. Free up to 10,000 neurons a day, about 100 pictures. Takes the previous picture and reference pictures as input images, at most 512 px a side. |
| FLUX.2 [klein] 4B, local | When Cloudflare fails or rate limits; the only painter without the Cloudflare settings or under `/local` | Needs `sepia-cli[local]` and `sepia --download`. The same model as on Cloudflare. |

After a rate-limit answer (HTTP 429), sepia skips Cloudflare for 120 seconds and paints locally instead of retrying it on every picture. Once the day's free allocation is used up (Cloudflare error 4006), it skips Cloudflare for the rest of the session, since a short wait does not bring it back. `/api` or a restart makes sepia try Cloudflare again after either. A rejected token (HTTP 401 or 403) gets a message that says so. Cloudflare's safety filter sometimes flags a harmless picture, and not every time for the same prompt; that picture is painted locally and the next one goes to Cloudflare again. Whenever the local model paints because Cloudflare failed, the reply's detail line says why.

The local model runs on CUDA, then Apple Silicon (MPS), then CPU, whichever is found first:

- **CUDA:** the transformer and text encoder load in 4-bit (bitsandbytes nf4), about 5 GB of VRAM. On an RTX 4070 laptop GPU a 768x512 picture takes about 3 seconds.
- **MPS:** bf16 weights without quantization, so it needs more memory than the CUDA path.
- **CPU:** float32. It works, but slowly.

Once the model is downloaded, it starts loading in the background as soon as sepia opens, so the first local picture rarely waits for it; it holds about 5 GB of VRAM from then on, until sepia closes. Edits work the same on both backends: `/add` hands the previous picture to the model, which edits it with the scene's fixed seed, so the composition stays close.

## Cost

| Part | Cost |
| --- | --- |
| Claude Haiku as art director | About $0.001 per request with the default model and effort, plus $0.01 per web search |
| Brave image search | About $0.005 per named subject, covered by Brave's monthly free credits |
| Cloudflare Workers AI | Free up to 10,000 neurons a day (about 100 pictures), reset at 00:00 UTC; after that the local model paints |
| Local model | Free, runs on your hardware |

A larger model (`/model`, `SEPIA_MODEL`) or a higher effort costs more per request: about $0.03 on Sonnet 5.5, $0.05 on Opus 5.5 and $0.12 on Fable 5.1.

## Platform support

| Platform | Viewer window | Notes |
| --- | --- | --- |
| Windows 10/11 | Windows Terminal, plain console as a fallback | Full support. |
| macOS | Terminal.app, opened through `osascript` | Full support. |
| Linux | Not available | Not supported: the viewer window cannot be opened there. |

**Windows.** The viewer opens as a new Windows Terminal window with a tab named `sepia` in the theme's pinkish purple; drag the tab row to move the window. It uses a `sepia` profile (6 pt Cascadia Mono, black background, no padding) that sepia writes as a Windows Terminal fragment to `%LOCALAPPDATA%\Microsoft\Windows Terminal\Fragments\sepia\sepia.json`. Your own `settings.json` is not touched; delete that folder to remove the profile. The small font fits several times more cells into the window, which gives the picture more detail. Without Windows Terminal, the viewer falls back to a plain console window.

**macOS.** The first time, macOS asks whether your terminal may control Terminal.app (Automation permission); allow it. Terminal.app cannot hide its title bar. Press ⌘- in the viewer window to shrink the font: the picture redraws with more cells and more detail.

## Privacy

What leaves your machine:

- **To Anthropic:** your request, the earlier requests of the current scene, the last generated prompt, and a reference picture when one is used.
- **To Brave Search:** a short image search query for a named subject, written by Claude, only when `BRAVE_SEARCH_API_KEY` is set.
- **To the site of a reference picture:** a plain download of the linked page or picture, when a request names a subject or contains a link.
- **To Cloudflare:** the generated English prompt, the picture size, the seed and, as input pictures of at most 512 px a side, the reference picture and, for `/add`, the previous picture. Your original request is not sent. Nothing goes to Cloudflare when the picture is painted locally.
- **To Hugging Face:** only the model download when you run `sepia --download`.

Pictures, the request history and the API key file stay in the user config folder on your machine. sepia has no telemetry of its own.

## Development

See [CONTRIBUTING.md](https://github.com/Yigtwxx/sepia/blob/main/CONTRIBUTING.md) for the setup on Windows and macOS, the checks, and the commit and test conventions. The design is described in [docs/superpowers/specs/2026-10-28-sepia-design.md](https://github.com/Yigtwxx/sepia/blob/main/docs/superpowers/specs/2026-10-28-sepia-design.md), releases in [docs/releasing.md](https://github.com/Yigtwxx/sepia/blob/main/docs/releasing.md), and changes in [CHANGELOG.md](https://github.com/Yigtwxx/sepia/blob/main/CHANGELOG.md). To report a vulnerability, see [SECURITY.md](https://github.com/Yigtwxx/sepia/blob/main/SECURITY.md).

## License

[MIT](https://github.com/Yigtwxx/sepia/blob/main/LICENSE). The optional local model, FLUX.2 [klein] 4B, is published by Black Forest Labs under Apache 2.0 and is downloaded separately from Hugging Face.
