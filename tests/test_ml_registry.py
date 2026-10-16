import pytest
from ml_helpers import make_db

from app.ml.metrics import economic_backtest, expected_calibration_error
from app.ml.registry import (
    STATUS_RETIRED,
    gate_passes,
    get_champion,
    maybe_promote,
    register_challenger,
    rollback,
)


def _metrics(**overrides) -> dict:
    """A full metric set; the defaults pass the gate against themselves."""
    base = {
        "logloss": 0.95,
        "brier": 0.55,
        "ece": 0.03,
        "clv_mean_edge": 0.01,
        "roi": 0.02,
    }
    return {**base, **overrides}


def test_gate_passes() -> None:
    """A challenger better on every metric is promoted."""
    challenger = _metrics(logloss=0.94, brier=0.54, ece=0.02, clv_mean_edge=0.02, roi=0.03)
    assert gate_passes(challenger, _metrics(), 0.0)


def test_gate_blocks_a_logloss_gain_below_the_margin() -> None:
    assert not gate_passes(_metrics(logloss=0.949), _metrics(logloss=0.95), 0.01)


def test_gate_promotes_a_logloss_gain_above_the_margin() -> None:
    assert gate_passes(_metrics(logloss=0.93), _metrics(logloss=0.95), 0.01)


def test_gate_blocks_worse_logloss() -> None:
    # better Brier but worse logloss: the old Brier-only gate promoted this
    assert not gate_passes(_metrics(logloss=0.96, brier=0.54), _metrics(logloss=0.95), 0.0)


def test_gate_promotes_when_logloss_is_better_even_if_brier_is_worse() -> None:
    """Brier must not gate. Measured: the isotonic champion had the BETTER Brier
    (0.57545 vs 0.57579) while being worse on logloss (0.98355 vs 0.96990) and
    worse for betting, so a Brier condition blocks exactly the challenger the
    evidence calls for."""
    isotonic_champion = _metrics(logloss=0.98355, brier=0.57545)
    temperature_challenger = _metrics(logloss=0.96990, brier=0.57579)
    assert gate_passes(temperature_challenger, isotonic_champion, 0.0)


def test_gate_requires_a_strictly_better_logloss() -> None:
    assert not gate_passes(_metrics(logloss=0.95, brier=0.50), _metrics(logloss=0.95, brier=0.60), 0.0)


def test_gate_reports_ece_without_gating_on_it() -> None:
    assert gate_passes(_metrics(ece=0.9, logloss=0.94), _metrics(ece=0.03, logloss=0.95), 0.0)


def test_gate_blocks_worse_clv() -> None:
    assert not gate_passes(
        _metrics(clv_mean_edge=0.005, brier=0.54), _metrics(clv_mean_edge=0.01), 0.0
    )


def test_gate_allows_structurally_zero_clv() -> None:
    """``clv_metrics`` averages the edge over ALL outcomes, so a normalised
    predictor's mean edge against a normalised de-vigged close is ~0 by
    construction (the live challenger stored -1.9e-18). Requiring ``> 0`` would
    therefore block every promotion forever; only "not worse than the champion"
    (float-noise tolerant) may be required. The ``> 0`` intent is carried by
    ``roi``, which comes from a real per-bet simulation.
    """
    challenger = _metrics(brier=0.54, logloss=0.94, clv_mean_edge=-1.9e-18)
    champion = _metrics(clv_mean_edge=-1.9e-18)
    assert gate_passes(challenger, champion, 0.0)


def test_gate_blocks_negative_roi() -> None:
    assert not gate_passes(_metrics(roi=-0.01, brier=0.54), _metrics(roi=0.02), 0.0)


@pytest.mark.parametrize("key", ["logloss", "brier"])
def test_gate_fails_closed_on_missing_mandatory_metrics(key: str) -> None:
    challenger = _metrics(brier=0.54)
    del challenger[key]
    assert not gate_passes(challenger, _metrics(), 0.0)
    champion = _metrics()
    del champion[key]
    assert not gate_passes(_metrics(brier=0.54), champion, 0.0)
    challenger = _metrics(brier=0.54)
    challenger[key] = None
    assert not gate_passes(challenger, _metrics(), 0.0)
    champion = _metrics()
    champion[key] = None
    assert not gate_passes(_metrics(brier=0.54), champion, 0.0)


