from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from packages.domain.enums import BetStatus, MarketType, Side
from packages.domain.errors import InvalidConditionRaw, SettlementInputError
from packages.domain.markets import parse_condition_raw, validate_side

PAYOUT_STEP = Decimal("0.10")  # normalized money precision
PAYOUT_INCREMENT = Decimal("0.1")  # actual rounding unit: nearest HK$0.10
PAYOUT_ROUNDING = ROUND_HALF_UP
MIN_ODDS = Decimal("1.01")


class _HalfOutcome(StrEnum):
    WIN = "win"
    LOSE = "lose"
    PUSH = "push"


@dataclass(frozen=True)
class SettlementOutcome:
    result_status: BetStatus
    payout: Decimal
    payout_unrounded: Decimal
    void_reason: str | None = None


def round_payout(amount: Decimal) -> Decimal:
    rounded = amount.quantize(PAYOUT_INCREMENT, rounding=PAYOUT_ROUNDING)
    return rounded.quantize(PAYOUT_STEP, rounding=PAYOUT_ROUNDING)


def _validate_common(odds: Decimal, stake: Decimal) -> None:
    if odds < MIN_ODDS:
        raise SettlementInputError(f"odds must be at least {MIN_ODDS}, got {odds}")
    if stake <= Decimal(0):
        raise SettlementInputError(f"stake must be positive, got {stake}")


def _validate_goals(home_goals_90: int, away_goals_90: int) -> None:
    if home_goals_90 < 0 or away_goals_90 < 0:
        raise SettlementInputError("goals cannot be negative")


def _payout_for_half(half_stake: Decimal, odds: Decimal, outcome: _HalfOutcome) -> Decimal:
    if outcome is _HalfOutcome.WIN:
        return half_stake * odds
    if outcome is _HalfOutcome.PUSH:
        return half_stake
    return Decimal(0)


def _single_status(outcome: _HalfOutcome) -> BetStatus:
    if outcome is _HalfOutcome.WIN:
        return BetStatus.WON
    if outcome is _HalfOutcome.PUSH:
        return BetStatus.PUSH
    return BetStatus.LOST


def _split_status(outcomes: tuple[_HalfOutcome, ...]) -> BetStatus:
    ordered = sorted(outcomes, key=lambda item: item.value)
    pair = (ordered[0], ordered[1])
    if pair == (_HalfOutcome.WIN, _HalfOutcome.WIN):
        return BetStatus.WON
    if pair == (_HalfOutcome.LOSE, _HalfOutcome.LOSE):
        return BetStatus.LOST
    if pair == (_HalfOutcome.PUSH, _HalfOutcome.PUSH):
        return BetStatus.PUSH
    if pair == (_HalfOutcome.PUSH, _HalfOutcome.WIN):
        return BetStatus.HALF_WON_HALF_PUSH
    if pair == (_HalfOutcome.LOSE, _HalfOutcome.PUSH):
        return BetStatus.HALF_LOST_HALF_PUSH
    raise SettlementInputError(f"unsupported half outcome pair {pair}")


def _build_outcome(
    stake: Decimal,
    odds: Decimal,
    half_outcomes: tuple[_HalfOutcome, ...],
) -> SettlementOutcome:
    if len(half_outcomes) == 1:
        outcome = half_outcomes[0]
        if outcome is _HalfOutcome.WIN:
            unrounded = stake * odds
        elif outcome is _HalfOutcome.PUSH:
            unrounded = stake
        else:
            unrounded = Decimal(0)
        return SettlementOutcome(
            result_status=_single_status(outcome),
            payout=round_payout(unrounded),
            payout_unrounded=unrounded,
        )
    half_stake = stake / Decimal(2)
    unrounded = sum(
        (_payout_for_half(half_stake, odds, outcome) for outcome in half_outcomes),
        Decimal(0),
    )
    return SettlementOutcome(
        result_status=_split_status(half_outcomes),
        payout=round_payout(unrounded),
        payout_unrounded=unrounded,
    )


def _handicap_half(home_goals_90: int, away_goals_90: int, handicap: Decimal) -> _HalfOutcome:
    adjusted = Decimal(home_goals_90 - away_goals_90) + handicap
    if adjusted > 0:
        return _HalfOutcome.WIN
    if adjusted < 0:
        return _HalfOutcome.LOSE
    return _HalfOutcome.PUSH


