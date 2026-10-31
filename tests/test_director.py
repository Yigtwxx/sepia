import base64
import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx2
import pytest
from PIL import Image

from sepia.director import (
    ASK_SCHEMA,
    FALLBACK_BETA,
    LINKED_SIDE,
    REPLY_SCHEMA,
    Answer,
    Director,
    DirectorError,
    Failure,
    Option,
    Question,
    build_request,
    system_prompt,
)
from sepia.scene import Scene

REPLY = {"message": "Şelale çiziyorum.", "prompt": "A waterfall.", "edit": False}
_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls: type[anthropic.APIStatusError], code: int) -> Exception:
    return cls("error", response=httpx2.Response(code, request=_REQUEST), body=None)


def _painted_scene() -> Scene:
    scene = Scene()
    scene.record("şelale", "A waterfall in a canyon.", Image.new("RGB", (4, 4)))
    return scene


@pytest.mark.parametrize(
    ("model", "with_fallback"),
    [("claude-haiku-5-5", False), ("claude-sonnet-5-5", True)],
)
def test_director_direct_sends_fallback_only_for_supporting_models(
    fake_client: MagicMock, make_message, set_final_message, model: str, with_fallback
) -> None:
    set_final_message(make_message(REPLY))
    Director(fake_client, model, "low").direct("şelale", Scene())
    kwargs = fake_client.beta.messages.stream.call_args.kwargs
    has_fallback = kwargs["fallbacks"] == "default"
    assert has_fallback is with_fallback, f"{model}: fallbacks={kwargs['fallbacks']}"
    if with_fallback:
        assert FALLBACK_BETA in kwargs["betas"], f"Missing beta in {kwargs['betas']}"


def test_director_direct_requests_schema_and_effort(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message(REPLY))
    Director(fake_client, "claude-haiku-5-5", "low").direct("şelale", Scene())
    kwargs = fake_client.beta.messages.stream.call_args.kwargs
    expected = {
        "effort": "low",
        "format": {"type": "json_schema", "schema": REPLY_SCHEMA},
    }
    assert kwargs["output_config"] == expected, f"Got {kwargs['output_config']}"
    assert "art director inside sepia" in kwargs["system"], "System prompt not loaded"


def test_director_effort_change_applies_to_the_next_request(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message(REPLY))
    director = Director(fake_client, "claude-haiku-5-5", "low")
    director.effort = "max"
    director.direct("şelale", Scene())
    config = fake_client.beta.messages.stream.call_args.kwargs["output_config"]
    assert config["effort"] == "max", f"Got {config}"


def test_director_model_change_applies_to_the_next_request(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message(REPLY))
    director = Director(fake_client, "claude-haiku-5-5", "low")
    director.model = "claude-opus-5-5"
    director.direct("şelale", Scene())
    kwargs = fake_client.beta.messages.stream.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5-5", f"Got {kwargs['model']}"
    assert kwargs["fallbacks"] == "default", "Opus 5.5 takes the server-side fallback"


def test_director_mature_adds_its_rules_to_the_system_prompt(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message(REPLY))
    director = Director(fake_client, "claude-haiku-5-5", "low")
    director.direct("şelale", Scene())
    plain = fake_client.beta.messages.stream.call_args.kwargs["system"]
    director.mature = True
    director.direct("şelale", Scene())
    mature = fake_client.beta.messages.stream.call_args.kwargs["system"]
    assert "Mature mode is on" not in plain, "Mature rules sent while off"
    assert mature.startswith(plain), "Mature mode dropped the base instructions"
    assert "Mature mode is on" in mature, "Mature rules missing while on"


def test_system_prompt_named_subjects_include_public_figures() -> None:
    prompt = system_prompt()
    assert "well-known real person" in prompt, "Famous people get no reference"
    assert "for real people" not in prompt, "Real people are still left out"


def test_director_direct_valid_reply_returns_direction(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message({**REPLY, "prompt": "  A waterfall.  "}))
    direction = Director(fake_client, "m", "low").direct("şelale", Scene())
    assert direction.message == "Şelale çiziyorum.", f"Got {direction.message!r}"
    assert direction.prompt == "A waterfall.", f"Got {direction.prompt!r}"
    tokens = (direction.input_tokens, direction.output_tokens)
    assert tokens == (1200, 3400), f"Got {tokens}"


