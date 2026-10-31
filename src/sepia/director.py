"""Ask Claude to turn a short request into a prompt for the local image model."""

import base64
import io
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib.resources import files
from string import Template
from typing import Any

import anthropic
from anthropic.types.beta import (
    BetaContentBlockParam,
    BetaImageBlockParam,
    BetaOutputConfigParam,
    BetaUsage,
    BetaWebSearchTool20260209Param,
)
from PIL import Image
from pydantic import BaseModel, Field, ValidationError

from sepia.config import Effort
from sepia.scene import Scene

MAX_TOKENS = 32_000
"""Room for thinking plus a short JSON reply; Opus and Fable think at length at
high effort and above. Only what is written is billed."""
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
LINKED_SIDE = 1024
"""Longest side of a linked picture shown to Claude; more detail only costs tokens."""
MAX_QUESTIONS = 3
"""Questions asked about one request; more would feel like a form."""
MAX_OPTIONS = 4
"""Options per question, besides the person's own answer."""
MAX_HEADER = 12
"""Characters in a question's tab."""

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
        "subject": {
            "type": "string",
            "description": "A short image search query for the named subject, "
            "such as 'Yunara League of Legends'; empty when there is none.",
        },
        "show": {
            "type": "boolean",
            "description": "True when the request is the named subject and nothing "
            "else, so sepia shows its picture as it is instead of painting.",
        },
    },
    "required": ["message", "prompt", "edit", "references", "subject", "show"],
    "additionalProperties": False,
}
_OPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "One to five words."},
        "description": {
            "type": "string",
            "description": "At most eight words on what the picture would show.",
        },
    },
    "required": ["label", "description"],
    "additionalProperties": False,
}
_QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "header": {
            "type": "string",
            "description": "One or two words, at most 12 characters.",
        },
        "question": {
            "type": "string",
            "description": "One short sentence ending in a question mark.",
        },
        "multi": {
            "type": "boolean",
            "description": "True when several answers combine well.",
        },
        "options": {
            "type": "array",
            "items": _OPTION_SCHEMA,
            "description": "Two to four clearly different options.",
        },
    },
    "required": ["header", "question", "multi", "options"],
    "additionalProperties": False,
}
ASK_SCHEMA: dict[str, Any] = {
    **REPLY_SCHEMA,
    "properties": {
        **REPLY_SCHEMA["properties"],
        "questions": {
            "type": "array",
            "items": _QUESTION_SCHEMA,
            "description": "One to three questions about a vague request; empty "
            "when the request says what to paint.",
        },
    },
    "required": [*REPLY_SCHEMA["required"], "questions"],
}
"""The reply while clarifying questions are on."""


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


class _Option(BaseModel):
    label: str = ""
    description: str = ""


class _Question(BaseModel):
    header: str = ""
    question: str = ""
    multi: bool = False
    options: list[_Option] = Field(default_factory=list)


class _Reply(BaseModel):
    message: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    edit: bool
    references: list[str] = Field(default_factory=list)
    subject: str = ""
    show: bool = False
    questions: list[_Question] = Field(default_factory=list)


@dataclass(frozen=True)
class Option:
    label: str
    description: str


@dataclass(frozen=True)
class Question:
    """One of Claude's questions about a vague request."""

    header: str
    """The question's tab: one or two words."""
    text: str
    multi: bool
    """Several options can be picked together."""
    options: tuple[Option, ...]


@dataclass(frozen=True)
class Answer:
    header: str
    question: str
    choices: tuple[str, ...]
    """Option labels and the person's own words, in the order shown."""


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
    subject: str = ""
    """An image search query for the named subject, for `reference.find_subject`."""
    show: bool = False
    """Show the subject's picture as it is: the request was only its name."""
    questions: tuple[Question, ...] = ()
    """Asked before painting a vague new picture; `prompt` is the guess meanwhile."""


def create_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, max_retries=MAX_RETRIES)