def _total_half(selection: Side, total_goals: int, line: Decimal) -> _HalfOutcome:
    if total_goals == line:
        return _HalfOutcome.PUSH
    over_wins = total_goals > line
    if selection is Side.H:
        return _HalfOutcome.WIN if over_wins else _HalfOutcome.LOSE
    return _HalfOutcome.WIN if not over_wins else _HalfOutcome.LOSE


def settle_had(
    selection: Side,
    home_goals_90: int,
    away_goals_90: int,
    odds: Decimal,
    stake: Decimal,
) -> SettlementOutcome:
    _validate_common(odds, stake)
    _validate_goals(home_goals_90, away_goals_90)
    validate_side(MarketType.HAD, selection)
    if home_goals_90 > away_goals_90:
        winner = Side.H
    elif home_goals_90 < away_goals_90:
        winner = Side.A
    else:
        winner = Side.D
    result = _HalfOutcome.WIN if selection is winner else _HalfOutcome.LOSE
    return _build_outcome(stake, odds, (result,))


def settle_hdc(
    selection: Side,
    home_goals_90: int,
    away_goals_90: int,
    condition_raw: str,
    odds: Decimal,
    stake: Decimal,
) -> SettlementOutcome:
    _validate_common(odds, stake)
    _validate_goals(home_goals_90, away_goals_90)
    validate_side(MarketType.HDC, selection)
    try:
        halves = parse_condition_raw(condition_raw)
    except InvalidConditionRaw as exc:
        raise SettlementInputError(f"invalid HDC condition {condition_raw}") from exc
    outcomes: list[_HalfOutcome] = []
    for handicap in halves:
        home_outcome = _handicap_half(home_goals_90, away_goals_90, handicap)
        if selection is Side.H:
            outcomes.append(home_outcome)
        elif home_outcome is _HalfOutcome.WIN:
            outcomes.append(_HalfOutcome.LOSE)
        elif home_outcome is _HalfOutcome.LOSE:
            outcomes.append(_HalfOutcome.WIN)
        else:
            outcomes.append(_HalfOutcome.PUSH)
    return _build_outcome(stake, odds, tuple(outcomes))


def settle_hil(
    selection: Side,
    home_goals_90: int,
    away_goals_90: int,
    condition_raw: str,
    odds: Decimal,
    stake: Decimal,
) -> SettlementOutcome:
    _validate_common(odds, stake)
    _validate_goals(home_goals_90, away_goals_90)
    validate_side(MarketType.HIL, selection)
    parts = condition_raw.strip().split("/")
    if any(part.strip().startswith(("+", "-")) for part in parts):
        raise SettlementInputError(f"HIL condition must be unsigned, got {condition_raw}")
    try:
        halves = parse_condition_raw(condition_raw)
    except InvalidConditionRaw as exc:
        raise SettlementInputError(f"invalid HIL condition {condition_raw}") from exc
    total_goals = home_goals_90 + away_goals_90
    outcomes = tuple(_total_half(selection, total_goals, line) for line in halves)
    return _build_outcome(stake, odds, outcomes)


def settle_void(stake: Decimal) -> SettlementOutcome:
    if stake <= Decimal(0):
        raise SettlementInputError(f"stake must be positive, got {stake}")
    return SettlementOutcome(
        result_status=BetStatus.VOID,
        payout=round_payout(stake),
        payout_unrounded=stake,
        void_reason="hkjc_refund_pool",
    )


def _is_supported_market(market: object) -> bool:
    return isinstance(market, MarketType) and market in (
        MarketType.HAD,
        MarketType.HDC,
        MarketType.HIL,
    )


def settle_market(
    market: MarketType,
    selection: Side,
    home_goals_90: int,
    away_goals_90: int,
    condition_raw: str,
    odds: Decimal,
    stake: Decimal,
) -> SettlementOutcome:
    if not _is_supported_market(market):
        raise SettlementInputError(f"unsupported market {market}")
    if market is MarketType.HAD:
        return settle_had(selection, home_goals_90, away_goals_90, odds, stake)
    if market is MarketType.HDC:
        return settle_hdc(selection, home_goals_90, away_goals_90, condition_raw, odds, stake)
    return settle_hil(selection, home_goals_90, away_goals_90, condition_raw, odds, stake)
