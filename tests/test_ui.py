from datetime import datetime
from typing import get_args

from rich.console import Console
from rich.text import Text

from sepia import ui
from sepia.config import Effort, Switch
from sepia.usage import AllTime, Earlier, Usage


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


def _usage() -> Usage:
    usage = Usage(requests=3, input_tokens=64_200, output_tokens=3_100, searches=2)
    usage.input_cost, usage.output_cost, usage.search_cost = 0.0064, 0.0020, 0.02
    usage.pictures = {"api": 5, "local": 2}
    usage.paint_seconds = 58.3
    usage.referenced = 3
    return usage


def _view_text(session: Usage, all_time: AllTime) -> str:
    console = Console(record=True, width=120)
    view = ui.usage_view(ui.Words(), session, all_time, "claude-haiku-5-5", 120)
    console.print(view)
    return console.export_text()


def _cells(bar: Text, style: str) -> int:
    """How many cells of `bar` are drawn in `style`."""
    return sum(span.end - span.start for span in bar.spans if span.style == style)


def test_usage_view_session_shows_claude_cost_and_pictures_by_source() -> None:
    usage = _usage()
    text = _view_text(usage, AllTime(since=datetime(2026, 10, 29), total=usage))
    pieces = [
        "this session",
        "haiku-5-5",
        "$0.0284",
        "64.2k",
        "3.1k",
        "2 web searches",
        "3 requests",
        "7 pictures · 58.3s",
        "pollinations 5",
        "local GPU 2",
        "3 after a reference picture",
    ]
    missing = [piece for piece in pieces if piece not in text]
    assert not missing, f"{missing} missing from: {text!r}"


def test_usage_view_all_time_adds_the_estimate_from_before_tracking() -> None:
    usage = _usage()
    earlier = Earlier(requests=40, pictures=26, cost=0.04)
    all_time = AllTime(since=datetime(2026, 10, 29), total=usage, earlier=earlier)
    text = _view_text(usage, all_time)
    pieces = [
        "all time · since 29 Oct 2026",
        "$0.0684",
        "43 requests",
        "33 pictures",
        "about 40 requests, $0.0400",
        "about 26 pictures",
    ]
    missing = [piece for piece in pieces if piece not in text]
    assert not missing, f"{missing} missing from: {text!r}"


def test_usage_view_without_earlier_use_hides_the_estimate() -> None:
    usage = _usage()
    text = _view_text(usage, AllTime(since=datetime(2026, 10, 29), total=usage))
    assert "before tracking" not in text, f"Nothing to estimate, got: {text!r}"


def test_bar_without_use_is_all_gray_track() -> None:
    bar = ui._bar([(0.0, ui.ACCENT)], 20, "$0")
    assert _cells(bar, ui.TRACK) == 20, f"Expected 20 gray cells in {bar.spans}"


def test_bar_equal_thirds_fill_the_whole_bar() -> None:
    parts = [(1.0, ui.ACCENT), (1.0, ui.BANDS[3]), (1.0, ui.BANDS[4])]
    bar = ui._bar(parts, 40, "x")
    colored = sum(_cells(bar, color) for _, color in parts)
    assert (colored, _cells(bar, ui.TRACK)) == (40, 0), f"Got {bar.spans}"


def test_bar_against_a_whole_colors_only_its_share() -> None:
    bar = ui._bar([(1.0, ui.ACCENT)], 40, "x", whole=4.0)
    got = (_cells(bar, ui.ACCENT), _cells(bar, ui.TRACK))
    assert got == (10, 30), f"Expected a quarter colored, got {got}"


def test_bar_tiny_share_still_shows_one_cell() -> None:
    bar = ui._bar([(0.001, ui.ACCENT)], 40, "x", whole=100.0)
    assert _cells(bar, ui.ACCENT) == 1, f"Any use must show, got {bar.spans}"


def test_bar_part_larger_than_whole_fills_the_bar() -> None:
    bar = ui._bar([(5.0, ui.ACCENT)], 40, "x", whole=1.0)
    assert _cells(bar, ui.ACCENT) == 40, f"Expected a full bar, got {bar.spans}"


def test_words_commands_include_usage() -> None:
    names = [usage.split()[0] for usage, _ in ui.Words().commands]
    assert "/usage" in names, f"Got {names}"


def test_words_describe_every_effort_level() -> None:
    words = ui.Words()
    missing = [level for level in get_args(Effort) if not words(f"effort.{level}")]
    assert not missing, f"No description for {missing}"


def test_words_describe_every_mature_switch() -> None:
    words = ui.Words()
    missing = [
        switch
        for switch in get_args(Switch)
        if not (words(f"mature.{switch}") and words(f"mature_{switch}"))
    ]
    assert not missing, f"No description or reply for {missing}"


def test_usage_view_lists_image_searches_once_there_are_some() -> None:
    usage = _usage()
    usage.image_searches = 4
    text = _view_text(usage, AllTime(since=datetime(2026, 10, 29), total=usage))
    assert "4 image searches" in text, f"Image searches missing from: {text!r}"
