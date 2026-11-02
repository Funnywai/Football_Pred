from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import cast

import pytest

from packages.adapters.football_data_co_uk import HistoricalMatchRow
from packages.backtest.experiments import (
    HOLDOUT_BLOCK,
    VALIDATION_BLOCK,
    BlockMetrics,
    ExperimentPrediction,
    block_metrics,
    predict_rows,
    run_experiments,
    season_start_year_for,
    sort_historical_rows,
    split_blocks,
)
from packages.backtest.models import (
    apply_temperature,
    dixon_coles_had,
    fit_temperature,
    fit_weighted_ratings,
    poisson_had,
    team_key,
)

D = Decimal
TEAMS = ("Arsenal", "Chelsea", "Liverpool", "Everton")
SCORE_CYCLE = (
    (2, 1),
    (0, 0),
    (1, 2),
    (3, 1),
    (1, 1),
    (0, 2),
    (2, 0),
    (1, 3),
    (0, 1),
    (2, 2),
    (4, 0),
    (1, 0),
)
ODDS_CYCLE = (
    ("2.10", "3.40", "3.60"),
    ("2.80", "3.30", "2.60"),
    ("2.40", "3.20", "3.00"),
    ("3.20", "3.40", "2.30"),
)
PAIRINGS = (
    ((0, 1), (2, 3)),
    ((0, 2), (1, 3)),
    ((0, 3), (1, 2)),
)


