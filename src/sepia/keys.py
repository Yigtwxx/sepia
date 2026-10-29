"""The API keys sepia uses: asked for on the first run and with /keys.

They are kept in the user config `.env` (`config.save_keys`) and never shown: a
prompt hides what is typed, and a key's state is only "set" or "not set".
"""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from prompt_toolkit import PromptSession

from sepia.config import ACCOUNT_VAR, API_KEY_VAR, TOKEN_VAR


@dataclass(frozen=True)
class Key:
    name: str
    """What /keys calls it."""
    variables: tuple[str, ...]
    """Its environment variables, asked in this order."""


KEYS: tuple[Key, ...] = (
    Key("anthropic", (API_KEY_VAR,)),
    Key("cloudflare", (ACCOUNT_VAR, TOKEN_VAR)),
)
"""Anthropic writes the prompts and is needed; Cloudflare paints and is optional.
Brave Search is paid beyond a monthly credit, so it is not asked for; a
`BRAVE_SEARCH_API_KEY` set in `.env` still works."""


def key_named(name: str) -> Key:
    for key in KEYS:
        if key.name == name:
            return key
    raise KeyError(name)


def ask_values(key: Key, ask: Callable[[str], str]) -> dict[str, str]:
    """What is typed for each of `key`'s variables, or nothing when one is left
    empty: Cloudflare needs both its account ID and its token, and an empty first
    answer skips the key without asking for the rest."""
    values: dict[str, str] = {}
    for variable in key.variables:
        value = ask(variable).strip()
        if not value:
            return {}
        values[variable] = value
    return values


def is_set(key: Key, environ: Mapping[str, str] = os.environ) -> bool:
    return all(environ.get(variable, "").strip() for variable in key.variables)


def ask_secret(label: str) -> str:
    """One line typed with its characters hidden; the prompt erases itself.
    Raises KeyboardInterrupt on Ctrl+C and EOFError on Ctrl+D."""
    session: PromptSession[str] = PromptSession(erase_when_done=True)
    return session.prompt(label, is_password=True)