def test_gate_governs_handicap_shaped_metrics_by_logloss() -> None:
    """The handicap target computes no ece/clv/roi. The extra conditions must be
    applied only when both sides carry them, otherwise the handicap target would
    be silently frozen (never promoted again)."""
    challenger = {"logloss": 0.94, "brier": 0.54, "n": 10}
    champion = {"logloss": 0.95, "brier": 0.55, "n": 10}
    assert gate_passes(challenger, champion, 0.0)
    assert not gate_passes({"logloss": 0.96, "brier": 0.54, "n": 10}, champion, 0.0)


def test_gate_enforces_roi_on_the_challenger_even_without_a_champion_roi() -> None:
    champion = {"logloss": 0.95, "brier": 0.55, "n": 10}
    assert not gate_passes({"logloss": 0.94, "brier": 0.54, "roi": -0.5}, champion, 0.0)
    assert gate_passes({"logloss": 0.94, "brier": 0.54, "roi": 0.01}, champion, 0.0)


def test_gate_promotes_a_challenger_that_trades_slightly_worse_ece_for_better_logloss_and_roi() -> None:
    """Measured on the live eval window: the temperature challenger has better
    logloss (0.96988 vs 0.98355) and far better served ROI (+30.7% vs +10.5%) but
    slightly worse ECE (0.018 vs 0.0141) and Brier. ECE is isotonic's home turf,
    so gating on it structurally favours the configuration being replaced."""
    champion = _metrics(logloss=0.98355, brier=0.57545, ece=0.01405, clv_mean_edge=0.0, roi=0.10505)
    challenger = _metrics(logloss=0.96988, brier=0.57591, ece=0.018, clv_mean_edge=0.0, roi=0.30657)
    assert gate_passes(challenger, champion, 0.0)


def test_expected_calibration_error_hand_computed() -> None:
    probs = [
        [0.8, 0.1, 0.1],  # H, correct, confidence 0.8 -> |0.8 - 1| = 0.2
        [0.6, 0.3, 0.1],  # D, wrong,   confidence 0.6 -> |0.6 - 0| = 0.6
        [0.4, 0.35, 0.25],  # H, correct, confidence 0.4 -> |0.4 - 1| = 0.6
        [0.9, 0.05, 0.05],  # H, correct, confidence 0.9 -> |0.9 - 1| = 0.1
    ]
    labels = ["H", "D", "H", "H"]
    # one sample per 10-bin bucket -> the mean of the four gaps
    assert expected_calibration_error(probs, labels) == pytest.approx((0.2 + 0.6 + 0.6 + 0.1) / 4)


def test_expected_calibration_error_weights_buckets_by_size() -> None:
    probs = [[0.8, 0.1, 0.1], [0.8, 0.15, 0.05]]
    labels = ["H", "D"]
    # both land in the same bucket: confidence 0.8, accuracy 0.5 -> 0.3
    assert expected_calibration_error(probs, labels) == pytest.approx(0.3)


def test_expected_calibration_error_empty_is_zero() -> None:
    assert expected_calibration_error([], []) == 0.0


def test_economic_backtest_hand_computed() -> None:
    probs = [[0.5, 0.3, 0.2]]
    market = [[0.4, 0.35, 0.25]]
    result = economic_backtest(probs, market, ["H"], threshold=0.05)
    # H: edge 0.10 > 0.05 and 0.5 / 0.4 = 1.25 > 1.0 -> 1 unit at fair price 2.5, hit
    assert result["n_bets"] == 1
    assert result["staked"] == pytest.approx(1.0)
    assert result["returned"] == pytest.approx(2.5)
    assert result["roi"] == pytest.approx(1.5)


