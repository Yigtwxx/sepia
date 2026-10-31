"""Settings, the choices kept between sessions, and API key lookup."""

import contextlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast, get_args

from dotenv import load_dotenv
from platformdirs import user_config_path
from pydantic import BaseModel

from sepia.ascii_art import ArtStyle, Charset
from sepia.painter import DEFAULT_IMAGE_MODEL, Source

Effort = Literal["low", "medium", "high", "xhigh", "max"]
Switch = Literal["off", "on"]
ModelName = Literal["haiku", "sonnet", "opus", "fable"]

MODELS: dict[ModelName, str] = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
    "fable": "claude-fable-5-1",
}
"""The art directors /model switches between, cheapest first: each family's newest
model. All four take effort, structured output, the web search tool and pictures."""
DEFAULT_MODEL = MODELS["haiku"]
DEFAULT_EFFORT: Effort = "high"
"""Haiku 5.5 thinks little more at high than at low (about $0.001 a request either
way), and the extra thought goes into finding an idea for the picture."""
DEFAULT_STYLE: ArtStyle = "ink"
DEFAULT_CHARSET: Charset = "classic"
API_KEY_VAR = "ANTHROPIC_API_KEY"
SEARCH_KEY_VAR = "BRAVE_SEARCH_API_KEY"
ACCOUNT_VAR = "CLOUDFLARE_ACCOUNT_ID"
TOKEN_VAR = "CLOUDFLARE_API_TOKEN"


class ConfigError(ValueError):
    """A setting has a value sepia cannot use."""


@dataclass(frozen=True)
class Settings:
    model: str = DEFAULT_MODEL
    effort: Effort = DEFAULT_EFFORT
    style: ArtStyle = DEFAULT_STYLE
    charset: Charset = DEFAULT_CHARSET
    image_model: str = DEFAULT_IMAGE_MODEL
    mature: bool = False
    """Let Claude paint sexy, dark and violent pictures of adults, never explicit."""
    ask: bool = True
    """Let Claude ask a few questions before painting a vague request."""
    painter: Source = "api"
    """Cloudflare (when its key is set) or this machine only: /api and /local."""


class Choices(BaseModel):
    """What was last picked with a slash command; the next sepia starts with it.

    Only what was picked is kept, so a `SEPIA_*` variable still sets the rest.
    """

    model: str | None = None
    effort: Effort | None = None
    style: ArtStyle | None = None
    charset: Charset | None = None
    mature: bool | None = None
    ask: bool | None = None
    painter: Source | None = None


def config_dir() -> Path:
    """Per-user directory for sepia's key file, history and session files."""
    return user_config_path("sepia", appauthor=False)


def user_env_file() -> Path:
    return config_dir() / ".env"


def load_environment(cwd: Path | None = None) -> None:
    """Fill `os.environ` from `.env` files without overriding what is already set.

    Lookup order: the real environment, then `.env` in the working directory (handy
    while developing), then the `.env` in the user config directory.
    """
    load_dotenv((cwd or Path.cwd()) / ".env", override=False)
    load_dotenv(user_env_file(), override=False)


def choices_file() -> Path:
    return config_dir() / "choices.json"


def load_choices(path: Path | None = None) -> Choices:
    """The choices kept from earlier sessions; none when the file is missing or
    cannot be read."""
    try:
        return Choices.model_validate_json((path or choices_file()).read_bytes())
    except (OSError, ValueError):
        return Choices()


def remember(path: Path | None = None, **picked: object) -> None:
    """Keep `picked` for the next session along with the earlier choices. The file
    is read just before it is written, so several sepia windows keep each other's
    choices."""
    target = path or choices_file()
    choices = load_choices(target).model_copy(update=picked)
    temporary = target.with_suffix(".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(choices.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        pass  # Only a convenience: the choice still holds for this session.


def load_settings(
    environ: Mapping[str, str] = os.environ, chosen: Choices | None = None
) -> Settings:
    """Settings from `SEPIA_*` variables, overridden by what was `chosen` with a
    slash command in an earlier session."""
    model = environ.get("SEPIA_MODEL", "").strip() or DEFAULT_MODEL
    image_model = environ.get("SEPIA_IMAGE_MODEL", "").strip() or DEFAULT_IMAGE_MODEL
    effort = _choice(environ, "SEPIA_EFFORT", get_args(Effort), DEFAULT_EFFORT)
    style = _choice(environ, "SEPIA_STYLE", get_args(ArtStyle), DEFAULT_STYLE)
    charset = _choice(environ, "SEPIA_CHARSET", get_args(Charset), DEFAULT_CHARSET)
    mature = _choice(environ, "SEPIA_MATURE", get_args(Switch), "off")
    ask = _choice(environ, "SEPIA_ASK", get_args(Switch), "on")
    settings = Settings(
        model=model,
        effort=cast(Effort, effort),
        style=cast(ArtStyle, style),
        charset=cast(Charset, charset),
        image_model=image_model,
        mature=mature == "on",
        ask=ask == "on",
    )
    if chosen is None:
        return settings
    return replace(settings, **chosen.model_dump(exclude_none=True))


def api_key(environ: Mapping[str, str] = os.environ) -> str | None:
    return environ.get(API_KEY_VAR, "").strip() or None


def search_key(environ: Mapping[str, str] = os.environ) -> str | None:
    """Optional Brave Search API key: named subjects come from an image search."""
    return environ.get(SEARCH_KEY_VAR, "").strip() or None


def cloudflare_key(environ: Mapping[str, str] = os.environ) -> tuple[str, str] | None:
    """Optional Cloudflare account ID and API token for Workers AI, which paints
    for free up to a daily allowance. Only one of the two is a mistake."""
    account = environ.get(ACCOUNT_VAR, "").strip()
    token = environ.get(TOKEN_VAR, "").strip()
    if bool(account) != bool(token):
        missing = TOKEN_VAR if account else ACCOUNT_VAR
        raise ConfigError(
            f"{missing} is not set; Cloudflare needs both {ACCOUNT_VAR} and {TOKEN_VAR}"
        )
    return (account, token) if account else None


def save_keys(keys: Mapping[str, str], path: Path | None = None) -> Path:
    """Store `keys` (variable name to key) in the user config `.env`, readable only
    by its owner. A key given replaces its old line; every other line stays."""
    target = path or user_env_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    kept: list[str] = []
    if target.exists():
        kept = [
            line
            for line in target.read_text(encoding="utf-8").splitlines()
            if line.partition("=")[0].strip() not in keys
        ]
    added = [f"{name}={key.strip()}" for name, key in keys.items()]
    target.write_text("\n".join([*kept, *added]) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):  # Windows ignores POSIX modes
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return target


def _choice(
    environ: Mapping[str, str], name: str, allowed: tuple[str, ...], default: str
) -> str:
    value = environ.get(name, "").strip().lower() or default
    if value not in allowed:
        raise ConfigError(f"{name} must be one of {', '.join(allowed)}; got {value!r}")
    return value
