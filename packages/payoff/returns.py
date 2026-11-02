from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum

from packages.domain.enums import MarketType, Side
from packages.domain.errors import InvalidConditionRaw, SettlementInputError
from packages.domain.markets import parse_condition_raw, validate_side

MIN_ODDS = Decimal("1.01")
DISTRIBUTION_TOLERANCE = Decimal("1e-6")


class ReturnOutcome(StrEnum):
    WIN = "win"
    HALF_WIN_HALF_PUSH = "half_win_half_push"
    PUSH = "push"
    HALF_LOSE_HALF_PUSH = "half_lose_half_push"
    LOSS = "loss"


ReturnDistribution = Mapping[ReturnOutcome, Decimal]
Score = tuple[int, int]

RETURN_OUTCOMES = (
    ReturnOutcome.WIN,
    ReturnOutcome.HALF_WIN_HALF_PUSH,
    ReturnOutcome.PUSH,
    ReturnOutcome.HALF_LOSE_HALF_PUSH,
    ReturnOutcome.LOSS,
)


def _validate_odds(odds: Decimal) -> None:
    if not odds.is_finite():
        raise SettlementInputError(f"odds must be finite, got {odds}")
    if odds < MIN_ODDS:
        raise SettlementInputError(f"odds must be at least {MIN_ODDS}, got {odds}")


def _validate_probability(probability: Decimal) -> None:
    if not probability.is_finite():
        raise SettlementInputError(f"probabilities must be finite, got {probability}")
    if probability < 0:
        raise SettlementInputError("probabilities cannot be negative")


def return_multiple(outcome: ReturnOutcome, odds: Decimal) -> Decimal:
    _validate_odds(odds)
    if outcome is ReturnOutcome.WIN:
        return odds - Decimal(1)
    if outcome is ReturnOutcome.HALF_WIN_HALF_PUSH:
        return (odds - Decimal(1)) / Decimal(2)
    if outcome is ReturnOutcome.PUSH:
        return Decimal(0)
    if outcome is ReturnOutcome.HALF_LOSE_HALF_PUSH:
        return Decimal("-0.5")
    if outcome is ReturnOutcome.LOSS:
        return Decimal(-1)
    raise SettlementInputError(f"unsupported return outcome {outcome}")


def _invert(outcome: ReturnOutcome) -> ReturnOutcome:
    if outcome is ReturnOutcome.WIN:
        return ReturnOutcome.LOSS
    if outcome is ReturnOutcome.LOSS:
        return ReturnOutcome.WIN
    return ReturnOutcome.PUSH


def _combine(outcomes: tuple[ReturnOutcome, ...]) -> ReturnOutcome:
    if len(outcomes) == 1:
        return outcomes[0]
    if len(outcomes) != 2:
        raise SettlementInputError("split lines must contain exactly two halves")
    pair = tuple(sorted(outcomes, key=lambda item: item.value))
    if pair == (ReturnOutcome.WIN, ReturnOutcome.WIN):
        return ReturnOutcome.WIN
    if pair == (ReturnOutcome.LOSS, ReturnOutcome.LOSS):
        return ReturnOutcome.LOSS
    if pair == (ReturnOutcome.PUSH, ReturnOutcome.PUSH):
        return ReturnOutcome.PUSH
    if pair == (ReturnOutcome.PUSH, ReturnOutcome.WIN):
        return ReturnOutcome.HALF_WIN_HALF_PUSH
    if pair == (ReturnOutcome.LOSS, ReturnOutcome.PUSH):
        return ReturnOutcome.HALF_LOSE_HALF_PUSH
    raise SettlementInputError(f"split line produced unsupported pair {pair}")


def _settle_had(selection: Side, home_goals: int, away_goals: int) -> ReturnOutcome:
    if home_goals > away_goals:
        winner = Side.H
    elif home_goals < away_goals:
        winner = Side.A
    else:
        winner = Side.D
    return ReturnOutcome.WIN if selection is winner else ReturnOutcome.LOSS


def _settle_hdc(
    selection: Side, home_goals: int, away_goals: int, halves: tuple[Decimal, ...]
) -> ReturnOutcome:
    goal_difference = Decimal(home_goals - away_goals)
    outcomes: list[ReturnOutcome] = []
    for handicap in halves:
        adjusted = goal_difference + handicap
        home_outcome = (
            ReturnOutcome.WIN
            if adjusted > 0
            else ReturnOutcome.LOSS
            if adjusted < 0
            else ReturnOutcome.PUSH
        )
        outcomes.append(home_outcome if selection is Side.H else _invert(home_outcome))
    return _combine(tuple(outcomes))


def _settle_hil(
    selection: Side, total_goals: int, halves: tuple[Decimal, ...]
) -> ReturnOutcome:
    outcomes: list[ReturnOutcome] = []
    for line in halves:
        if total_goals == line:
            outcomes.append(ReturnOutcome.PUSH)
            continue
        over_wins = total_goals > line
        selection_wins = (selection is Side.H and over_wins) or (
            selection is Side.L and not over_wins
        )
        outcomes.append(ReturnOutcome.WIN if selection_wins else ReturnOutcome.LOSS)
    return _combine(tuple(outcomes))


def _parse_halves(market: MarketType, condition_raw: str) -> tuple[Decimal, ...]:
    if market is MarketType.HIL:
        parts = condition_raw.strip().split("/")
        if any(part.strip().startswith(("+", "-")) for part in parts):
            raise SettlementInputError(f"HIL condition must be unsigned, got {condition_raw}")
    try:
        return parse_condition_raw(condition_raw)
    except InvalidConditionRaw as exc:
        raise SettlementInputError(f"invalid condition {condition_raw}") from exc


def settle_return(
    market: MarketType,
    selection: Side,
    condition_raw: str,
    score: Score,
    odds: Decimal,
) -> ReturnOutcome:
    _validate_odds(odds)
    home_goals, away_goals = score
    if home_goals < 0 or away_goals < 0:
        raise SettlementInputError("goals cannot be negative")
    validate_side(market, selection)
    if market is MarketType.HAD:
        return _settle_had(selection, home_goals, away_goals)
    halves = _parse_halves(market, condition_raw)
    if market is MarketType.HDC:
        return _settle_hdc(selection, home_goals, away_goals, halves)
    if market is MarketType.HIL:
        return _settle_hil(selection, home_goals + away_goals, halves)
    raise SettlementInputError(f"unsupported market {market}")


def return_distribution(
    score_distribution: Mapping[Score, Decimal],
    market: MarketType,
    selection: Side,
    condition_raw: str,
    odds: Decimal,
) -> ReturnDistribution:
    if not score_distribution:
        raise SettlementInputError("score distribution cannot be empty")
    for probability in score_distribution.values():
        _validate_probability(probability)
    total = sum(score_distribution.values(), Decimal(0))
    if abs(total - Decimal(1)) > DISTRIBUTION_TOLERANCE:
        raise SettlementInputError(f"score distribution must sum to 1, got {total}")
    distribution = {outcome: Decimal(0) for outcome in RETURN_OUTCOMES}
    for score, probability in score_distribution.items():
        outcome = settle_return(market, selection, condition_raw, score, odds)
        distribution[outcome] += probability
    return distribution


def expected_value(distribution: ReturnDistribution, odds: Decimal) -> Decimal:
    _validate_odds(odds)
    return sum(
        (
            probability * return_multiple(outcome, odds)
            for outcome, probability in distribution.items()
        ),
        Decimal(0),
    )
