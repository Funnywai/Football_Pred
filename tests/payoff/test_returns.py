from decimal import Decimal

import pytest

from packages.domain.enums import BetStatus, MarketType, Side
from packages.domain.errors import SettlementInputError
from packages.ledger.settlement import settle_market
from packages.payoff.returns import (
    ReturnOutcome,
    expected_value,
    return_distribution,
    return_multiple,
    settle_return,
)

D = Decimal

RETURN_TO_STATUS = {
    ReturnOutcome.WIN: BetStatus.WON,
    ReturnOutcome.HALF_WIN_HALF_PUSH: BetStatus.HALF_WON_HALF_PUSH,
    ReturnOutcome.PUSH: BetStatus.PUSH,
    ReturnOutcome.HALF_LOSE_HALF_PUSH: BetStatus.HALF_LOST_HALF_PUSH,
    ReturnOutcome.LOSS: BetStatus.LOST,
}


def test_return_multiple_values():
    assert return_multiple(ReturnOutcome.WIN, D("2.00")) == D("1.00")
    assert return_multiple(ReturnOutcome.HALF_WIN_HALF_PUSH, D("2.00")) == D("0.50")
    assert return_multiple(ReturnOutcome.PUSH, D("2.00")) == D("0.00")
    assert return_multiple(ReturnOutcome.HALF_LOSE_HALF_PUSH, D("2.00")) == D("-0.50")
    assert return_multiple(ReturnOutcome.LOSS, D("2.00")) == D("-1.00")


def test_had_distribution_matches_binary_ev():
    scores = {(2, 0): D("0.45"), (1, 1): D("0.30"), (0, 1): D("0.25")}
    distribution = return_distribution(scores, MarketType.HAD, Side.H, "0.0", D("2.00"))
    assert distribution[ReturnOutcome.WIN] == D("0.45")
    assert distribution[ReturnOutcome.LOSS] == D("0.55")
    assert expected_value(distribution, D("2.00")) == D("-0.10")
    binary = D("0.45") * (D("2.00") - D("1")) + D("0.55") * D("-1")
    assert expected_value(distribution, D("2.00")) == binary


def test_hdc_push_outcome():
    score = settle_return(MarketType.HDC, Side.H, "-1.0", (2, 1), D("1.95"))
    assert score is ReturnOutcome.PUSH
    distribution = return_distribution(
        {(2, 1): D("1.0")},
        MarketType.HDC,
        Side.H,
        "-1.0",
        D("1.95"),
    )
    assert distribution[ReturnOutcome.PUSH] == D("1.0")


def test_hdc_split_half_win_half_push():
    outcome = settle_return(MarketType.HDC, Side.H, "0.0/-1.0", (2, 1), D("1.95"))
    assert outcome is ReturnOutcome.HALF_WIN_HALF_PUSH
    assert return_multiple(outcome, D("1.95")) == D("0.475")


def test_hil_split_outcomes():
    over = settle_return(MarketType.HIL, Side.H, "2.5/3.0", (2, 1), D("1.90"))
    under = settle_return(MarketType.HIL, Side.L, "2.5/3.0", (2, 1), D("1.90"))
    assert over is ReturnOutcome.HALF_WIN_HALF_PUSH
    assert under is ReturnOutcome.HALF_LOSE_HALF_PUSH


def test_distribution_sums_to_one():
    scores = {(2, 0): D("0.5"), (0, 0): D("0.5")}
    distribution = return_distribution(scores, MarketType.HIL, Side.H, "2.5", D("1.90"))
    assert sum(distribution.values(), D("0")) == D("1.0")


def test_impossible_outcome_is_exactly_zero():
    scores = {(2, 1): D("0.6"), (1, 0): D("0.4")}
    distribution = return_distribution(scores, MarketType.HDC, Side.H, "0.5", D("1.95"))
    assert distribution[ReturnOutcome.PUSH] == D("0")
    assert distribution[ReturnOutcome.HALF_WIN_HALF_PUSH] == D("0")


@pytest.mark.parametrize("condition", ["-0.5", "+0.5"])
def test_signed_hil_condition_is_rejected(condition):
    with pytest.raises(SettlementInputError):
        settle_return(MarketType.HIL, Side.H, condition, (2, 1), D("1.90"))


def test_return_distribution_rejects_bad_total():
    with pytest.raises(SettlementInputError):
        return_distribution(
            {(1, 0): D("0.5")},
            MarketType.HAD,
            Side.H,
            "0.0",
            D("2.00"),
        )


@pytest.mark.parametrize("probability", [Decimal("NaN"), Decimal("Infinity")])
def test_return_distribution_rejects_non_finite_probability(probability):
    with pytest.raises(SettlementInputError):
        return_distribution(
            {(1, 0): probability},
            MarketType.HAD,
            Side.H,
            "0.0",
            D("2.00"),
        )


@pytest.mark.parametrize(
    ("market", "selection", "condition", "score", "odds"),
    [
        (MarketType.HAD, Side.H, "0.0", (2, 1), "2.00"),
        (MarketType.HAD, Side.D, "0.0", (1, 1), "3.40"),
        (MarketType.HAD, Side.A, "0.0", (0, 1), "3.80"),
        (MarketType.HDC, Side.H, "-1.0", (2, 1), "1.95"),
        (MarketType.HDC, Side.H, "0.0/-1.0", (2, 1), "1.95"),
        (MarketType.HDC, Side.A, "0.0/-1.0", (1, 0), "1.95"),
        (MarketType.HIL, Side.H, "2.5/3.0", (2, 1), "1.90"),
        (MarketType.HIL, Side.L, "2.5/3.0", (2, 1), "1.90"),
    ],
)
def test_settle_return_matches_settlement_engine(market, selection, condition, score, odds):
    decimal_odds = D(odds)
    payoff_outcome = settle_return(market, selection, condition, score, decimal_odds)
    settlement = settle_market(
        market,
        selection,
        score[0],
        score[1],
        condition,
        decimal_odds,
        D("10.00"),
    )
    assert settlement.result_status is RETURN_TO_STATUS[payoff_outcome]
