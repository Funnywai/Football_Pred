import pytest

from app.ml.value import clv_metrics, edge, fair_odds, is_value, kelly_fraction


def test_edge_and_fair_odds() -> None:
    assert edge(0.5, 0.45) == pytest.approx(0.05)
    assert fair_odds(0.5) == pytest.approx(2.0)
    assert fair_odds(0.0) == float("inf")


def test_is_value() -> None:
    assert is_value(0.03, 0.02)
    assert not is_value(0.02, 0.02)  # strictly greater


def test_kelly_fraction() -> None:
    # even odds, true prob 0.6 -> f = (1*0.6 - 0.4)/1 = 0.2
    assert kelly_fraction(0.6, 2.0) == pytest.approx(0.2)
    assert kelly_fraction(0.4, 2.0) == 0.0  # no edge -> no stake
    assert kelly_fraction(0.5, 1.0) == 0.0  # b <= 0


def test_clv_metrics() -> None:
    model = {1: {"H": 0.5, "D": 0.3, "A": 0.2}}
    closing = {1: {"H": 0.45, "D": 0.32, "A": 0.23}}
    metrics = clv_metrics(model, closing)
    assert metrics["clv_n"] == 3
    assert metrics["clv_fraction"] == pytest.approx(1 / 3)  # H beats, D/A don't
    assert clv_metrics({1: {"H": 0.5}}, {})["clv_fraction"] is None


def test_clv_metrics_keys_do_not_collide_with_eval_metrics() -> None:
    keys = set(clv_metrics({1: {"H": 0.5}}, {1: {"H": 0.5}})) | set(clv_metrics({}, {}))
    assert keys & {"brier", "logloss", "n"} == set()
