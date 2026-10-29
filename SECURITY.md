# Security policy

## Supported versions

Only the latest release of `sepia-cli` on PyPI gets security fixes.

## Reporting a vulnerability

Report vulnerabilities privately through GitHub: open [a new security advisory](https://github.com/Yigtwxx/sepia/security/advisories/new) on `Yigtwxx/sepia` (repository *Security* tab, *Report a vulnerability*). Do not open a public issue, pull request or discussion for a vulnerability.

Include the sepia version (`sepia --version`), your operating system, steps to reproduce, and what an attacker could do. If the report contains an API key or other secret, revoke it first.

The maintainer, [@Yigtwxx](https://github.com/Yigtwxx), handles reports on a best-effort basis and answers in the advisory thread.

## What sepia protects, and how

**API keys.**

- `ANTHROPIC_API_KEY` and `CLOUDFLARE_API_TOKEN` (with `CLOUDFLARE_ACCOUNT_ID`) are read from the environment or from `.env` files. The key and the token are never written to code, logs or error messages.
- When sepia asks for the Anthropic key on the first run, the input is hidden. The key is saved to `.env` in the user config folder (`%LOCALAPPDATA%\sepia` on Windows, `~/Library/Application Support/sepia` on macOS). On macOS the file is set to mode 600. On Windows, POSIX modes do not apply; the file relies on the per-user profile folder's default permissions.
- The Cloudflare token travels only in the `Authorization: Bearer` header of HTTPS requests to `api.cloudflare.com`.

**The channel between the two windows.**

- The prompt window listens on `127.0.0.1` on a random port. Nothing listens on other interfaces.
- For each session it generates a 32-byte random key and writes it, with the port, to a session file in the user config folder, readable only by the current user (mode 600 on macOS).
- The viewer must pass the HMAC challenge of `multiprocessing.connection` with that key. A peer that fails it is dropped, and the prompt keeps waiting for the real viewer.
- Messages are JSON only. They are decoded with `json.loads` and never unpickled, so a peer can send data but not code. The viewer accepts only known message types and known style and charset names.

**Launching the viewer.** The viewer runs as `<current python> -m sepia --viewer <session file>`. On Windows the command is passed as an argument list, without a shell. On macOS it goes through AppleScript, with the command quoted by `shlex.join` and escaped for the AppleScript string.

## Out of scope

- What the image model paints. Pictures come from a third-party model, FLUX.2 [klein] 4B, on Cloudflare Workers AI or on your own GPU.
- Issues in Anthropic, Cloudflare or Hugging Face services themselves; report those to the provider.
- Data those services receive by design: the request text goes to Anthropic, and the generated prompt, with any input pictures, goes to Cloudflare unless the picture is painted locally. See the privacy section of the [README](README.md#privacy).
- Attacks that need control of the user's account or files already, such as reading the key file as the same user.
