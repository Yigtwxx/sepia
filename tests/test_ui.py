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


def test_bar_rule_is_an_open_line_across_the_width() -> None:
    rule = ui.bar_rule(12)
    assert rule == "─" * 12, f"Expected a plain 12-column rule, got {rule!r}"


def test_usage_view_shows_claude_cost_and_pictures_by_source() -> None:
    from rich.console import Console

    from sepia.usage import Usage

    usage = Usage(requests=3, input_tokens=64_200, output_tokens=3_100, searches=2)
    usage.input_cost, usage.output_cost, usage.search_cost = 0.0064, 0.0020, 0.02
    usage.pictures = {"api": 5, "local": 2}
    usage.paint_seconds = 58.3
    usage.referenced = 3
    console = Console(record=True, width=90)
    console.print(ui.usage_view(ui.Words(), usage, "claude-haiku-5-5", 90))
    text = console.export_text()
    pieces = [
        "haiku-5-5",
        "$0.0284",
        "64.2k",
        "3.1k",
        "2 web searches",
        "3 requests",
        "7 pictures",
        "58.3s",
        "pollinations 5",
        "local GPU 2",
        "3 after a reference picture",
        "█",
    ]
    missing = [piece for piece in pieces if piece not in text]
    assert not missing, f"{missing} missing from: {text!r}"


def test_words_commands_include_usage() -> None:
    names = [usage.split()[0] for usage, _ in ui.Words().commands]
    assert "/usage" in names, f"Got {names}"