def test_economic_backtest_losing_bet() -> None:
    probs = [[0.5, 0.3, 0.2]]
    market = [[0.4, 0.35, 0.25]]
    result = economic_backtest(probs, market, ["D"], threshold=0.05)
    assert result["n_bets"] == 1
    assert result["returned"] == pytest.approx(0.0)
    assert result["roi"] == pytest.approx(-1.0)


def test_economic_backtest_aggregates_multiple_bets() -> None:
    probs = [[0.5, 0.3, 0.2], [0.2, 0.5, 0.3]]
    market = [[0.4, 0.35, 0.25], [0.3, 0.4, 0.3]]
    result = economic_backtest(probs, market, ["H", "D"], threshold=0.05)
    # both bets hit at fair price 2.5 -> staked 2, returned 5
    assert result["n_bets"] == 2
    assert result["staked"] == pytest.approx(2.0)
    assert result["returned"] == pytest.approx(5.0)
    assert result["roi"] == pytest.approx(1.5)


def test_economic_backtest_no_bets_is_zero_roi() -> None:
    probs = [[0.5, 0.3, 0.2]]
    market = [[0.4, 0.35, 0.25]]
    assert economic_backtest(probs, market, ["H"], threshold=0.5) == {
        "roi": 0.0,
        "n_bets": 0,
        "staked": 0.0,
        "returned": 0.0,
    }


def test_economic_backtest_exec_edge_buffer_blocks_marginal_bets() -> None:
    probs = [[0.5, 0.3, 0.2]]
    market = [[0.4, 0.35, 0.25]]
    # 0.5 / 0.4 = 1.25 is not > 1.3 -> no bet
    result = economic_backtest(probs, market, ["H"], threshold=0.05, exec_edge_buffer=0.3)
    assert result["n_bets"] == 0
    assert result["roi"] == 0.0


def test_economic_backtest_skips_missing_market_prices() -> None:
    probs = [[0.5, 0.3, 0.2]]
    market = [[float("nan"), 0.35, 0.25]]
    result = economic_backtest(probs, market, ["H"], threshold=0.05)
    assert result["n_bets"] == 0
    assert result["roi"] == 0.0


async def test_promote_and_rollback(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            first = await register_challenger(
                session, "1x2", "lightgbm", {}, _metrics(), "/a.joblib"
            )
            assert await maybe_promote(session, first, 0.0)  # first becomes champion
            champion = await get_champion(session, "1x2")
            assert champion is not None and champion.id == first.id

            better = await register_challenger(
                session,
                "1x2",
                "lightgbm",
                {},
                _metrics(logloss=0.94, brier=0.54, ece=0.02, clv_mean_edge=0.02, roi=0.03),
                "/b.joblib",
            )
            assert await maybe_promote(session, better, 0.0)
            champion = await get_champion(session, "1x2")
            assert champion is not None and champion.id == better.id

            previous = await rollback(session, "1x2")
            assert previous is not None and previous.id == first.id
            champion = await get_champion(session, "1x2")
            assert champion is not None and champion.id == first.id
            assert better.status == STATUS_RETIRED
    finally:
        await db.dispose()


async def test_maybe_promote_uses_fresh_champion_metrics(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            # champion whose STORED brier looks unbeatable
            first = await register_challenger(
                session, "1x2", "lightgbm", {}, _metrics(brier=0.10), "/a.joblib"
            )
            assert await maybe_promote(session, first, 0.0)
            worse = await register_challenger(
                session,
                "1x2",
                "lightgbm",
                {},
                _metrics(logloss=0.94, brier=0.30),
                "/b.joblib",
            )
            # stored metrics would reject (0.30 > 0.10); the FRESH window says 0.40 -> promote
            assert await maybe_promote(
                session, worse, 0.0, champion_metrics=_metrics(logloss=0.95, brier=0.40)
            )
            champion = await get_champion(session, "1x2")
            assert champion is not None and champion.id == worse.id
            # and with None the stored metrics still govern (legacy behaviour)
            newer = await register_challenger(
                session, "1x2", "lightgbm", {}, _metrics(brier=0.35), "/c.joblib"
            )
            assert not await maybe_promote(session, newer, 0.0)
    finally:
        await db.dispose()
