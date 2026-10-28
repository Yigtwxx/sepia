"""Ask Claude to turn a short request into a prompt for the local image model."""

from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib.resources import files
from string import Template
from typing import Any

import anthropic
from anthropic.types.beta import (
    BetaOutputConfigParam,
    BetaUsage,
    BetaWebSearchTool20260209Param,
)
from pydantic import BaseModel, Field, ValidationError

from sepia.config import Effort
from sepia.scene import Scene

MAX_TOKENS = 8_000
"""Room for thinking plus a short JSON reply."""
MAX_RETRIES = 3
"""The SDK retries connection errors, 429 and 5xx with exponential backoff."""
FALLBACK_BETA = "server-side-fallback-2026-07-01"
"""Lets the API re-run a declined request on Anthropic's recommended fallback model."""
FALLBACK_MODELS = frozenset(
    {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
)
"""Models that accept `fallbacks: "default"`; Haiku has no server-side fallback."""
WEB_SEARCH: BetaWebSearchTool20260209Param = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 2,
}
"""Lets Claude look up what an unfamiliar name looks like; about $0.01 a search."""
MAX_REFERENCES = 3
"""Links tried for a reference picture; the first usable one wins."""

REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "One short sentence in English.",
        },
        "prompt": {"type": "string", "description": "The English image prompt."},
        "edit": {
            "type": "boolean",
            "description": "True to repaint the previous picture, false for a new one.",
        },
        "references": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Up to three links that show the named subject, best "
            "first; empty when the request names nothing specific.",
        },
    },
    "required": ["message", "prompt", "edit", "references"],
    "additionalProperties": False,
}


class Failure(StrEnum):
    """Why a request failed, so the prompt can explain it in the user's language."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    CONNECTION = "connection"
    REJECTED = "rejected"
    REFUSED = "refused"
    TRUNCATED = "truncated"
    INVALID = "invalid"


class DirectorError(Exception):
    """The request failed. The scene is untouched, so the user can simply retry."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.value)
        self.failure = failure


class _Reply(BaseModel):
    message: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    edit: bool
    references: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Direction:
    message: str
    prompt: str
    edit: bool
    references: tuple[str, ...]
    """Links to a picture of the subject, for `reference.find_reference`."""
    model: str
    """The model that answered; a server-side fallback can differ from the one asked."""
    searches: int
    input_tokens: int
    output_tokens: int


def create_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, max_retries=MAX_RETRIES)


class Director:
    def __init__(self, client: anthropic.Anthropic, model: str, effort: Effort) -> None:
        self._client = client
        self._model = model
        self._effort = effort

    def direct(self, request: str, scene: Scene) -> Direction:
        """Turn `request`, in the context of `scene`, into an image prompt."""
        output_config: BetaOutputConfigParam = {
            "effort": self._effort,
            "format": {"type": "json_schema", "schema": REPLY_SCHEMA},
        }
        fallback = self._model in FALLBACK_MODELS
        try:
            with self._client.beta.messages.stream(
                model=self._model,
                max_tokens=MAX_TOKENS,
                betas=[FALLBACK_BETA] if fallback else anthropic.omit,
                fallbacks="default" if fallback else anthropic.omit,
                system=system_prompt(),
                tools=[WEB_SEARCH],
                output_config=output_config,
                messages=[{"role": "user", "content": build_request(request, scene)}],
            ) as stream:
                message = stream.get_final_message()
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise DirectorError(Failure.AUTH) from exc
        except anthropic.RateLimitError as exc:
            raise DirectorError(Failure.RATE_LIMIT) from exc
        except anthropic.BadRequestError as exc:
            raise DirectorError(Failure.REJECTED) from exc
        except anthropic.APIStatusError as exc:
            raise DirectorError(Failure.SERVER) from exc
        except anthropic.APIConnectionError as exc:
            raise DirectorError(Failure.CONNECTION) from exc

        if message.stop_reason == "refusal":
            raise DirectorError(Failure.REFUSED)
        if message.stop_reason == "max_tokens":
            raise DirectorError(Failure.TRUNCATED)
        # The JSON is the last text block; a search can put remarks before it.
        texts = [block.text for block in message.content if block.type == "text"]
        text = texts[-1] if texts else ""
        try:
            reply = _Reply.model_validate_json(text)
        except ValidationError as exc:
            raise DirectorError(Failure.INVALID) from exc
        return Direction(
            message=reply.message.strip(),
            prompt=reply.prompt.strip(),
            edit=reply.edit and not scene.is_empty,
            references=_links(reply.references),
            model=message.model,
            searches=_searches(message.usage),
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )


def _searches(usage: BetaUsage) -> int:
    """Web searches the request ran; None when it ran no server tool at all."""
    server = usage.server_tool_use
    return server.web_search_requests if server is not None else 0


def _links(raw: list[str]) -> tuple[str, ...]:
    """The first few https links, trimmed; anything else is dropped."""
    links = [link.strip() for link in raw]
    web = [link for link in links if link.startswith("https://")]
    return tuple(web[:MAX_REFERENCES])


@cache
def system_prompt() -> str:
    return _prompt("director.md")


def build_request(request: str, scene: Scene) -> str:
    if scene.is_empty:
        history = (
            "<previous_requests>none: this is the first picture</previous_requests>"
        )
    else:
        earlier = "\n".join(f"{i}. {text}" for i, text in enumerate(scene.requests, 1))
        history = (
            f"<previous_requests>\n{earlier}\n</previous_requests>\n"
            f"<previous_prompt>{scene.prompts[-1]}</previous_prompt>"
        )
    return Template(_prompt("request.md")).substitute(
        history=history, request=request.strip()
    )


@cache
def _prompt(name: str) -> str:
    return files("sepia").joinpath("prompts", name).read_text(encoding="utf-8")
