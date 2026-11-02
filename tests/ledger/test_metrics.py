from decimal import Decimal

import pytest

from packages.ledger.metrics import (
    bankroll_curve,
    brier_score,
    clv,
    max_drawdown,
    roi,
)

D = Decimal


def test_roi_uses_net_payout_over_stake():
    assert roi(D("100"), D("200")) == D("1")
    assert roi(D("100"), D("80")) == D("-0.2")
    assert roi(D("0"), D("10")) == D("0")


def test_clv_handles_missing_closing_odds():
    assert clv(D("2.0"), D("1.8")) == D("2.0") / D("1.8") - D("1")
    assert clv(D("2.0"), None) is None
    assert clv(D("2.0"), D("0")) is None


def test_brier_score_is_squared_error():
    assert brier_score(D("0.7"), 1) == D("0.09")
    assert brier_score(D("0.7"), 0) == D("0.49")
    with pytest.raises(ValueError):
        brier_score(D("0.7"), 2)


def test_brier_score_rejects_probability_outside_unit_interval():
    with pytest.raises(ValueError):
        brier_score(D("1.01"), 1)
    with pytest.raises(ValueError):
        brier_score(D("-0.01"), 0)


def test_max_drawdown_uses_peak_to_trough():
    curve = [D("100"), D("120"), D("90"), D("110")]
    assert max_drawdown(curve) == D("0.25")
    assert max_drawdown([D("100"), D("110")]) == D("0")
    assert max_drawdown([]) == D("0")


def test_max_drawdown_starts_at_zero_equity():
    assert max_drawdown([D("0"), D("10"), D("5")]) == D("0.5")


def test_bankroll_curve_applies_payout_minus_stake():
    curve = bankroll_curve(D("1000"), [(D("100"), D("200")), (D("50"), D("0"))])
    assert curve == [D("1000"), D("1100"), D("1050")]


def test_bankroll_curve_with_no_settled_bets():
    assert bankroll_curve(D("1000"), []) == [D("1000")]
