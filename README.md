# sepia

Type a short request in your terminal and get a photograph painted in colored text characters in a second terminal window.

<!-- demo gif -->

```text
› waterfall
 ⏺ Painting a tall waterfall in a mossy gorge.
   pollinations · 6.2s
› mountains
 ⏺ Adding snowy mountains behind the waterfall.
   pollinations · 5.8s
```

Follow-up requests build on the same picture: "mountains" after "waterfall" gives the same waterfall with mountains behind it. `/new` starts over. sepia only makes pictures; it is not a chat assistant.

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
Pollinations web API ---- fails or rate limited ----> FLUX.2 [klein] 4B on your GPU
        |                                                      |
        +------------------------> PNG <-----------------------+
                                    |
                                    +--- path over a loopback socket --->  photo -> colored characters
```

1. **Direct.** Claude (`claude-haiku-5-5` at low effort by default) turns the request and the scene so far into a detailed English photo prompt written for symbol rendering: one clear subject, strong light, saturated color, no text. It also decides whether the request edits the current picture or starts a new one, and writes a one-sentence reply in the language you typed in. The reply comes back as structured output (JSON with a fixed schema).
2. **Paint.** The prompt goes to [Pollinations](https://pollinations.ai) first. If the API fails or rate limits, sepia paints the picture locally with [FLUX.2 [klein] 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) (Apache 2.0), if you installed the local extra. The picture is painted at the viewer window's aspect ratio.
3. **Show.** The picture is saved as a PNG, and the viewer window is told where it is. The viewer stretches contrast, boosts saturation, crops the picture to the window, and draws every cell as one character whose density matches the brightness, in 24-bit color where the terminal supports it (256 colors otherwise). Resizing the window redraws the picture without new API calls.

The two windows are two processes that talk over an authenticated loopback socket (see [SECURITY.md](SECURITY.md)).

## Install

You need Windows 10/11 or macOS, [uv](https://docs.astral.sh/uv/), and an [Anthropic API key](https://console.anthropic.com/). uv provides Python 3.12 if you do not have it.

**API painting only** (small install, no GPU needed):

```bash
uv tool install sepia-cli
```

**With the local fallback model** (about 3 GB of packages plus a 16 GB model download):

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

```bash
sepia
```

On the first run sepia asks for your Anthropic API key (hidden input) and saves it to the user config folder. The first request opens the viewer window; keep it next to the prompt window.

| Command | What it does |
| --- | --- |
| `/new` | Start a fresh picture. The next request does not build on the old one. |
| `/clear` | Clear the screen and start a fresh picture. |
| `/style [ink\|fill]` | `ink` colors the characters on the terminal's own background (made for dark backgrounds); `fill` also paints each cell's background, which works on any theme. Without an argument it switches to the other style. |
| `/charset [classic\|symbols]` | `classic` uses 31 density levels of the ASCII-art alphabet (letters, digits, punctuation); `symbols` uses punctuation only. Without an argument it switches to the other set. |
| `/help` | List the commands. |
| `/exit` | Close sepia and the viewer window. `/quit`, `/q` and Ctrl+D do the same. |

Up and down arrows walk the request history, and typing `/` completes commands. The bottom bar shows the model, the current style and charset, and whether the viewer window is connected (`●`) or not (`○`). If you close the viewer, the next request opens it again.

Command-line flags:

| Flag | What it does |
| --- | --- |
| `--download` | Download the local model (about 16 GB) from Hugging Face. Needs `sepia-cli[local]`. |
| `--version` | Print the version. |
| `--help` | Print usage. |

## Configuration

sepia reads settings from the environment, then from `.env` in the current directory, then from `.env` in the user config folder. A value that is already set is never overridden by a later source. See [.env.example](.env.example).

| Variable | Default | Meaning |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | none | Required. Asked for on the first run if missing and saved to the user config `.env`. |
| `POLLINATIONS_KEY` | none | Optional free key from [enter.pollinations.ai](https://enter.pollinations.ai). Uses the keyed endpoint with `flux.2-klein-4b` and no logo. |
| `SEPIA_MODEL` | `claude-haiku-5-5` | The art director model. `claude-sonnet-5-5` writes richer prompts at a higher price. |
| `SEPIA_EFFORT` | `low` | Claude effort: `low`, `medium`, `high`, `xhigh` or `max`. |
| `SEPIA_STYLE` | `ink` | Starting style: `ink` or `fill`. |
| `SEPIA_CHARSET` | `classic` | Starting character set: `classic` or `symbols`. |
| `SEPIA_IMAGE_MODEL` | `black-forest-labs/FLUX.2-klein-4B` | Hugging Face id of the local model. |

An invalid value for `SEPIA_EFFORT`, `SEPIA_STYLE` or `SEPIA_CHARSET` stops sepia at startup.

The user config folder is `%LOCALAPPDATA%\sepia` on Windows and `~/Library/Application Support/sepia` on macOS. It holds the key file, the request history, and one folder per session with that session's pictures (`01.png`, `02.png`, ...). The newest 10 session folders are kept.

## Painting backends

| Backend | When it runs | Notes |
| --- | --- | --- |
| Pollinations, keyed (`gen.pollinations.ai`) | First, when `POLLINATIONS_KEY` is set | `flux.2-klein-4b`, no logo. |
| Pollinations, keyless (`image.pollinations.ai`) | First without a key; second with a key | About one picture per 15 seconds, adds a small logo. Requests are sent with `private=true`. |
| FLUX.2 [klein] 4B, local | When the API fails or rate limits | Needs `sepia-cli[local]` and `sepia --download`. |

After a rate-limit or out-of-credit answer (HTTP 429 or 402), sepia skips that endpoint for 120 seconds instead of retrying it on every picture.

The local model runs on CUDA, then Apple Silicon (MPS), then CPU, whichever is found first:

- **CUDA:** the transformer and text encoder load in 4-bit (bitsandbytes nf4), about 5 GB of VRAM. On an RTX 4070 laptop GPU a 768x512 picture takes about 3 seconds.
- **MPS:** bf16 weights without quantization, so it needs more memory than the CUDA path.
- **CPU:** float32. It works, but slowly.

The model loads on the first local picture, so that picture takes longer. Edits differ by backend: the local model repaints using the previous picture as a reference, while the API cannot see the previous picture and repaints from the full prompt with the scene's fixed seed, which keeps the composition close.

## Cost

| Part | Cost |
| --- | --- |
| Claude Haiku as art director | About $0.0003 per request with the default model and effort |
| Pollinations | Free (keyless, or with the free key) |
| Local model | Free, runs on your hardware |

`SEPIA_MODEL=claude-sonnet-5-5` or a higher `SEPIA_EFFORT` costs more per request.

## Platform notes

**Windows.** The viewer opens as a new Windows Terminal window in focus mode, so there is no tab bar or title bar. It uses a `sepia` profile (6 pt Cascadia Mono, black background, no padding) that sepia writes as a Windows Terminal fragment to `%LOCALAPPDATA%\Microsoft\Windows Terminal\Fragments\sepia\sepia.json`. Your own `settings.json` is not touched; delete that folder to remove the profile. The small font fits several times more cells into the window, which gives the picture more detail. Without Windows Terminal, the viewer falls back to a plain console window.

**macOS.** The viewer opens in a new Terminal.app window through `osascript`. The first time, macOS asks whether your terminal may control Terminal.app (Automation permission); allow it. Terminal.app cannot hide its title bar. Press ⌘- in the viewer window to shrink the font: the picture redraws with more cells and more detail.

**Linux.** Not supported. The viewer window cannot be opened there.

## Privacy

What leaves your machine:

- **To Anthropic:** your request, the earlier requests of the current scene, and the last generated prompt.
- **To Pollinations:** the generated English prompt, the picture size and the seed. Your original request is not sent. Nothing goes to Pollinations when the picture is painted locally.
- **To Hugging Face:** only the model download when you run `sepia --download`.

Pictures, the request history and the API key file stay in the user config folder on your machine. sepia has no telemetry of its own.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the setup on Windows and macOS, the checks, and the commit and test conventions. The design is described in [docs/superpowers/specs/2026-10-28-sepia-design.md](docs/superpowers/specs/2026-10-28-sepia-design.md), and releases in [docs/releasing.md](docs/releasing.md).

## License

[MIT](LICENSE). The optional local model, FLUX.2 [klein] 4B, is published by Black Forest Labs under Apache 2.0 and is downloaded separately from Hugging Face.