def test_director_direct_edit_on_empty_scene_becomes_new_picture(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message({**REPLY, "edit": True}))
    direction = Director(fake_client, "m", "low").direct("şelale", Scene())
    assert direction.edit is False, "Nothing to edit before the first picture"


def test_director_direct_edit_on_painted_scene_is_kept(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message({**REPLY, "edit": True}))
    direction = Director(fake_client, "m", "low").direct("dağlar", _painted_scene())
    assert direction.edit is True, "An edit of an existing picture must stay an edit"


@pytest.mark.parametrize(
    ("reply", "stop_reason", "failure"),
    [
        (REPLY, "refusal", Failure.REFUSED),
        (REPLY, "max_tokens", Failure.TRUNCATED),
        ("not json", "end_turn", Failure.INVALID),
        ({"message": "x", "prompt": "y"}, "end_turn", Failure.INVALID),
        ({"message": "", "prompt": "y", "edit": False}, "end_turn", Failure.INVALID),
    ],
)
def test_director_direct_bad_response_raises_matching_failure(
    fake_client: MagicMock, make_message, set_final_message, reply, stop_reason, failure
) -> None:
    set_final_message(make_message(reply, stop_reason))
    with pytest.raises(DirectorError) as exc:
        Director(fake_client, "m", "low").direct("x", Scene())
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
def test_director_direct_api_error_raises_matching_failure(
    fake_client: MagicMock, error: Exception, failure: Failure
) -> None:
    fake_client.beta.messages.stream.side_effect = error
    with pytest.raises(DirectorError) as exc:
        Director(fake_client, "m", "low").direct("x", Scene())
    assert exc.value.failure is failure, f"Expected {failure}, got {exc.value.failure}"


def test_build_request_first_picture_says_so() -> None:
    text = build_request("  şelale ", Scene())
    assert "<request>şelale</request>" in text, f"Request missing in {text!r}"
    assert "first picture" in text, f"First-picture note missing in {text!r}"


def test_build_request_linked_picture_is_marked() -> None:
    text = build_request("at night", Scene(), linked=True)
    assert "<reference_picture>" in text, f"Linked-picture note missing in {text!r}"
    plain = build_request("at night", Scene())
    assert "<reference_picture>" not in plain, f"Note without a picture in {plain!r}"


def test_director_direct_linked_picture_is_shown_before_the_request(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message(REPLY))
    picture = Image.new("RGB", (2048, 1024), (200, 40, 220))
    Director(fake_client, "m", "low").direct("at night", Scene(), picture)
    messages = fake_client.beta.messages.stream.call_args.kwargs["messages"]
    image, text = messages[0]["content"]
    assert image["type"] == "image", f"Expected the picture first, got {image}"
    assert image["source"]["media_type"] == "image/jpeg", f"Got {image['source']}"
    assert "<reference_picture>" in text["text"], f"Got {text}"


def test_director_direct_linked_picture_is_shrunk_for_claude(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message(REPLY))
    picture = Image.new("RGB", (4000, 2000), (200, 40, 220))
    Director(fake_client, "m", "low").direct("x", Scene(), picture)
    messages = fake_client.beta.messages.stream.call_args.kwargs["messages"]
    data = base64.standard_b64decode(messages[0]["content"][0]["source"]["data"])
    size = Image.open(io.BytesIO(data)).size
    assert max(size) == LINKED_SIDE, (
        f"Expected the long side at {LINKED_SIDE}, got {size}"
    )


def test_build_request_follow_up_includes_history_and_last_prompt() -> None:
    text = build_request("dağlar", _painted_scene())
    assert "1. şelale" in text, f"History missing in {text!r}"
    expected = "<previous_prompt>A waterfall in a canyon.</previous_prompt>"
    assert expected in text, f"Last prompt missing in {text!r}"