def _optional(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _row(
    played_on: date,
    home_team: str,
    away_team: str,
    home_goals: int,
    away_goals: int,
    *,
    season_start_year: int,
    b365: tuple[str | None, str | None, str | None] = ("2.10", "3.40", "3.60"),
    ps: tuple[str | None, str | None, str | None] = (None, None, None),
) -> HistoricalMatchRow:
    if home_goals > away_goals:
        result = "H"
    elif home_goals == away_goals:
        result = "D"
    else:
        result = "A"
    return HistoricalMatchRow(
        competition_code="EPL",
        season_start_year=season_start_year,
        played_on=played_on,
        kickoff_time=None,
        home_team=home_team,
        away_team=away_team,
        home_goals_90=home_goals,
        away_goals_90=away_goals,
        result=result,
        b365_home=_optional(b365[0]),
        b365_draw=_optional(b365[1]),
        b365_away=_optional(b365[2]),
        ps_home=_optional(ps[0]),
        ps_draw=_optional(ps[1]),
        ps_away=_optional(ps[2]),
    )


def _season_rows(season: int) -> list[HistoricalMatchRow]:
    rows: list[HistoricalMatchRow] = []
    season_index = season - 2021
    for round_index in range(12):
        played_on = date(season, 8, 1) + timedelta(days=round_index * 7)
        pairings = PAIRINGS[round_index % len(PAIRINGS)]
        for match_index, (home, away) in enumerate(pairings):
            cycle = season_index * 12 + round_index * 2 + match_index
            home_goals, away_goals = SCORE_CYCLE[cycle % len(SCORE_CYCLE)]
            rows.append(
                _row(
                    played_on,
                    TEAMS[home],
                    TEAMS[away],
                    home_goals,
                    away_goals,
                    season_start_year=season,
                    b365=ODDS_CYCLE[cycle % len(ODDS_CYCLE)],
                )
            )
    return rows


def _dataset() -> list[HistoricalMatchRow]:
    rows: list[HistoricalMatchRow] = []
    for season in (2021, 2022, 2023, 2024, 2025):
        rows.extend(_season_rows(season))
    return rows


def test_season_label_derives_from_match_date_when_missing():
    assert season_start_year_for(
        _row(date(2024, 8, 1), "A", "B", 1, 0, season_start_year=0)
    ) == 2024
    assert season_start_year_for(
        _row(date(2025, 2, 1), "A", "B", 1, 0, season_start_year=0)
    ) == 2024


def test_sort_and_split_blocks_use_season_labels():
    rows = sort_historical_rows(_dataset())
    assert rows == sorted(
        rows,
        key=lambda row: (
            row.played_on,
            row.season_start_year,
            row.home_team,
            row.away_team,
        ),
    )

    blocks = split_blocks(rows)
    assert all(row.season_start_year <= 2023 for row in blocks["train"])
    assert all(row.season_start_year == 2024 for row in blocks["validation"])
    assert all(row.season_start_year == 2025 for row in blocks["holdout"])
    assert len(blocks["train"]) == 72
    assert len(blocks["validation"]) == 24
    assert len(blocks["holdout"]) == 24


def test_predict_rows_ignores_same_day_and_future_results():
    rows = _dataset()
    validation_rows = split_blocks(rows)[VALIDATION_BLOCK]
    target = validation_rows[0]
    baseline = predict_rows(
        rows, predict_for=[target], variant="poisson", min_train=1
    )[0]

    same_day = next(
        row
        for row in validation_rows
        if row.played_on == target.played_on and row != target
    )
    future = next(row for row in validation_rows if row.played_on > target.played_on)
    mutated_rows = [
        replace(row, home_goals_90=9, away_goals_90=0, result="H")
        if row in (same_day, future)
        else row
        for row in rows
    ]

    mutated = predict_rows(
        mutated_rows, predict_for=[target], variant="poisson", min_train=1
    )[0]
    assert mutated.model == baseline.model


def test_time_decay_weights_recent_results_more_heavily():
    as_of = date(2025, 1, 1)
    rows = [
        _row(date(2021, 8, 1), "Arsenal", "Chelsea", 0, 5, season_start_year=2021),
        _row(date(2021, 8, 8), "Arsenal", "Everton", 0, 4, season_start_year=2021),
        _row(date(2021, 8, 15), "Chelsea", "Liverpool", 2, 2, season_start_year=2021),
        _row(date(2021, 8, 22), "Everton", "Liverpool", 1, 1, season_start_year=2021),
        _row(date(2024, 8, 1), "Arsenal", "Chelsea", 5, 0, season_start_year=2024),
        _row(date(2024, 8, 8), "Arsenal", "Everton", 4, 0, season_start_year=2024),
        _row(date(2024, 8, 15), "Chelsea", "Liverpool", 2, 2, season_start_year=2024),
        _row(date(2024, 8, 22), "Everton", "Liverpool", 1, 1, season_start_year=2024),
    ]

    flat = fit_weighted_ratings(rows, as_of=as_of, decay=D("0"))
    recency = fit_weighted_ratings(rows, as_of=as_of, decay=D("2"))

    arsenal = team_key("Arsenal")
    assert recency.teams[arsenal].attack > flat.teams[arsenal].attack


def test_dixon_coles_probabilities_are_normalized_and_rho_zero_matches_poisson():
    rows = _dataset()
    as_of = date(2025, 8, 1)
    ratings = fit_weighted_ratings(rows, as_of=as_of, decay=D("0"))
    home = team_key("Arsenal")
    away = team_key("Chelsea")

    corrected = dixon_coles_had(ratings, home, away, rho=D("-0.10"))
    assert abs(sum(corrected.values(), D(0)) - D(1)) <= D("1e-12")
    assert all(0 <= probability <= 1 for probability in corrected.values())

    neutral = dixon_coles_had(ratings, home, away, rho=D("0"))
    poisson = poisson_had(ratings, home, away)
    for outcome in ("H", "D", "A"):
        assert abs(neutral[outcome] - poisson[outcome]) <= D("1e-12")


def _overconfident_observations(
    count: int,
) -> list[tuple[dict[str, Decimal], str]]:
    probabilities = {"H": D("0.80"), "D": D("0.10"), "A": D("0.10")}
    return [(probabilities, "D") for _ in range(count)]


def test_temperature_scaling_improves_expected_log_loss():
    observations = _overconfident_observations(20)
    fitted = fit_temperature(observations, grid=(D("0.5"), D("1"), D("2"), D("3")))

    assert fitted >= D("1")
    before = sum(-observation[0][observation[1]].ln() for observation in observations)
    after = sum(
        -apply_temperature(observation[0], fitted)[observation[1]].ln()
        for observation in observations
    )
    assert after < before


def test_temperature_uses_only_the_predictions_it_is_given():
    validation = _overconfident_observations(10)
    fitted_validation = fit_temperature(
        validation, grid=(D("1"), D("2"), D("3"))
    )

    assert fitted_validation == D("3")


def _metrics_signature(
    metrics: BlockMetrics,
) -> tuple[int, Decimal | None, Decimal | None, int, Decimal | None]:
    return (
        metrics.matches,
        metrics.brier_model,
        metrics.log_loss_model,
        metrics.bets_placed,
        metrics.roi_model,
    )


def _run_small_experiments(rows: list[HistoricalMatchRow]):
    return run_experiments(
        rows,
        min_train=1,
        decay_grid=(D("0"), D("1")),
        rho_grid=(D("-0.10"), D("0")),
        temperature_grid=(D("0.5"), D("1"), D("2")),
    )


def test_hyperparameters_are_selected_without_reading_holdout_rows():
    rows = _dataset()
    before = _run_small_experiments(rows)

    holdout_rows = split_blocks(rows)[HOLDOUT_BLOCK]
    mutated_rows = [
        replace(row, home_goals_90=9, away_goals_90=0, result="H")
        if row in holdout_rows
        else row
        for row in rows
    ]
    after = _run_small_experiments(mutated_rows)

    assert {report.variant: report.selected_params for report in after} == {
        report.variant: report.selected_params for report in before
    }
    for old_report, new_report in zip(before, after, strict=True):
        assert _metrics_signature(old_report.validation) == _metrics_signature(
            new_report.validation
        )


def test_run_experiments_reports_all_variants_and_blocks():
    reports = _run_small_experiments(_dataset())

    assert [report.variant for report in reports] == [
        "poisson",
        "time_decay_poisson",
        "dixon_coles",
        "calibrated",
    ]
    for report in reports:
        assert report.train_matches == 72
        assert report.validation_matches == 24
        assert report.holdout_matches == 24
        assert report.validation.block == VALIDATION_BLOCK
        assert report.holdout.block == HOLDOUT_BLOCK
        assert report.validation.matches > 0
        assert report.holdout.matches > 0
        assert report.validation.brier_model is not None
        assert report.holdout.log_loss_model is not None
        assert set(report.selected_params) >= {
            "selection_block",
            "evaluation_block",
            "selection_metric",
        }
        assert report.selected_params["selection_block"] == "2024/25"
        assert report.selected_params["evaluation_block"] == "2025/26"


def test_predict_rows_skips_targets_before_min_train():
    rows = _dataset()
    first = sort_historical_rows(rows)[0]
    predictions = predict_rows(
        rows, predict_for=[first], variant="poisson", min_train=50
    )

    assert predictions == []


def test_block_metrics_handles_no_predictions():
    metrics = block_metrics([], block="validation")

    assert metrics.matches == 0
    assert metrics.brier_model is None
    assert metrics.log_loss_model is None
    assert metrics.roi_model is None
    assert dict(metrics.calibration) == {}


def test_experiment_prediction_is_immutable_mapping():
    rows = _dataset()
    validation_rows = split_blocks(rows)[VALIDATION_BLOCK]
    prediction = predict_rows(
        rows, predict_for=[validation_rows[0]], variant="poisson", min_train=1
    )[0]

    assert isinstance(prediction, ExperimentPrediction)
    mutable = cast(dict[str, Decimal], prediction.model)
    with pytest.raises(TypeError):
        mutable["H"] = D("1")
