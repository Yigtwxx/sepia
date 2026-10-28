"""Ask Claude to paint, or keep painting, the scene as SVG."""

from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib.resources import files
from string import Template
from typing import Any

import anthropic
from anthropic.types.beta import BetaOutputConfigParam
from pydantic import BaseModel, Field, ValidationError

from sepia.config import Effort
from sepia.raster import RenderError, render_svg
from sepia.scene import Canvas, Scene

MAX_TOKENS = 32_000
"""Room for thinking plus a full SVG; streaming keeps a long reply from timing out."""
MAX_RETRIES = 3
"""The SDK retries connection errors, 429 and 5xx with exponential backoff."""
FALLBACK_BETA = "server-side-fallback-2026-07-01"
"""Lets the API re-run a declined request on Anthropic's recommended fallback model."""

REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "One short sentence in the language of the latest request.",
        },
        "svg": {"type": "string", "description": "The complete SVG document."},
    },
    "required": ["message", "svg"],
    "additionalProperties": False,
}


class Failure(StrEnum):
    """Why a drawing failed, so the prompt can explain it in the user's language."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    CONNECTION = "connection"
    REJECTED = "rejected"
    REFUSED = "refused"
    TRUNCATED = "truncated"
    INVALID = "invalid"


class ArtistError(Exception):
    """A drawing failed. The scene is untouched, so the user can simply retry."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.value)
        self.failure = failure


class _Reply(BaseModel):
    message: str = Field(min_length=1)
    svg: str = Field(min_length=1)


@dataclass(frozen=True)
class Drawing:
    message: str
    svg: str
    input_tokens: int
    output_tokens: int


def create_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, max_retries=MAX_RETRIES)


class Artist:
    def __init__(self, client: anthropic.Anthropic, model: str, effort: Effort) -> None:
        self._client = client
        self._model = model
        self._effort = effort

    def draw(self, request: str, scene: Scene, canvas: Canvas) -> Drawing:
        """Paint `request` on top of `scene` for a window shaped like `canvas`."""
        output_config: BetaOutputConfigParam = {
            "effort": self._effort,
            "format": {"type": "json_schema", "schema": REPLY_SCHEMA},
        }
        try:
            with self._client.beta.messages.stream(
                model=self._model,
                max_tokens=MAX_TOKENS,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                system=system_prompt(),
                output_config=output_config,
                messages=[
                    {"role": "user", "content": build_request(request, scene, canvas)}
                ],
            ) as stream:
                message = stream.get_final_message()
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise ArtistError(Failure.AUTH) from exc
        except anthropic.RateLimitError as exc:
            raise ArtistError(Failure.RATE_LIMIT) from exc
        except anthropic.BadRequestError as exc:
            raise ArtistError(Failure.REJECTED) from exc
        except anthropic.APIStatusError as exc:
            raise ArtistError(Failure.SERVER) from exc
        except anthropic.APIConnectionError as exc:
            raise ArtistError(Failure.CONNECTION) from exc

        if message.stop_reason == "refusal":
            raise ArtistError(Failure.REFUSED)
        if message.stop_reason == "max_tokens":
            raise ArtistError(Failure.TRUNCATED)
        text = "".join(block.text for block in message.content if block.type == "text")
        try:
            reply = _Reply.model_validate_json(text)
        except ValidationError as exc:
            raise ArtistError(Failure.INVALID) from exc
        svg = reply.svg.strip()
        try:
            render_svg(svg, 32, 16)
        except RenderError as exc:
            raise ArtistError(Failure.INVALID) from exc
        return Drawing(
            message=reply.message.strip(),
            svg=svg,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )


@cache
def system_prompt() -> str:
    return _prompt("system.md")


def build_request(request: str, scene: Scene, canvas: Canvas) -> str:
    width, height = canvas.viewbox()
    if scene.svg is None:
        scene_block = "<scene>empty: this is a new picture</scene>"
    else:
        earlier = "\n".join(f"{i}. {text}" for i, text in enumerate(scene.requests, 1))
        scene_block = (
            f"<previous_requests>\n{earlier}\n</previous_requests>\n"
            f"<current_svg>\n{scene.svg}\n</current_svg>"
        )
    return Template(_prompt("request.md")).substitute(
        scene=scene_block,
        width=width,
        height=height,
        cols=canvas.cols,
        rows=canvas.rows,
        request=request.strip(),
    )


@cache
def _prompt(name: str) -> str:
    return files("sepia").joinpath("prompts", name).read_text(encoding="utf-8")
