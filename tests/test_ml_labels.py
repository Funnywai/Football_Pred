from app.ml.labels import (
    handicap_label,
    is_whole_or_half,
    label_1x2,
    parse_handicap_line,
)


def test_label_1x2() -> None:
    assert label_1x2(2, 1) == "H"
    assert label_1x2(1, 1) == "D"
    assert label_1x2(0, 3) == "A"


def test_parse_handicap_line() -> None:
    assert parse_handicap_line("-1") == -1.0
    assert parse_handicap_line("+0.5") == 0.5
    assert parse_handicap_line("0") == 0.0
    assert parse_handicap_line("-0.25") == -0.25
    assert parse_handicap_line(None) is None
    assert parse_handicap_line("") is None
    assert parse_handicap_line("n/a") is None


def test_is_whole_or_half() -> None:
    assert is_whole_or_half(0.0)
    assert is_whole_or_half(-1.0)
    assert is_whole_or_half(0.5)
    assert is_whole_or_half(-1.5)
    assert not is_whole_or_half(-0.25)
    assert not is_whole_or_half(0.75)


def test_handicap_label() -> None:
    assert handicap_label(2, 1, -0.5) == "H"
    assert handicap_label(1, 1, -0.5) == "A"
    assert handicap_label(3, 1, -1.0) == "H"
    assert handicap_label(2, 1, -1.0) is None  # push on a whole line
    assert handicap_label(2, 1, -1.25) is None  # quarter line skipped in v1
