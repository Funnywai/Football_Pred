from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from packages.adapters.football_data_co_uk import HistoricalMatchRow
from packages.backtest.walk_forward import (
    HAD_OUTCOMES,
    devig_had,
    fit_historical_ratings,
    market_had_quote,
    multiclass_brier,
    multiclass_log_loss,
    run_walk_forward,
    team_id,
    walk_forward_predictions,
)
from packages.models.poisson import (
    DEFAULT_AWAY_GOALS,
    DEFAULT_HOME_GOALS,
    MODEL_VERSION,
    predict_had,
)

D = Decimal

ODDS_SETS = (
    ("2.10", "3.50", "3.60"),
    ("2.90", "3.30", "2.80"),
    ("2.20", "3.40", "3.30"),
    ("3.10", "3.20", "2.70"),
)

_RESULTS = (
    ("Arsenal", "Chelsea", 2, 1),
    ("Liverpool", "Everton", 1, 1),
    ("Chelsea", "Liverpool", 0, 2),
    ("Everton", "Arsenal", 0, 1),
    ("Arsenal", "Liverpool", 3, 0),
    ("Chelsea", "Everton", 2, 2),
    ("Liverpool", "Arsenal", 1, 2),
    ("Everton", "Chelsea", 1, 0),
    ("Arsenal", "Everton", 2, 0),
    ("Liverpool", "Chelsea", 1, 0),
    ("Chelsea", "Arsenal", 1, 1),
    ("Everton", "Liverpool", 0, 3),
    ("Liverpool", "Chelsea", 2, 2),
    ("Arsenal", "Everton", 4, 1),
    ("Chelsea", "Liverpool", 0, 1),
    ("Everton", "Arsenal", 1, 3),
    ("Arsenal", "Chelsea", 2, 2),
    ("Liverpool", "Everton", 2, 0),
    ("Chelsea", "Everton", 0, 1),
    ("Arsenal", "Liverpool", 1, 0),
)


def _optional_decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _row(
    played_on: date,
    home_team: str,
    away_team: str,
    home_goals: int,
    away_goals: int,
    *,
    b365: tuple[str | None, str | None, str | None] = ("2.10", "3.50", "3.60"),
    ps: tuple[str | None, str | None, str | None] = (None, None, None),
    result: str | None = None,
) -> HistoricalMatchRow:
    if result is None:
        if home_goals > away_goals:
            result = "H"
        elif home_goals == away_goals:
            result = "D"
        else:
            result = "A"
    return HistoricalMatchRow(
        competition_code="EPL",
        season_start_year=2025,
        played_on=played_on,
        kickoff_time=None,
        home_team=home_team,
        away_team=away_team,
        home_goals_90=home_goals,
        away_goals_90=away_goals,
        result=result,
        b365_home=_optional_decimal(b365[0]),
        b365_draw=_optional_decimal(b365[1]),
        b365_away=_optional_decimal(b365[2]),
        ps_home=_optional_decimal(ps[0]),
        ps_draw=_optional_decimal(ps[1]),
        ps_away=_optional_decimal(ps[2]),
    )


