from sepia import ui


def test_wordmark_is_compact_and_uses_the_band_colors() -> None:
    mark = ui.wordmark()
    lines = mark.plain.split("\n")
    assert len(lines) == 6, f"Expected the six ANSI Shadow rows, got {len(lines)}"
    assert {len(line) for line in lines} == {35}, "Every row must be 35 columns"
    styles = " ".join(str(span.style) for span in mark.spans)
    assert ui.BANDS[0] in styles and ui.BANDS[-1] in styles, "Gradient ends missing"


def test_words_format_values_into_strings() -> None:
    text = ui.Words()("style_set", style="ink", charset="classic")
    assert text == "Style: ink · charset: classic", f"Got {text!r}"


def test_words_commands_include_clear_and_exit() -> None:
    names = [usage.split()[0] for usage, _ in ui.Words().commands]
    assert {"/clear", "/exit"} <= set(names), f"Got {names}"


def test_reply_marks_failures_in_the_warning_color() -> None:
    styles = " ".join(str(s.style) for s in ui.reply("x", failed=True).spans)
    assert ui.WARN in styles, f"Failure not highlighted: {styles}"
