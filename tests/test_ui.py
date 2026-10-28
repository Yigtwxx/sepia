import pytest

from sepia import ui


def test_wordmark_is_compact_and_uses_the_band_colors() -> None:
    mark = ui.wordmark()
    lines = mark.plain.split("\n")
    assert len(lines) == 6, f"Expected the six ANSI Shadow rows, got {len(lines)}"
    assert {len(line) for line in lines} == {35}, "Every row must be 35 columns"
    styles = " ".join(str(span.style) for span in mark.spans)
    assert ui.BANDS[0] in styles and ui.BANDS[-1] in styles, "Gradient ends missing"


@pytest.mark.parametrize("language", ["en", "tr"])
def test_strings_cover_the_same_keys_in_every_language(language: str) -> None:
    missing = set(ui.STRINGS["en"]) ^ set(ui.STRINGS[language])
    assert not missing, f"{language} is out of sync: {missing}"


def test_words_format_values_into_strings() -> None:
    words = ui.Words("en")
    text = words("style_set", style="ink", charset="classic")
    assert text == "Style: ink · charset: classic", f"Got {text!r}"


@pytest.mark.parametrize(
    ("forced", "expected"), [("tr", "tr"), ("EN", "en"), ("de", None)]
)
def test_detect_language_honours_sepia_lang(
    monkeypatch: pytest.MonkeyPatch, forced: str, expected: str | None
) -> None:
    monkeypatch.setenv("SEPIA_LANG", forced)
    language = ui.detect_language()
    if expected is None:
        assert language in ("en", "tr"), f"Unknown value must fall back, got {language}"
    else:
        assert language == expected, f"Expected {expected}, got {language}"


def test_reply_marks_failures_in_the_warning_color() -> None:
    styles = " ".join(str(s.style) for s in ui.reply("x", failed=True).spans)
    assert ui.WARN in styles, f"Failure not highlighted: {styles}"
