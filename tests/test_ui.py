from datetime import datetime
from typing import get_args

import pytest
from rich.console import Console
from rich.text import Text

from sepia import ui
from sepia.config import MODELS, Effort, Switch
from sepia.painter import Source
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


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.0, "0s"), (9.99, "9s"), (59.5, "59s"), (60.0, "1m 00s"), (125.4, "2m 05s")],
)
def test_elapsed_whole_seconds_then_minutes(seconds: float, expected: str) -> None:
    assert ui.elapsed(seconds) == expected, f"{seconds}: got {ui.elapsed(seconds)!r}"


def test_words_working_labels_show_the_elapsed_time_and_no_painter() -> None:
    words = ui.Words()
    for key in ("directing", "painting", "looking"):
        label = words(key, elapsed="12s")
        assert label.endswith("· 12s)"), f"{key}: no elapsed time in {label!r}"
        assert "cloudflare" not in label, f"{key}: names a painter in {label!r}"


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


def test_usage_view_session_shows_claude_cost_and_requests() -> None:
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
    ]
    missing = [piece for piece in pieces if piece not in text]
    assert not missing, f"{missing} missing from: {text!r}"


def test_usage_view_leaves_the_pictures_and_their_painters_out() -> None:
    usage = _usage()
    usage.image_searches = 4
    earlier = Earlier(requests=40, pictures=26, cost=0.04)
    all_time = AllTime(since=datetime(2026, 10, 29), total=usage, earlier=earlier)
    text = _view_text(usage, all_time)
    shown = [
        word
        for word in (
            "Pictures",
            "pictures",
            "cloudflare",
            "local GPU",
            "image searches",
        )
        if word in text
    ]
    assert not shown, f"{shown} still shown in: {text!r}"


def test_usage_view_all_time_adds_the_estimate_from_before_tracking() -> None:
    usage = _usage()
    earlier = Earlier(requests=40, pictures=26, cost=0.04)
    all_time = AllTime(since=datetime(2026, 10, 29), total=usage, earlier=earlier)
    text = _view_text(usage, all_time)
    pieces = [
        "all time · since 29 Oct 2026",
        "$0.0684",
        "43 requests",
        "about 40 requests, $0.0400",
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


def test_words_describe_every_model() -> None:
    words = ui.Words()
    missing = [name for name in MODELS if not words(f"model.{name}")]
    assert not missing, f"No description for {missing}"


def test_words_commands_include_model() -> None:
    names = [usage.split()[0] for usage, _ in ui.Words().commands]
    assert "/model" in names, f"Got {names}"


def test_words_describe_every_mature_switch() -> None:
    words = ui.Words()
    missing = [
        switch
        for switch in get_args(Switch)
        if not (words(f"mature.{switch}") and words(f"mature_{switch}"))
    ]
    assert not missing, f"No description or reply for {missing}"


def test_words_commands_include_api_and_local() -> None:
    names = [usage.split()[0] for usage, _ in ui.Words().commands]
    assert {"/api", "/local"} <= set(names), f"Got {names}"


def test_words_name_and_switch_to_every_painter() -> None:
    words = ui.Words()
    missing = [
        source
        for source in get_args(Source)
        if not (words(f"source.{source}") and words(f"painter_{source}"))
    ]
    assert not missing, f"No name or switch reply for {missing}"


def test_words_commands_include_save() -> None:
    names = [usage.split()[0] for usage, _ in ui.Words().commands]
    assert "/save" in names, f"Got {names}"


def test_words_save_replies_fill_in_the_path_and_the_error() -> None:
    words = ui.Words()
    saved = words("saved", path="C:/Pictures/sepia/a.png")
    failed = words("save_failed", error="disk full")
    assert saved == "Saved to C:/Pictures/sepia/a.png", f"Got {saved!r}"
    assert failed == "Could not save the picture: disk full", f"Got {failed!r}"
    assert words("save_empty"), "The empty-scene reply must say something"


def test_words_commands_include_config() -> None:
    names = [usage.split()[0] for usage, _ in ui.Words().commands]
    assert "/config" in names, f"Got {names}"


def test_answers_pads_headers_to_one_width() -> None:
    text = ui.answers([("Subject", "A black hole"), ("Mood", "Calm")]).plain
    expected = "   · Subject  A black hole\n   · Mood     Calm"
    assert text == expected, f"Got {text!r}"
