import re
from decimal import Decimal

from packages.domain.enums import MarketType, Side
from packages.domain.errors import InvalidConditionRaw, UnsupportedMarket

CONDITION_RAW_PATTERN = re.compile(r"^[+-]?\d+(\.\d+)?(/[+-]?\d+(\.\d+)?)?$")
MAX_HALVES = 2

_ALLOWED_SIDES: dict[MarketType, set[Side]] = {
    MarketType.HAD: {Side.H, Side.D, Side.A},
    MarketType.HDC: {Side.H, Side.A},
    MarketType.HIL: {Side.H, Side.L},
}


def parse_condition_raw(raw: str) -> tuple[Decimal, ...]:
    candidate = raw.strip()
    if not CONDITION_RAW_PATTERN.fullmatch(candidate):
        raise InvalidConditionRaw(raw)
    halves = tuple(Decimal(part) for part in candidate.split("/"))
    if len(halves) == 0 or len(halves) > MAX_HALVES:
        raise InvalidConditionRaw(raw)
    return halves


def canonical_line_key(raw: str) -> str:
    _ = parse_condition_raw(raw)
    return raw.strip()


def is_split_line(halves: tuple[Decimal, ...]) -> bool:
    return len(halves) == MAX_HALVES


def validate_side(market: MarketType, side: Side) -> None:
    allowed = _ALLOWED_SIDES.get(market)
    if allowed is None or side not in allowed:
        raise UnsupportedMarket(f"{side.value} is not a valid outcome for {market.value}")