class Director:
    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str,
        effort: Effort,
        mature: bool = False,
        ask: bool = False,
    ) -> None:
        self._client = client
        self._model = model
        self._effort = effort
        self._mature = mature
        self._ask = ask

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, model: str) -> None:
        """Takes effect from the next request; /model sets it while sepia waits."""
        self._model = model

    @property
    def effort(self) -> Effort:
        return self._effort

    @effort.setter
    def effort(self, effort: Effort) -> None:
        """Takes effect from the next request; /effort sets it while sepia waits."""
        self._effort = effort

    @property
    def mature(self) -> bool:
        return self._mature

    @mature.setter
    def mature(self, mature: bool) -> None:
        """Takes effect from the next request; /mature sets it while sepia waits."""
        self._mature = mature

    @property
    def ask(self) -> bool:
        return self._ask

    @ask.setter
    def ask(self, ask: bool) -> None:
        """Takes effect from the next request; /config sets it while sepia waits."""
        self._ask = ask

    def direct(
        self,
        request: str,
        scene: Scene,
        linked: Image.Image | None = None,
        answers: Sequence[Answer] = (),
    ) -> Direction:
        """Turn `request`, in the context of `scene`, into an image prompt.

        `linked` is a picture of the subject, linked by the person or found by
        sepia; Claude sees it, so it can write the subject's look into the prompt
        without searching. `answers` are the person's answers to Claude's
        questions about this request. Questions come back only for a vague new
        picture: never for /add, a reference picture, answers or a named subject.
        """
        output_config: BetaOutputConfigParam = {
            "effort": self._effort,
            "format": {
                "type": "json_schema",
                "schema": ASK_SCHEMA if self._ask else REPLY_SCHEMA,
            },
        }
        fallback = self._model in FALLBACK_MODELS
        text = build_request(request, scene, linked=linked is not None, answers=answers)
        content: str | list[BetaContentBlockParam] = text
        if linked is not None:
            content = [_image_block(linked), {"type": "text", "text": text}]
        try:
            with self._client.beta.messages.stream(
                model=self._model,
                max_tokens=MAX_TOKENS,
                betas=[FALLBACK_BETA] if fallback else anthropic.omit,
                fallbacks="default" if fallback else anthropic.omit,
                system=system_prompt(self._mature, self._ask),
                tools=[WEB_SEARCH],
                output_config=output_config,
                messages=[{"role": "user", "content": content}],
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
        edit = reply.edit and not scene.is_empty
        references = _links(reply.references)
        subject = reply.subject.strip()
        asks = (
            self._ask
            and scene.is_empty
            and linked is None
            and not answers
            and not subject
            and not references
        )
        return Direction(
            message=reply.message.strip(),
            prompt=reply.prompt.strip(),
            edit=edit,
            references=references,
            model=message.model,
            searches=_searches(message.usage),
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            subject=subject,
            show=reply.show and not edit,
            questions=_questions(reply.questions) if asks else (),
        )


def _image_block(picture: Image.Image) -> BetaImageBlockParam:
    small = picture.convert("RGB")
    small.thumbnail((LINKED_SIDE, LINKED_SIDE))
    buffer = io.BytesIO()
    small.save(buffer, format="JPEG", quality=85)
    data = base64.standard_b64encode(buffer.getvalue()).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": data},
    }


def _searches(usage: BetaUsage) -> int:
    """Web searches the request ran; None when it ran no server tool at all."""
    server = usage.server_tool_use
    return server.web_search_requests if server is not None else 0


def _links(raw: list[str]) -> tuple[str, ...]:
    """The first few https links, trimmed; anything else is dropped."""
    links = [link.strip() for link in raw]
    web = [link for link in links if link.startswith("https://")]
    return tuple(web[:MAX_REFERENCES])


def _questions(raw: list[_Question]) -> tuple[Question, ...]:
    """Claude's questions within sepia's limits; one that cannot be asked (no
    text, fewer than two options) is dropped."""
    kept: list[Question] = []
    for item in raw:
        options = tuple(
            Option(option.label.strip(), option.description.strip())
            for option in item.options
            if option.label.strip()
        )[:MAX_OPTIONS]
        text = item.question.strip()
        if not text or len(options) < 2:
            continue
        header = item.header.strip()[:MAX_HEADER].rstrip()
        kept.append(
            Question(header or f"Question {len(kept) + 1}", text, item.multi, options)
        )
    return tuple(kept[:MAX_QUESTIONS])


@cache
def system_prompt(mature: bool = False, ask: bool = False) -> str:
    """The art director's instructions; `mature` adds the rules for grown-up
    pictures and `ask` the rules for clarifying questions."""
    parts = [_prompt("director.md")]
    if mature:
        parts.append(_prompt("mature.md"))
    if ask:
        parts.append(_prompt("ask.md"))
    return "\n\n".join(parts)


def build_request(
    request: str, scene: Scene, linked: bool = False, answers: Sequence[Answer] = ()
) -> str:
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
    picture = (
        "<reference_picture>the picture above shows the subject</reference_picture>\n"
        if linked
        else ""
    )
    given = ""
    if answers:
        lines = "\n".join(
            f"{answer.header}: {answer.question} {'; '.join(answer.choices)}"
            for answer in answers
        )
        given = f"\n<answers>\n{lines}\n</answers>"
    return Template(_prompt("request.md")).substitute(
        history=history, linked=picture, request=request.strip(), answers=given
    )


@cache
def _prompt(name: str) -> str:
    return files("sepia").joinpath("prompts", name).read_text(encoding="utf-8")
