from decimal import Decimal

import pytest

from packages.domain.enums import MarketType, Side
from packages.domain.errors import InvalidConditionRaw, UnsupportedMarket
from packages.domain.markets import (
    canonical_line_key,
    is_split_line,
    parse_condition_raw,
    validate_side,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.0", (Decimal("0.0"),)),
        ("+0.5", (Decimal("+0.5"),)),
        ("-1", (Decimal(-1),)),
        ("1.0/1.5", (Decimal("1.0"), Decimal("1.5"))),
        ("-0.25/0", (Decimal("-0.25"), Decimal(0))),
        (" 2.5 ", (Decimal("2.5"),)),
    ],
)
def test_parse_condition_raw_accepts_valid_lines(raw, expected):
    assert parse_condition_raw(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "1/2/3", "1.0//1.5", "1,5", "1.0/", "/1.0"])
def test_parse_condition_raw_rejects_invalid_lines(raw):
    with pytest.raises(InvalidConditionRaw):
        parse_condition_raw(raw)


def test_split_line_detection():
    assert is_split_line(parse_condition_raw("1.0/1.5")) is True
    assert is_split_line(parse_condition_raw("1.5")) is False


def test_line_key_preserves_source_condition_string():
    assert canonical_line_key(" 1.0/1.5 ") == "1.0/1.5"


def test_validate_side_enforces_market_outcomes():
    validate_side(MarketType.HAD, Side.D)
    validate_side(MarketType.HDC, Side.A)
    validate_side(MarketType.HIL, Side.L)
    with pytest.raises(UnsupportedMarket):
        validate_side(MarketType.HAD, Side.L)
    with pytest.raises(UnsupportedMarket):
        validate_side(MarketType.HIL, Side.D)
