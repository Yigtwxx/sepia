import os
from pathlib import Path

import pytest

from sepia import config
from sepia.config import (
    ConfigError,
    Settings,
    api_key,
    load_settings,
    pollinations_key,
    save_api_key,
)


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


@pytest.mark.parametrize("name", ["SEPIA_EFFORT", "SEPIA_STYLE", "SEPIA_CHARSET"])
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


def test_save_api_key_replaces_old_key_and_keeps_other_lines(tmp_path: Path) -> None:
    target = tmp_path / "sepia" / ".env"
    save_api_key("sk-old", target)
    target.write_text(target.read_text() + "SEPIA_STYLE=fill\n")
    save_api_key("sk-new", target)
    lines = target.read_text().splitlines()
    assert lines == ["SEPIA_STYLE=fill", "ANTHROPIC_API_KEY=sk-new"], f"Got {lines}"


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
    [({}, None), ({"POLLINATIONS_KEY": " "}, None), ({"POLLINATIONS_KEY": "pk"}, "pk")],
)
def test_pollinations_key_is_optional(environ: dict[str, str], expected) -> None:
    assert pollinations_key(environ) == expected, f"Expected {expected!r}"
