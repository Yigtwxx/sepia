import pytest

from sepia.keys import KEYS, ask_values, is_set, key_named


def _asker(typed: dict[str, str]):
    """Answers each prompt from `typed`, by variable name; records what was asked."""
    asked: list[str] = []

    def ask(variable: str) -> str:
        asked.append(variable)
        return typed.get(variable, "")

    return ask, asked


def test_keys_are_anthropic_then_cloudflare() -> None:
    names = [key.name for key in KEYS]
    assert names == ["anthropic", "cloudflare"], f"Got {names}"


def test_ask_values_cloudflare_asks_id_then_token() -> None:
    ask, asked = _asker({"CLOUDFLARE_ACCOUNT_ID": "acct", "CLOUDFLARE_API_TOKEN": "t"})
    values = ask_values(key_named("cloudflare"), ask)
    assert values == {"CLOUDFLARE_ACCOUNT_ID": "acct", "CLOUDFLARE_API_TOKEN": "t"}, (
        f"Got {values}"
    )
    assert asked == ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"], f"Got {asked}"


def test_ask_values_skipped_key_gives_nothing() -> None:
    ask, _ = _asker({})
    assert ask_values(key_named("anthropic"), ask) == {}, "Enter alone skips it"


def test_ask_values_half_of_cloudflare_gives_nothing() -> None:
    ask, asked = _asker({"CLOUDFLARE_ACCOUNT_ID": "acct"})
    values = ask_values(key_named("cloudflare"), ask)
    assert values == {}, f"Cloudflare needs both its ID and token, got {values}"
    assert asked == ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"], f"Got {asked}"


def test_ask_values_skipped_id_does_not_ask_for_the_token() -> None:
    ask, asked = _asker({})
    ask_values(key_named("cloudflare"), ask)
    assert asked == ["CLOUDFLARE_ACCOUNT_ID"], f"Got {asked}"


def test_ask_values_strips_spaces_around_a_pasted_key() -> None:
    ask, _ = _asker({"ANTHROPIC_API_KEY": "  sk-1 \n"})
    values = ask_values(key_named("anthropic"), ask)
    assert values == {"ANTHROPIC_API_KEY": "sk-1"}, f"Got {values}"


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"CLOUDFLARE_ACCOUNT_ID": "a", "CLOUDFLARE_API_TOKEN": "t"}, True),
        ({"CLOUDFLARE_ACCOUNT_ID": "a"}, False),
        ({"CLOUDFLARE_ACCOUNT_ID": " ", "CLOUDFLARE_API_TOKEN": "t"}, False),
        ({}, False),
    ],
)
def test_is_set_needs_every_variable_of_the_key(
    environ: dict[str, str], expected: bool
) -> None:
    result = is_set(key_named("cloudflare"), environ)
    assert result is expected, f"{environ}: expected {expected}, got {result}"


def test_key_named_unknown_name_raises_key_error() -> None:
    with pytest.raises(KeyError):
        key_named("brave")
