from sepia.chatbar import BAR_ROWS, BottomBar


def _bar(rows: int = 30) -> tuple[BottomBar, list[str]]:
    written: list[str] = []
    return BottomBar(written.append, lambda: rows), written


def test_bottom_bar_start_keeps_the_last_rows_out_of_the_scroll_region() -> None:
    bar, written = _bar(rows=30)
    bar.start()
    expected = f"\x1b[1;{30 - BAR_ROWS}r"
    assert written == [expected], f"Expected {expected!r}, got {written}"


def test_bottom_bar_to_bar_saves_transcript_and_moves_below_region() -> None:
    bar, written = _bar(rows=30)
    bar.to_bar()
    output = "".join(written)
    assert output.startswith("\x1b7"), f"Transcript position not saved: {output!r}"
    assert output.endswith(f"\x1b[{30 - BAR_ROWS + 1};1H"), f"Wrong row: {output!r}"


def test_bottom_bar_to_transcript_restores_the_saved_position() -> None:
    bar, written = _bar()
    bar.to_transcript()
    assert written == ["\x1b8"], f"Expected a cursor restore, got {written}"


def test_bottom_bar_stop_resets_region_and_clears_the_bar_rows() -> None:
    bar, written = _bar(rows=24)
    bar.stop()
    output = "".join(written)
    assert output.startswith("\x1b[r"), f"Region not reset: {output!r}"
    top = 24 - BAR_ROWS + 1
    assert output.endswith(f"\x1b[{top};1H\x1b[J"), f"Rows not cleared: {output!r}"


def test_bottom_bar_tiny_window_never_makes_an_empty_region() -> None:
    bar, written = _bar(rows=2)
    bar.start()
    assert written == ["\x1b[1;1r"], f"Region must keep at least one row: {written}"


def test_bottom_bar_hold_draws_each_row_on_the_bar_rows() -> None:
    bar, written = _bar(rows=30)
    bar.hold(["a", "b", "c", "d"])
    top = 30 - BAR_ROWS + 1
    expected = [f"\x1b[{top + i};1H\x1b[2K{row}" for i, row in enumerate("abcd")]
    assert written == expected, f"Expected {expected}, got {written}"


def test_bottom_bar_redraw_repeats_the_held_rows_around_a_cursor_save() -> None:
    bar, written = _bar(rows=30)
    bar.hold(["a", "b"])
    written.clear()
    bar.redraw()
    top = 30 - BAR_ROWS + 1
    expected = ["7"] + [f"[{top + i};1H[2K{row}" for i, row in enumerate("ab")]
    expected.append("8")
    assert written == expected, f"Expected {expected}, got {written}"


def test_bottom_bar_redraw_before_any_hold_writes_nothing() -> None:
    bar, written = _bar()
    bar.redraw()
    assert written == [], f"Nothing was held, yet wrote {written}"
