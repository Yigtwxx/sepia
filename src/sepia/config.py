"""Settings and API key lookup."""

import contextlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast, get_args

from dotenv import load_dotenv
from platformdirs import user_config_path

from sepia.ascii_art import ArtStyle, Charset
from sepia.painter import DEFAULT_IMAGE_MODEL

Effort = Literal["low", "medium", "high", "xhigh", "max"]
Switch = Literal["off", "on"]

DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_EFFORT: Effort = "high"
"""Haiku 5.5 thinks little more at high than at low (about $0.001 a request either
way), and the extra thought goes into finding an idea for the picture."""
DEFAULT_STYLE: ArtStyle = "ink"
DEFAULT_CHARSET: Charset = "classic"
API_KEY_VAR = "ANTHROPIC_API_KEY"
SEARCH_KEY_VAR = "BRAVE_SEARCH_API_KEY"


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


def load_settings(environ: Mapping[str, str] = os.environ) -> Settings:
    model = environ.get("SEPIA_MODEL", "").strip() or DEFAULT_MODEL
    image_model = environ.get("SEPIA_IMAGE_MODEL", "").strip() or DEFAULT_IMAGE_MODEL
    effort = _choice(environ, "SEPIA_EFFORT", get_args(Effort), DEFAULT_EFFORT)
    style = _choice(environ, "SEPIA_STYLE", get_args(ArtStyle), DEFAULT_STYLE)
    charset = _choice(environ, "SEPIA_CHARSET", get_args(Charset), DEFAULT_CHARSET)
    mature = _choice(environ, "SEPIA_MATURE", get_args(Switch), "off")
    return Settings(
        model=model,
        effort=cast(Effort, effort),
        style=cast(ArtStyle, style),
        charset=cast(Charset, charset),
        image_model=image_model,
        mature=mature == "on",
    )


def api_key(environ: Mapping[str, str] = os.environ) -> str | None:
    return environ.get(API_KEY_VAR, "").strip() or None


def search_key(environ: Mapping[str, str] = os.environ) -> str | None:
    """Optional Brave Search API key: named subjects come from an image search."""
    return environ.get(SEARCH_KEY_VAR, "").strip() or None


def pollinations_key(environ: Mapping[str, str] = os.environ) -> str | None:
    """Optional key from enter.pollinations.ai: no logo and better models, paid
    from the account's pollen."""
    return environ.get("POLLINATIONS_KEY", "").strip() or None


def save_api_key(key: str, path: Path | None = None) -> Path:
    """Store `key` in the user config `.env`, readable only by its owner."""
    target = path or user_env_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    kept: list[str] = []
    if target.exists():
        kept = [
            line
            for line in target.read_text(encoding="utf-8").splitlines()
            if not line.startswith(f"{API_KEY_VAR}=")
        ]
    target.write_text("\n".join([*kept, f"{API_KEY_VAR}={key.strip()}"]) + "\n")
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
