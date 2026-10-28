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

from sepia.ascii_art import ArtStyle

Effort = Literal["low", "medium", "high", "xhigh", "max"]

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT: Effort = "medium"
DEFAULT_STYLE: ArtStyle = "fill"
API_KEY_VAR = "ANTHROPIC_API_KEY"


class ConfigError(ValueError):
    """A setting has a value sepia cannot use."""


@dataclass(frozen=True)
class Settings:
    model: str = DEFAULT_MODEL
    effort: Effort = DEFAULT_EFFORT
    style: ArtStyle = DEFAULT_STYLE


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
    effort = _choice(environ, "SEPIA_EFFORT", get_args(Effort), DEFAULT_EFFORT)
    style = _choice(environ, "SEPIA_STYLE", get_args(ArtStyle), DEFAULT_STYLE)
    return Settings(
        model=model, effort=cast(Effort, effort), style=cast(ArtStyle, style)
    )


def api_key(environ: Mapping[str, str] = os.environ) -> str | None:
    return environ.get(API_KEY_VAR, "").strip() or None


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