def test_director_direct_offers_claude_a_web_search(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message(REPLY))
    Director(fake_client, "claude-haiku-5-5", "low").direct("yunara lol", Scene())
    tools = fake_client.beta.messages.stream.call_args.kwargs["tools"]
    assert [tool["name"] for tool in tools] == ["web_search"], f"Got {tools}"
    assert tools[0]["max_uses"] <= 2, "Searches must stay capped"


def test_director_direct_reads_json_from_the_last_text_block(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    message = make_message(REPLY)
    remark = SimpleNamespace(type="text", text="Let me look that up.")
    search = SimpleNamespace(type="server_tool_use", name="web_search")
    message.content = [remark, search, *message.content]
    set_final_message(message)
    direction = Director(fake_client, "m", "low").direct("yunara lol", Scene())
    assert direction.prompt == "A waterfall.", f"Got {direction.prompt!r}"


def test_director_reply_schema_asks_for_reference_links() -> None:
    field = REPLY_SCHEMA["properties"].get("references", {})
    assert field.get("type") == "array", f"Got {field}"
    assert "references" in REPLY_SCHEMA["required"], "References must be required"


def test_director_direct_keeps_up_to_three_clean_reference_links(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    links = [" https://a.example/1 ", "", "https://b.example/2", "https://c/3", "x"]
    set_final_message(make_message({**REPLY, "references": links}))
    direction = Director(fake_client, "m", "low").direct("yunara lol", Scene())
    expected = ("https://a.example/1", "https://b.example/2", "https://c/3")
    assert direction.references == expected, f"Got {direction.references}"


def test_director_direct_reply_without_references_has_none(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message(REPLY))
    direction = Director(fake_client, "m", "low").direct("şelale", Scene())
    assert direction.references == (), f"Got {direction.references}"


def test_director_direct_reports_serving_model_and_searches(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message(REPLY, searches=2))
    direction = Director(fake_client, "m", "low").direct("yunara lol", Scene())
    got = (direction.model, direction.searches)
    assert got == ("claude-haiku-5-5", 2), f"Got {got}"


def test_director_direct_without_searches_counts_zero(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message(REPLY))
    direction = Director(fake_client, "m", "low").direct("x", Scene())
    assert direction.searches == 0, f"Got {direction.searches}"


def test_director_reply_schema_requires_subject_and_show() -> None:
    required = set(REPLY_SCHEMA["required"])
    assert {"subject", "show"} <= required, f"Got {required}"


def test_director_direct_returns_subject_and_show(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    reply = {**REPLY, "subject": " Yunara League of Legends ", "show": True}
    set_final_message(make_message(reply))
    direction = Director(fake_client, "m", "low").direct("yunara lol", Scene())
    got = (direction.subject, direction.show)
    assert got == ("Yunara League of Legends", True), f"Got {got}"


def test_director_direct_never_shows_when_adding_to_a_picture(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    reply = {**REPLY, "edit": True, "subject": "Yunara", "show": True}
    set_final_message(make_message(reply))
    direction = Director(fake_client, "m", "low").direct("yunara", _painted_scene())
    assert direction.show is False, "An addition must be painted, not shown"


QUESTION = {
    "header": "Subject",
    "question": "What should it show?",
    "multi": False,
    "options": [
        {"label": "A galaxy", "description": "spiral arms"},
        {"label": "A black hole", "description": "a bright disk"},
    ],
}


@pytest.mark.parametrize("ask", [False, True])
def test_director_direct_sends_questions_schema_and_rules_only_when_asking(
    fake_client: MagicMock, make_message, set_final_message, ask: bool
) -> None:
    set_final_message(make_message({**REPLY, "questions": []}))
    Director(fake_client, "claude-haiku-5-5", "low", ask=ask).direct("evren", Scene())
    kwargs = fake_client.beta.messages.stream.call_args.kwargs
    schema = kwargs["output_config"]["format"]["schema"]
    assert (schema is ASK_SCHEMA) is ask, f"ask={ask}: wrong schema"
    has_rules = "Clarifying questions:" in kwargs["system"]
    assert has_rules is ask, f"ask={ask}: rules in system prompt = {has_rules}"


def test_ask_schema_requires_questions_on_top_of_the_reply() -> None:
    assert "questions" in ASK_SCHEMA["required"], "questions must be required"
    assert set(REPLY_SCHEMA["required"]) < set(ASK_SCHEMA["required"]), (
        "Every reply field must stay required"
    )
    assert "questions" not in REPLY_SCHEMA["properties"], "The plain schema is today's"


def test_director_direct_vague_request_returns_its_questions(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    set_final_message(make_message({**REPLY, "questions": [QUESTION]}))
    director = Director(fake_client, "claude-haiku-5-5", "low", ask=True)
    direction = director.direct("evren", Scene())
    expected = (
        Question(
            "Subject",
            "What should it show?",
            False,
            (
                Option("A galaxy", "spiral arms"),
                Option("A black hole", "a bright disk"),
            ),
        ),
    )
    assert direction.questions == expected, f"Got {direction.questions}"


def test_director_direct_keeps_questions_within_the_limits(
    fake_client: MagicMock, make_message, set_final_message
) -> None:
    six = [{"label": f" Option {i} ", "description": " d "} for i in range(6)]
    long = {
        "header": "  A very long header ",
        "question": " Which one? ",
        "multi": True,
        "options": [{"label": "  ", "description": "no label"}, *six],
    }
    no_text = {**QUESTION, "question": "  "}
    one_option = {**QUESTION, "options": QUESTION["options"][:1]}
    no_header = {**QUESTION, "header": ""}
    questions = [no_text, one_option, long, no_header, QUESTION, QUESTION]
    set_final_message(make_message({**REPLY, "questions": questions}))
    director = Director(fake_client, "claude-haiku-5-5", "low", ask=True)
    asked = director.direct("evren", Scene()).questions
    assert len(asked) == 3, f"At most three questions, got {len(asked)}"
    first = asked[0]
    assert first.header == "A very long", f"Header cut to 12, got {first.header!r}"
    assert first.text == "Which one?", f"Text stripped, got {first.text!r}"
    labels = [option.label for option in first.options]
    assert labels == ["Option 0", "Option 1", "Option 2", "Option 3"], f"Got {labels}"
    assert asked[1].header == "Question 2", f"Empty header, got {asked[1].header!r}"


@pytest.mark.parametrize(
    "case", ["off", "add", "linked", "answers", "subject", "references"]
)
def test_director_direct_drops_questions_when_it_should_not_ask(
    fake_client: MagicMock, make_message, set_final_message, case: str
) -> None:
    reply: dict[str, object] = {**REPLY, "questions": [QUESTION]}
    if case == "subject":
        reply["subject"] = "Yunara League of Legends"
    if case == "references":
        reply["references"] = ["https://example.com/yunara"]
    set_final_message(make_message(reply))
    director = Director(fake_client, "claude-haiku-5-5", "low", ask=case != "off")
    scene = _painted_scene() if case == "add" else Scene()
    linked = Image.new("RGB", (4, 4)) if case == "linked" else None
    answers = (Answer("Mood", "Which mood?", ("Calm",)),) if case == "answers" else ()
    direction = director.direct("evren", scene, linked, answers)
    assert direction.questions == (), f"{case}: questions must be dropped"


def test_build_request_lists_the_answers_after_the_request() -> None:
    answers = (
        Answer("Subject", "What should it show?", ("A black hole",)),
        Answer("Mood", "Which moods fit?", ("Calm", "a dying red star")),
    )
    text = build_request("universe", Scene(), answers=answers)
    expected = (
        "<request>universe</request>\n<answers>\n"
        "Subject: What should it show? A black hole\n"
        "Mood: Which moods fit? Calm; a dying red star\n</answers>"
    )
    assert expected in text, f"Answers missing from {text!r}"


def test_build_request_without_answers_ends_with_the_request() -> None:
    text = build_request("universe", Scene())
    assert text.rstrip().endswith("<request>universe</request>"), f"Got {text!r}"


def test_system_prompt_adds_mature_then_question_rules() -> None:
    both = system_prompt(True, True)
    mature_rules = system_prompt(True).removeprefix(system_prompt()).strip()
    assert both.startswith(system_prompt()), "The base prompt comes first"
    mature_at, ask_at = both.index(mature_rules), both.index("Clarifying questions:")
    assert mature_at < ask_at, "mature.md comes before ask.md"
