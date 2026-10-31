# sepia update

`sepia update` upgrades sepia with the installer that installed it, in the same
terminal, as `claude update` does. On start, sepia says when a newer release is
on PyPI. Ships in **0.4.1**.

## Choice

The upgrade runs in the same terminal (approach A). Rejected: a detached
helper that upgrades after sepia exits (a second console window), and only
printing the command.

Windows is the hard part: an installer cannot overwrite a running `.exe`
(uv issues #11930, #14520, #17548: "being used by another process", leaving a
stale `sepia.exe` that the next upgrade calls up to date), and a running Python
locks the compiled modules it has loaded. So on Windows:

- the running `sepia.exe` is **renamed** to `sepia.exe.old` before the
  installer runs (Windows allows renaming a running program; yt-dlp and pipx do
  the same), put back if the installer wrote no new one, and deleted on the next
  start;
- `sepia update` imports nothing with compiled modules from sepia's
  environment (no pydantic, numpy, Pillow): only the standard library, rich and
  `sepia.ui`;
- when other sepia processes from the same install run (another prompt window,
  a picture window), it refuses before touching anything and says to close
  them.

## How sepia was installed

`update.find_install()` looks at `sys.prefix`:

| Found | Method | Upgrade |
|---|---|---|
| `uv-receipt.toml` whose `sepia-cli` requirement is from PyPI | `uv` | `uv tool upgrade sepia-cli` |
| `uv-receipt.toml` whose requirement has `editable`, `directory`, `path`, `git` or `url` | `source` | none: says where it comes from |
| `pipx_metadata.json` | `pipx` | `pipx upgrade sepia-cli` |
| `direct_url.json` in sepia-cli's dist-info (a folder or URL install) | `source` | none |
| anything else | `pip` | `<sys.executable> -m pip install --upgrade sepia-cli` |

`uv tool upgrade` keeps the extras (`[local]`, `[cam]`) and the index options
(`--index`, `--index-strategy`) from the receipt, so a CUDA install stays one.
The launcher to rename is the receipt's entrypoint `install-path`, else
`sys.argv[0]` when it is an `.exe`.

## sepia update

```text
$ sepia update
 ⏺ sepia 0.4.2 is out (you have 0.4.1)
   uv tool upgrade sepia-cli
   …the installer's own output…
 ⏺ Updated to sepia 0.4.2
```

1. A source install: `⏺ sepia is installed from C:/…/sepia, not PyPI: update
   it there (git pull)`; exit 0.
2. PyPI's latest (`https://pypi.org/pypi/sepia-cli/json`, `info.version`,
   which skips pre-releases; 3 s timeout) is not newer: `⏺ sepia 0.4.1 is the
   latest version`; exit 0. PyPI unreachable: `⏺ Could not reach PyPI; trying
   the update anyway` and go on.
3. Windows, other sepia processes running: `⏺ Close the other sepia windows
   first (2 still open), then run sepia update again` (warning color); exit 1.
   Counted with PowerShell `Get-CimInstance Win32_Process` by executable path
   equal to `sys.executable`, leaving out this process and its parent; when that
   cannot run, the count is 0.
4. The installer is not on PATH (`uv`, `pipx`): `⏺ uv is not on PATH; run this
   yourself: uv tool upgrade sepia-cli`; exit 1.
5. Otherwise the command line is printed (muted), the launcher is moved aside
   on Windows, and the installer runs with its output in the terminal. Exit code
   0: `⏺ Updated to sepia 0.4.2` (or "to the latest version" when PyPI was not
   reached). Otherwise `⏺ The update failed; the message above says why. Try
   again with: uv tool upgrade sepia-cli` and its exit code.

Versions compare by their numbers; a pre-release of the same numbers
(`0.5.0a1`) comes before the release.

## Notice on start

- `update.json` in the config folder keeps `{"latest": "0.4.2", "checked":
  "<ISO time>"}`.
- On start the welcome screen shows, from that file and without waiting,
  ` ↑ sepia 0.4.2 is out: run sepia update` under the tip when it is newer than
  the running version.
- A daemon thread then asks PyPI again when the last check is a day old or
  missing and writes the file; a failed check changes nothing. The answer shows
  on the next start.
- Setting `update_check` (default on): `Settings.update_check`,
  `Choices.update_check`, `SEPIA_UPDATE_CHECK` (`on`/`off`), and a third
  `/config` row "Update notices · say when a new sepia is out". Off: no request
  and no notice.
- `sepia` deletes a `sepia.exe.old` beside its launcher on every start
  (Windows), ignoring errors.

## Strings, docs

All messages in `ui.STRINGS`. README: an "Update" part in Install, `sepia
update` in the commands, the notice, `SEPIA_UPDATE_CHECK`, the `/config` row.
Site: `SEPIA_UPDATE_CHECK` in the settings list, `sepia update` beside the
install lines, version 0.4.1. CHANGELOG under Added. CLAUDE.md layout:
`update.py`.

## Testing

`tests/test_update.py`: each install kind from files in a temporary prefix;
`is_newer`; the PyPI answer through the `web` fixture (good, unreachable,
malformed); the cache (fresh not asked again, stale asked and written, failed
check keeps the old file); the notice; `run_update` with `subprocess.run` and
`shutil.which` replaced (latest, newer, source, others running, installer
missing, failure, the Windows rename and its undo); deleting the old launcher.
`test_cli.py`: `sepia update` runs it. `test_config.py`: `SEPIA_UPDATE_CHECK`.
`test_repl.py`: the `/config` row and the notice on the welcome screen.
