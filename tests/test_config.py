import os
from pathlib import Path

import pytest

from sepia import config
from sepia.config import (
    Choices,
    ConfigError,
    Settings,
    api_key,
    cloudflare_key,
    load_choices,
    load_settings,
    remember,
    save_keys,
    search_key,
)


def test_models_cover_each_family_once_and_include_the_default() -> None:
    ids = list(config.MODELS.values())
    assert list(config.MODELS) == ["haiku", "sonnet", "opus", "fable"], (
        f"Got {list(config.MODELS)}"
    )
    assert len(set(ids)) == len(ids), f"Two names share a model: {ids}"
    assert config.DEFAULT_MODEL in ids, f"{config.DEFAULT_MODEL} has no /model name"


def test_load_settings_empty_environment_uses_defaults() -> None:
    settings = load_settings({})
    assert settings == Settings(), f"Expected defaults, got {settings}"


def test_load_settings_overrides_are_normalized() -> None:
    environ = {"SEPIA_MODEL": " claude-sonnet-5-5 ", "SEPIA_EFFORT": "HIGH"}
    settings = load_settings(
        environ | {"SEPIA_STYLE": "fill", "SEPIA_CHARSET": "symbols"}
    )
    expected = Settings(
        model="claude-sonnet-5-5", effort="high", style="fill", charset="symbols"
    )
    assert settings == expected, f"Expected {expected}, got {settings}"


@pytest.mark.parametrize(("value", "expected"), [("on", True), (" OFF ", False)])
def test_load_settings_mature_switch_sets_mature(value: str, expected: bool) -> None:
    settings = load_settings({"SEPIA_MATURE": value})
    assert settings.mature is expected, f"SEPIA_MATURE={value!r}: got {settings}"


@pytest.mark.parametrize(
    ("environ", "expected"),
    [({}, True), ({"SEPIA_UPDATE_CHECK": " OFF "}, False)],
)
def test_load_settings_update_check_switch_sets_the_notice(
    environ: dict[str, str], expected: bool
) -> None:
    settings = load_settings(environ)
    assert settings.update_check is expected, f"{environ}: got {settings}"


@pytest.mark.parametrize(
    "name",
    [
        "SEPIA_EFFORT",
        "SEPIA_STYLE",
        "SEPIA_CHARSET",
        "SEPIA_MATURE",
        "SEPIA_ASK",
        "SEPIA_UPDATE_CHECK",
    ],
)
def test_load_settings_unknown_choice_raises_config_error(name: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_settings({name: "loud"})


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, None),
        ({"ANTHROPIC_API_KEY": "  "}, None),
        ({"ANTHROPIC_API_KEY": " sk-1 "}, "sk-1"),
    ],
)
def test_api_key_blank_values_count_as_missing(
    environ: dict[str, str], expected: str | None
) -> None:
    assert api_key(environ) == expected, f"Expected {expected!r}"


def test_save_keys_replaces_the_given_keys_and_keeps_other_lines(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sepia" / ".env"
    target.parent.mkdir()
    target.write_text("ANTHROPIC_API_KEY=sk-a\nBRAVE_SEARCH_API_KEY=old\n")
    save_keys(
        {"BRAVE_SEARCH_API_KEY": " new ", "CLOUDFLARE_ACCOUNT_ID": "acct"}, target
    )
    lines = target.read_text().splitlines()
    expected = [
        "ANTHROPIC_API_KEY=sk-a",
        "BRAVE_SEARCH_API_KEY=new",
        "CLOUDFLARE_ACCOUNT_ID=acct",
    ]
    assert lines == expected, f"Got {lines}"


def test_load_environment_never_overrides_existing_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-file\nSEPIA_STYLE=fill\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")
    monkeypatch.delenv("SEPIA_STYLE", raising=False)
    monkeypatch.setattr(config, "user_env_file", lambda: tmp_path / "missing.env")
    config.load_environment(cwd=tmp_path)
    assert os.environ["ANTHROPIC_API_KEY"] == "from-shell", "Shell value was replaced"
    assert os.environ["SEPIA_STYLE"] == "fill", "Value from .env was not loaded"


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, None),
        ({"CLOUDFLARE_ACCOUNT_ID": " ", "CLOUDFLARE_API_TOKEN": " "}, None),
        (
            {"CLOUDFLARE_ACCOUNT_ID": " acc ", "CLOUDFLARE_API_TOKEN": " tok "},
            ("acc", "tok"),
        ),
    ],
)
def test_cloudflare_key_is_optional_and_trimmed(
    environ: dict[str, str], expected: tuple[str, str] | None
) -> None:
    assert cloudflare_key(environ) == expected, f"Expected {expected!r}"


@pytest.mark.parametrize(
    ("given", "missing"),
    [
        ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"),
        ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"),
    ],
)
def test_cloudflare_key_only_one_of_the_two_raises_config_error(
    given: str, missing: str
) -> None:
    with pytest.raises(ConfigError, match=f"^{missing} is not set"):
        cloudflare_key({given: "x"})


@pytest.mark.parametrize("content", [None, "not json", '{"effort": "loud"}'])
def test_load_choices_missing_or_unreadable_file_gives_no_choices(
    tmp_path: Path, content: str | None
) -> None:
    path = tmp_path / "choices.json"
    if content is not None:
        path.write_text(content)
    assert load_choices(path) == Choices(), f"{content!r} must give no choices"


def test_remember_keeps_earlier_choices_and_adds_the_new_one(tmp_path: Path) -> None:
    path = tmp_path / "sepia" / "choices.json"
    remember(path, mature=True)
    remember(path, painter="local")
    expected = Choices(mature=True, painter="local")
    assert load_choices(path) == expected, f"Got {load_choices(path)}"


def test_load_settings_choices_win_over_environment_and_defaults() -> None:
    chosen = Choices(effort="low", mature=True, painter="local")
    settings = load_settings({"SEPIA_EFFORT": "max", "SEPIA_STYLE": "fill"}, chosen)
    expected = Settings(effort="low", style="fill", mature=True, painter="local")
    assert settings == expected, f"Expected {expected}, got {settings}"


def test_load_settings_without_choices_paints_with_the_api() -> None:
    assert load_settings({}).painter == "api", "The API is the starting painter"


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, None),
        ({"BRAVE_SEARCH_API_KEY": " "}, None),
        ({"BRAVE_SEARCH_API_KEY": "bk"}, "bk"),
    ],
)
def test_search_key_is_optional(environ: dict[str, str], expected) -> None:
    assert search_key(environ) == expected, f"Expected {expected!r}"


@pytest.mark.parametrize(
    ("environ", "expected"),
    [({}, True), ({"SEPIA_ASK": " OFF "}, False), ({"SEPIA_ASK": "on"}, True)],
)
def test_load_settings_ask_switch_sets_clarifying_questions(
    environ: dict[str, str], expected: bool
) -> None:
    settings = load_settings(environ)
    assert settings.ask is expected, f"{environ}: got {settings}"


def test_load_settings_kept_ask_choice_wins_over_the_environment() -> None:
    settings = load_settings({"SEPIA_ASK": "on"}, Choices(ask=False))
    assert settings.ask is False, f"The kept choice must win, got {settings}"
