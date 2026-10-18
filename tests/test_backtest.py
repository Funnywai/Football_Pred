"""Unit tests for the read-only 1x2 backtest report (no DB, synthetic candidates)."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import pytest

from app.ml.backtest import (
    BacktestParams,
    Candidate,
    ReportContext,
    build_report,
    flat_roi,
    format_report,
    kelly_roi,
    normal_ci95,
    passes_value_test,
    wilson_interval,
)

KICKOFF = datetime(2025, 1, 1, 15, 0, tzinfo=UTC)


def _params() -> BacktestParams:
    return BacktestParams(
        threshold=0.02,
        exec_edge_buffer=0.03,
        kelly_multiplier=0.5,
        max_stake_fraction=0.05,
    )


def _context() -> ReportContext:
    return ReportContext(
        config={
            "target": "1x2",
            "blend_weight": 0.20,
            "value_edge_threshold": 0.02,
            "exec_edge_buffer": 0.03,
            "prior_lead_hours": 48,
            "kelly_multiplier": 0.5,
            "max_stake_fraction": 0.05,
            "champion_id": 7,
            "champion_artifact": "artifacts/ml/1x2.joblib",
            "champion_promoted_at": "2026-10-01T00:00:00+00:00",
        },
        since=datetime(2024, 10, 18, tzinfo=UTC),
        until=None,
        model_metrics={"brier": 0.58, "logloss": 0.98, "n": 3},
        market_metrics={"brier": 0.57, "logloss": 0.96, "n": 3},
        blend_metrics={"brier": 0.575, "logloss": 0.965, "n": 3},
    )


def _candidate(
    *,
    match_id: int = 1,
    outcome: str = "H",
    label: str = "H",
    p_model: float = 0.50,
    p_prior: float | None = 0.40,
    p_blend: float = 0.50,
    exec_odds: float | None = 2.20,
    exec_source: str = "hkjc",
    closing_prob: float | None = 0.45,
) -> Candidate:
    return Candidate(
        match_id=match_id,
        kickoff_time=KICKOFF,
        outcome=outcome,
        label=label,
        p_model=p_model,
        p_prior=p_prior,
        p_blend=p_blend,
        exec_odds=exec_odds,
        exec_source=exec_source,
        closing_prob=closing_prob,
    )


def test_passes_value_test_when_edge_and_buffer_clear() -> None:
    assert passes_value_test(0.50, 0.40, 2.20, threshold=0.02, buffer=0.03)


def test_passes_value_test_rejects_edge_at_or_below_threshold() -> None:
    assert not passes_value_test(0.42, 0.40, 2.20, threshold=0.02, buffer=0.03)
    assert not passes_value_test(0.41, 0.40, 2.20, threshold=0.02, buffer=0.03)


def test_passes_value_test_rejects_price_inside_the_execution_buffer() -> None:
    # 0.50 * 2.00 == 1.00, which is not > 1.03.
    assert not passes_value_test(0.50, 0.40, 2.00, threshold=0.02, buffer=0.03)


def test_passes_value_test_rejects_missing_price_or_prior() -> None:
    assert not passes_value_test(0.50, 0.40, None, threshold=0.02, buffer=0.03)
    assert not passes_value_test(0.50, None, 2.20, threshold=0.02, buffer=0.03)


def test_clv_uses_selected_bets_and_closing_probability() -> None:
    candidates = [
        _candidate(match_id=1, p_blend=0.50, closing_prob=0.45),
        _candidate(match_id=2, p_blend=0.50, closing_prob=0.55),
    ]
    report = build_report(candidates, _params(), _context())
    assert report["clv_n"] == 2
    assert report["clv_mean_edge"] == pytest.approx(0.0)
    assert report["clv_fraction"] == pytest.approx(0.5)


def test_flat_roi_pays_execution_odds_only_on_a_win() -> None:
    candidates = [
        _candidate(match_id=1, label="H", exec_odds=2.20),
        _candidate(match_id=2, label="A", exec_odds=2.20),
    ]
    report = build_report(candidates, _params(), _context())
    assert report["n_bets"] == 2
    assert report["roi_real"] == pytest.approx(0.10)


def test_flat_roi_and_kelly_roi_handle_empty_input() -> None:
    assert flat_roi([]) is None
    assert kelly_roi([], []) is None


def test_kelly_roi_weights_each_bet_by_its_stake() -> None:
    # (0.10 * 2.0 + 0.05 * 0.0) / 0.15 - 1 = 1/3
    assert kelly_roi([0.10, 0.05], [2.0, 0.0]) == pytest.approx(1.0 / 3.0)


def test_normal_ci95_matches_the_normal_approximation() -> None:
    interval = normal_ci95([1.0, 2.0, 3.0])
    assert interval is not None
    half = 1.96 / math.sqrt(3.0)
    assert interval[0] == pytest.approx(2.0 - half)
    assert interval[1] == pytest.approx(2.0 + half)
    assert normal_ci95([1.0]) is None


def test_wilson_interval_is_bounded_and_null_for_empty_input() -> None:
    interval = wilson_interval(5, 10)
    assert interval is not None
    assert 0.0 <= interval[0] < 0.5 < interval[1] <= 1.0
    assert wilson_interval(0, 0) is None


def test_empty_report_has_null_metrics_and_no_division_error() -> None:
    report = build_report([], _params(), _context())
    assert report["n_bets"] == 0
    assert report["bet_rate"] == 0.0
    assert report["roi_real"] is None
    assert report["roi_real_ci95"] is None
    assert report["roi_kelly"] is None
    assert report["roi_kelly_ci95"] is None
    assert report["clv_n"] == 0
    assert report["clv_mean_edge"] is None
    assert report["clv_fraction"] is None
    assert report["window"]["matches"] == 0
    assert report["window"]["outcomes"] == 0
    assert report["by_outcome"]["H"]["n_bets"] == 0
    assert report["execution_source_counts"] == {"hkjc": 0, "football_data": 0}
    json.dumps(report)


def test_by_outcome_is_ordered_h_d_a() -> None:
    candidates = [
        _candidate(match_id=1, outcome="A", label="A"),
        _candidate(match_id=1, outcome="H", label="H"),
        _candidate(match_id=1, outcome="D", label="D"),
    ]
    report = build_report(candidates, _params(), _context())
    assert list(report["by_outcome"]) == ["H", "D", "A"]


def test_selection_uses_blended_probability_not_raw_model() -> None:
    # Raw model is below the edge bar but the blend clears it -> selected.
    selected = _candidate(match_id=1, p_model=0.41, p_prior=0.40, p_blend=0.50)
    # Raw model clears the bar but the blend does not -> rejected.
    rejected = _candidate(match_id=2, p_model=0.50, p_prior=0.40, p_blend=0.41)
    report = build_report([selected, rejected], _params(), _context())
    assert report["n_bets"] == 1


def test_skipped_no_price_and_execution_source_counts() -> None:
    candidates = [
        _candidate(match_id=1, exec_odds=2.20, exec_source="hkjc"),
        _candidate(match_id=2, exec_odds=2.20, exec_source="football_data"),
        _candidate(match_id=3, exec_odds=None, exec_source="none"),
    ]
    report = build_report(candidates, _params(), _context())
    assert report["skipped_no_price"] == 1
    assert report["execution_source_counts"] == {"hkjc": 1, "football_data": 1}


def test_format_report_contains_the_headline_numbers() -> None:
    report = build_report([_candidate()], _params(), _context())
    text = format_report(report)
    assert "ROI flat 1u" in text
    assert "CLV" in text
    assert "H:" in text
