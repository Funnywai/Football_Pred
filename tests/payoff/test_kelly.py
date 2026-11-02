from decimal import Decimal

from packages.domain.enums import MarketType, Side
from packages.payoff.kelly import kelly_fraction
from packages.payoff.returns import ReturnOutcome, return_distribution

D = Decimal


def test_kelly_is_zero_at_zero_edge():
    distribution = {ReturnOutcome.WIN: D("0.5"), ReturnOutcome.LOSS: D("0.5")}
    assert kelly_fraction(distribution, D("2.00"), D("0.99")) == D("0")


def test_kelly_is_positive_for_known_positive_edge():
    distribution = {ReturnOutcome.WIN: D("0.6"), ReturnOutcome.LOSS: D("0.4")}
    fraction = kelly_fraction(distribution, D("2.00"), D("0.99"))
    assert abs(fraction - D("0.2")) < D("0.001")


def test_kelly_never_exceeds_max_fraction():
    distribution = {ReturnOutcome.WIN: D("0.9"), ReturnOutcome.LOSS: D("0.1")}
    fraction = kelly_fraction(distribution, D("3.00"), D("0.25"))
    assert fraction <= D("0.25")
    assert fraction > D("0")


def test_negative_edge_returns_zero():
    distribution = {ReturnOutcome.WIN: D("0.4"), ReturnOutcome.LOSS: D("0.6")}
    assert kelly_fraction(distribution, D("2.00"), D("0.99")) == D("0")


def test_had_matches_binary_closed_form():
    probability = D("0.6")
    odds = D("2.00")
    distribution = {
        ReturnOutcome.WIN: probability,
        ReturnOutcome.LOSS: D("1") - probability,
    }
    closed_form = (probability * (odds - D("1")) - (D("1") - probability)) / (
        odds - D("1")
    )
    fraction = kelly_fraction(distribution, odds, D("0.99"))
    assert abs(fraction - closed_form) < D("0.001")


def test_hdc_split_distribution_gets_positive_kelly():
    scores = {(1, 0): D("0.6"), (0, 0): D("0.4")}
    distribution = return_distribution(scores, MarketType.HDC, Side.H, "0.5", D("2.00"))
    fraction = kelly_fraction(distribution, D("2.00"), D("0.99"))
    assert fraction > D("0")
    assert fraction <= D("0.99")
