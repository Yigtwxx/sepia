import pytest

from sepia.mouse import MouseParser


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        (["\x1b[<35;10;5M"], (9, 4)),
        (["\x1b[<35;1;1M\x1b[<35;20;8M"], (19, 7)),
        (["\x1b[<35;3", ";4M"], (2, 3)),
        (["hello"], None),
    ],
)
def test_mouse_parser_reports_the_latest_cell(chunks, expected) -> None:
    parser = MouseParser()
    results = [parser.feed(chunk) for chunk in chunks]
    assert results[-1] == expected, f"{chunks!r}: expected {expected}, got {results}"