def _dataset() -> list[HistoricalMatchRow]:
    rows: list[HistoricalMatchRow] = []
    for index, (home, away, home_goals, away_goals) in enumerate(_RESULTS):
        rows.append(
            _row(
                date(2025, 8, index // 2 + 1),
                home,
                away,
                home_goals,
                away_goals,
                b365=ODDS_SETS[index % len(ODDS_SETS)],
            )
        )
    return rows


def test_fit_ratings_changes_with_prior_results():
    as_of = date(2025, 8, 5)
    strong_rows = [
        _row(date(2025, 8, 1), "Arsenal", "Chelsea", 5, 0),
        _row(date(2025, 8, 2), "Arsenal", "Everton", 4, 0),
        _row(date(2025, 8, 3), "Liverpool", "Chelsea", 1, 1),
        _row(date(2025, 8, 4), "Liverpool", "Everton", 1, 1),
    ]
    weak_rows = [
        _row(date(2025, 8, 1), "Arsenal", "Chelsea", 0, 5),
        _row(date(2025, 8, 2), "Arsenal", "Everton", 0, 4),
        _row(date(2025, 8, 3), "Liverpool", "Chelsea", 1, 1),
        _row(date(2025, 8, 4), "Liverpool", "Everton", 1, 1),
    ]

    strong = fit_historical_ratings(strong_rows, as_of=as_of)
    weak = fit_historical_ratings(weak_rows, as_of=as_of)

    arsenal = team_id("Arsenal")
    assert strong.teams[arsenal].attack > weak.teams[arsenal].attack
    assert strong.teams[arsenal].defense < weak.teams[arsenal].defense


def test_fit_uses_only_strictly_prior_dates():
    rows = [
        _row(date(2025, 8, 1), "Arsenal", "Chelsea", 2, 0),
        _row(date(2025, 8, 2), "Chelsea", "Liverpool", 0, 3),
        _row(date(2025, 8, 3), "Liverpool", "Arsenal", 1, 1),
    ]

    ratings = fit_historical_ratings(rows, as_of=date(2025, 8, 2))

    assert ratings.league_avg_home == D("2")
    assert ratings.league_avg_away == D("0")
    assert team_id("Liverpool") not in ratings.teams
    assert team_id("Arsenal") in ratings.teams
    assert team_id("Chelsea") in ratings.teams


def test_fit_uses_uuid5_team_keys_and_neutral_missing_team():
    rows = [_row(date(2025, 8, 1), "Arsenal", "Chelsea", 1, 0)]

    ratings = fit_historical_ratings(rows, as_of=date(2025, 8, 2))

    assert set(ratings.teams) == {team_id("Arsenal"), team_id("Chelsea")}
    neutral = ratings.strength(team_id("Unknown"))
    assert neutral.attack == D(1)
    assert neutral.defense == D(1)


def test_fit_without_history_returns_live_defaults():
    ratings = fit_historical_ratings([], as_of=date(2025, 8, 1))

    assert ratings.league_avg_home == DEFAULT_HOME_GOALS
    assert ratings.league_avg_away == DEFAULT_AWAY_GOALS
    assert dict(ratings.teams) == {}
    assert ratings.model_version == MODEL_VERSION


def test_devig_normalizes_proportional_probabilities():
    probabilities = devig_had(D("2.0"), D("4.0"), D("4.0"))

    assert probabilities is not None
    assert probabilities == (D("0.5"), D("0.25"), D("0.25"))
    assert sum(probabilities, D(0)) == D(1)


def test_devig_normalizes_overround_to_one():
    probabilities = devig_had(D("2.0"), D("3.5"), D("4.0"))

    assert probabilities is not None
    assert abs(sum(probabilities, D(0)) - D(1)) <= D("1e-9")
    assert all(probability > 0 for probability in probabilities)


@pytest.mark.parametrize(
    "odds",
    [
        (None, D("4.0"), D("4.0")),
        (D("2.0"), None, D("4.0")),
        (D("2.0"), D("4.0"), None),
        (D("1.0"), D("4.0"), D("4.0")),
        (D("0"), D("4.0"), D("4.0")),
        (D("-2.0"), D("4.0"), D("4.0")),
        (D("Infinity"), D("4.0"), D("4.0")),
        (D("NaN"), D("4.0"), D("4.0")),
    ],
)
def test_devig_returns_none_for_missing_or_invalid_odds(
    odds: tuple[Decimal | None, Decimal | None, Decimal | None],
):
    assert devig_had(*odds) is None


def test_market_quote_prefers_b365_and_falls_back_to_ps():
    b365_row = _row(
        date(2025, 8, 1),
        "Arsenal",
        "Chelsea",
        1,
        0,
        b365=("2.0", "4.0", "4.0"),
        ps=("9.0", "9.0", "9.0"),
    )
    b365_quote = market_had_quote(b365_row)
    assert b365_quote is not None
    assert b365_quote.bookmaker == "B365"
    assert b365_quote.probabilities == (D("0.5"), D("0.25"), D("0.25"))

    ps_row = _row(
        date(2025, 8, 1),
        "Arsenal",
        "Chelsea",
        1,
        0,
        b365=(None, None, None),
        ps=("2.0", "4.0", "4.0"),
    )
    ps_quote = market_had_quote(ps_row)
    assert ps_quote is not None
    assert ps_quote.bookmaker == "PS"

    partial_b365_row = _row(
        date(2025, 8, 1),
        "Arsenal",
        "Chelsea",
        1,
        0,
        b365=("2.0", None, "4.0"),
        ps=("2.0", "4.0", "4.0"),
    )
    assert market_had_quote(partial_b365_row) is None

    partial_ps_row = _row(
        date(2025, 8, 1),
        "Arsenal",
        "Chelsea",
        1,
        0,
        b365=(None, None, None),
        ps=("2.0", None, "4.0"),
    )
    assert market_had_quote(partial_ps_row) is None


def test_multiclass_brier_matches_known_distribution():
    probabilities = {"H": D("0.5"), "D": D("0.3"), "A": D("0.2")}

    assert multiclass_brier(probabilities, "H") == D("0.38")
    assert multiclass_brier(probabilities, "D") == D("0.78")
    assert multiclass_brier(probabilities, "A") == D("0.98")


def test_multiclass_log_loss_matches_known_distribution():
    probabilities = {"H": D("0.5"), "D": D("0.3"), "A": D("0.2")}

    assert abs(multiclass_log_loss(probabilities, "H") - (-D("0.5").ln())) <= D("1e-12")
    assert abs(multiclass_log_loss(probabilities, "D") - (-D("0.3").ln())) <= D("1e-12")


def test_multiclass_log_loss_uses_working_epsilon_without_mutating_probabilities():
    probabilities = {"H": D("0"), "D": D("1"), "A": D("0")}

    loss = multiclass_log_loss(probabilities, "H")

    assert loss.is_finite()
    assert loss > 0
    assert probabilities["H"] == D("0")


def test_metrics_reject_invalid_inputs():
    probabilities = {"H": D("0.5"), "D": D("0.3"), "A": D("0.2")}

    with pytest.raises(ValueError):
        multiclass_brier(probabilities, "X")
    with pytest.raises(ValueError):
        multiclass_log_loss(probabilities, "X")
    with pytest.raises(ValueError):
        multiclass_brier({"H": D("1.1"), "D": D("0.0"), "A": D("-0.1")}, "H")


def test_walk_forward_skips_early_rows_and_reports_finite_metrics():
    report = run_walk_forward(_dataset(), min_train=5)

    assert report.matches_total == 20
    assert report.matches_evaluated == 15
    assert report.matches_skipped == 5
    assert report.matches_with_market == 15
    assert report.bets_placed > 0
    for metric in (
        report.brier_model,
        report.brier_market,
        report.log_loss_model,
        report.log_loss_market,
        report.roi_model,
    ):
        assert metric is not None
        assert metric.is_finite()
    assert report.model_version == MODEL_VERSION


def test_walk_forward_prediction_uses_only_strictly_prior_dates():
    rows = _dataset()

    predictions = walk_forward_predictions(rows, min_train=5)

    first = predictions[0]
    assert first.row.played_on == date(2025, 8, 3)
    assert any(
        row.played_on == first.row.played_on and row != first.row for row in rows
    )

    ratings = fit_historical_ratings(rows, as_of=first.row.played_on)
    expected = predict_had(
        ratings,
        team_id(first.row.home_team),
        team_id(first.row.away_team),
    )
    assert first.model == {
        "H": expected.p_home,
        "D": expected.p_draw,
        "A": expected.p_away,
    }


def test_mutating_same_day_and_future_rows_does_not_change_earlier_prediction():
    rows = _dataset()
    original = walk_forward_predictions(rows, min_train=5)
    first = original[0]

    same_day_other = next(
        row for row in rows if row.played_on == first.row.played_on and row != first.row
    )
    future_row = next(row for row in rows if row.played_on > first.row.played_on)

    mutated_rows = [
        replace(row, home_goals_90=9, away_goals_90=0, result="H")
        if row in (same_day_other, future_row)
        else row
        for row in rows
    ]
    mutated = walk_forward_predictions(mutated_rows, min_train=5)

    assert mutated[0].model == first.model
    assert mutated[0].row == first.row


def test_calibration_bin_counts_sum_to_evaluated_outcomes():
    report = run_walk_forward(_dataset(), min_train=5)

    assert set(report.calibration) == set(HAD_OUTCOMES)
    for outcome in HAD_OUTCOMES:
        bins = report.calibration[outcome]
        assert sum(bin.count for bin in bins) == report.matches_evaluated
        for calibration_bin in bins:
            assert 0 <= calibration_bin.bin_index < 10
            assert calibration_bin.count > 0
            assert 0 <= calibration_bin.positives <= calibration_bin.count
            assert D(0) <= calibration_bin.observed_rate <= D(1)
            assert calibration_bin.predicted_mean.is_finite()


def test_walk_forward_with_no_rows_returns_zero_report():
    report = run_walk_forward([], min_train=5)

    assert report.matches_total == 0
    assert report.matches_evaluated == 0
    assert report.matches_skipped == 0
    assert report.brier_model is None
    assert report.brier_market is None
    assert report.log_loss_model is None
    assert report.log_loss_market is None
    assert report.roi_model is None
    assert report.calibration == {}
    assert report.model_version == MODEL_VERSION
