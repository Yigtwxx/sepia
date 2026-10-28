from unittest.mock import MagicMock

import anthropic
import httpx2
import pytest

from sepia.artist import (
    FALLBACK_BETA,
    REPLY_SCHEMA,
    Artist,
    ArtistError,
    Failure,
    build_request,
)
from sepia.scene import Canvas, Scene

CANVAS = Canvas(cols=120, rows=40)
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800">'
    '<rect width="1200" height="800" fill="#123456"/></svg>'
)
_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls: type[anthropic.APIStatusError], code: int) -> Exception:
    return cls("error", response=httpx2.Response(code, request=_REQUEST), body=None)


def test_artist_draw_sends_model_effort_fallback_and_schema(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message({"message": "Done.", "svg": SVG}))
    Artist(fake_client, "claude-opus-5-5", "high").draw("waterfall", Scene(), CANVAS)
    kwargs = fake_client.beta.messages.stream.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5-5", f"Wrong model: {kwargs['model']}"
    assert kwargs["fallbacks"] == "default", f"Wrong fallbacks: {kwargs['fallbacks']}"
    assert FALLBACK_BETA in kwargs["betas"], f"Missing beta in {kwargs['betas']}"
    expected = {
        "effort": "high",
        "format": {"type": "json_schema", "schema": REPLY_SCHEMA},
    }
    assert kwargs["output_config"] == expected, f"Got {kwargs['output_config']}"
    assert "illustrator inside sepia" in kwargs["system"], "System prompt not loaded"


def test_artist_draw_valid_reply_returns_stripped_drawing(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    reply = {"message": "  A blue night.  ", "svg": f"\n{SVG}\n"}
    set_final_message(make_message(reply))
    drawing = Artist(fake_client, "m", "medium").draw("night", Scene(), CANVAS)
    assert drawing.message == "A blue night.", f"Got {drawing.message!r}"
    assert drawing.svg == SVG, f"Got {drawing.svg!r}"
    tokens = (drawing.input_tokens, drawing.output_tokens)
    assert tokens == (1200, 3400), f"Got {tokens}"


@pytest.mark.parametrize(
    ("reply", "stop_reason", "failure"),
    [
        ({"message": "x", "svg": SVG}, "refusal", Failure.REFUSED),
        ({"message": "x", "svg": SVG}, "max_tokens", Failure.TRUNCATED),
        ("not json", "end_turn", Failure.INVALID),
        ({"message": "x"}, "end_turn", Failure.INVALID),
        ({"message": "x", "svg": "<svg"}, "end_turn", Failure.INVALID),
    ],
)
def test_artist_draw_bad_response_raises_matching_failure(
    fake_client: MagicMock,
    make_message,
    set_final_message,
    reply,
    stop_reason: str,
    failure: Failure,
) -> None:
    set_final_message(make_message(reply, stop_reason))
    with pytest.raises(ArtistError) as exc:
        Artist(fake_client, "m", "medium").draw("x", Scene(), CANVAS)
    assert exc.value.failure is failure, f"Expected {failure}, got {exc.value.failure}"


@pytest.mark.parametrize(
    ("error", "failure"),
    [
        (_status_error(anthropic.AuthenticationError, 401), Failure.AUTH),
        (_status_error(anthropic.PermissionDeniedError, 403), Failure.AUTH),
        (_status_error(anthropic.RateLimitError, 429), Failure.RATE_LIMIT),
        (_status_error(anthropic.BadRequestError, 400), Failure.REJECTED),
        (_status_error(anthropic.InternalServerError, 500), Failure.SERVER),
        (anthropic.APIConnectionError(request=_REQUEST), Failure.CONNECTION),
    ],
)
def test_artist_draw_api_error_raises_matching_failure(
    fake_client: MagicMock, error: Exception, failure: Failure
) -> None:
    fake_client.beta.messages.stream.side_effect = error
    with pytest.raises(ArtistError) as exc:
        Artist(fake_client, "m", "medium").draw("x", Scene(), CANVAS)
    assert exc.value.failure is failure, f"Expected {failure}, got {exc.value.failure}"


def test_build_request_empty_scene_asks_for_new_picture() -> None:
    text = build_request("  waterfall ", Scene(), CANVAS)
    assert "<request>waterfall</request>" in text, f"Request missing in {text!r}"
    assert "new picture" in text, f"Empty-scene note missing in {text!r}"
    assert 'viewBox="0 0 1200 800"' in text, f"Wrong viewBox in {text!r}"


def test_build_request_existing_scene_includes_history_and_svg() -> None:
    scene = Scene()
    scene.record("waterfall", SVG)
    text = build_request("mountains", scene, CANVAS)
    assert "1. waterfall" in text, f"History missing in {text!r}"
    assert f"<current_svg>\n{SVG}\n</current_svg>" in text, "Current SVG missing"
    assert "<request>mountains</request>" in text, f"Request missing in {text!r}"
