from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from packages.adapters.football_data_co_uk import HistoricalMatchRow
from packages.backtest.experiments import (
    HOLDOUT_BLOCK,
    predict_rows,
    run_feature_experiments,
    split_blocks,
)
from packages.backtest.features import (
    ELO_HOME_ADVANTAGE,
    ELO_INITIAL,
    adjusted_had,
    elo_expected_home_score,
    elo_ratings,
)
from packages.backtest.models import fit_weighted_ratings, poisson_had, team_key

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
PAIRINGS = (
    ((0, 1), (2, 3)),
    ((0, 2), (1, 3)),
    ((0, 3), (1, 2)),
)


def _row(
    played_on: date,
    home_team: str,
    away_team: str,
    home_goals: int,
    away_goals: int,
    *,
    season_start_year: int = 2025,
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
        b365_home=D("2.10"),
        b365_draw=D("3.40"),
        b365_away=D("3.60"),
        ps_home=None,
        ps_draw=None,
        ps_away=None,
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
                )
            )
    return rows


def _dataset() -> list[HistoricalMatchRow]:
    rows: list[HistoricalMatchRow] = []
    for season in (2021, 2022, 2023, 2024, 2025):
        rows.extend(_season_rows(season))
    return rows


def test_elo_winner_gains_and_loser_loses():
    rows = [_row(date(2025, 8, 1), "Arsenal", "Chelsea", 3, 0)]

    ratings = elo_ratings(rows, as_of=date(2025, 8, 2))

    assert ratings["Arsenal"] > ELO_INITIAL
    assert ratings["Chelsea"] < ELO_INITIAL
    assert ratings["Arsenal"] - ELO_INITIAL == ELO_INITIAL - ratings["Chelsea"]


def test_elo_draw_with_home_advantage_moves_points_to_away_team():
    rows = [_row(date(2025, 8, 1), "Arsenal", "Chelsea", 1, 1)]

    ratings = elo_ratings(rows, as_of=date(2025, 8, 2))

    assert ratings["Arsenal"] < ELO_INITIAL
    assert ratings["Chelsea"] > ELO_INITIAL


def test_elo_home_advantage_raises_expected_home_score():
    neutral = elo_expected_home_score(ELO_INITIAL, ELO_INITIAL, home_advantage=D("0"))
    with_advantage = elo_expected_home_score(
        ELO_INITIAL, ELO_INITIAL, home_advantage=ELO_HOME_ADVANTAGE
    )

    assert neutral == D("0.5")
    assert with_advantage > neutral
    assert with_advantage < D("1")


def test_elo_uses_only_strictly_prior_dates():
    rows = [
        _row(date(2025, 8, 1), "Arsenal", "Chelsea", 3, 0),
        _row(date(2025, 8, 5), "Liverpool", "Everton", 1, 0),
        _row(date(2025, 8, 10), "Arsenal", "Liverpool", 4, 0),
    ]

    ratings = elo_ratings(rows, as_of=date(2025, 8, 5))

    assert set(ratings) == {"Arsenal", "Chelsea"}
    assert ratings["Arsenal"] > ELO_INITIAL
    assert ratings["Chelsea"] < ELO_INITIAL
    assert "Liverpool" not in ratings
    assert "Everton" not in ratings


def test_mutating_same_day_and_future_rows_keeps_pre_match_elo():
    rows = [
        _row(date(2025, 8, 1), "Arsenal", "Chelsea", 1, 1),
        _row(date(2025, 8, 5), "Liverpool", "Everton", 1, 0),
        _row(date(2025, 8, 10), "Arsenal", "Liverpool", 2, 0),
    ]
    before = elo_ratings(rows, as_of=date(2025, 8, 5))

    mutated = [
        replace(row, home_goals_90=9, away_goals_90=0, result="H")
        if row.played_on >= date(2025, 8, 5)
        else row
        for row in rows
    ]

    assert elo_ratings(mutated, as_of=date(2025, 8, 5)) == before


def _ratings():
    return fit_weighted_ratings(_dataset(), as_of=date(2025, 8, 1), decay=D("0"))


def test_zero_elo_scale_preserves_poisson_probabilities():
    ratings = _ratings()
    home = team_key("Arsenal")
    away = team_key("Chelsea")

    base = poisson_had(ratings, home, away)
    adjusted = adjusted_had(
        ratings,
        home,
        away,
        elo_home=D("1700"),
        elo_away=D("1300"),
        k_elo=D("0"),
        home_advantage=ELO_HOME_ADVANTAGE,
    )

    assert adjusted == base


def test_elo_adjustment_favours_the_higher_rated_home_team():
    ratings = _ratings()
    home = team_key("Arsenal")
    away = team_key("Chelsea")
    base = poisson_had(ratings, home, away)

    stronger_home = adjusted_had(
        ratings,
        home,
        away,
        elo_home=D("1650"),
        elo_away=D("1350"),
        k_elo=D("0.2"),
        home_advantage=ELO_HOME_ADVANTAGE,
    )
    stronger_away = adjusted_had(
        ratings,
        home,
        away,
        elo_home=D("1350"),
        elo_away=D("1650"),
        k_elo=D("0.2"),
        home_advantage=ELO_HOME_ADVANTAGE,
    )

    assert stronger_home["H"] > base["H"]
    assert stronger_home["A"] < base["A"]
    assert stronger_away["H"] < base["H"]
    assert stronger_away["A"] > base["A"]
    assert abs(sum(stronger_home.values(), D(0)) - D(1)) <= D("1e-12")


def test_rest_adjustment_favours_the_better_rested_home_team():
    ratings = _ratings()
    home = team_key("Arsenal")
    away = team_key("Chelsea")
    base = poisson_had(ratings, home, away)

    rested_home = adjusted_had(
        ratings,
        home,
        away,
        elo_home=ELO_INITIAL,
        elo_away=ELO_INITIAL,
        k_elo=D("0"),
        home_advantage=ELO_HOME_ADVANTAGE,
        rest_home=10,
        rest_away=3,
        k_rest=D("0.02"),
    )

    assert rested_home["H"] > base["H"]
    assert rested_home["A"] < base["A"]
    assert abs(sum(rested_home.values(), D(0)) - D(1)) <= D("1e-12")


def _run_small_feature_experiments(rows: list[HistoricalMatchRow]):
    return run_feature_experiments(
        rows,
        min_train=1,
        decay_grid=(D("0"), D("1")),
        k_elo_grid=(D("0"), D("0.2")),
        k_rest_grid=(D("0"), D("0.01")),
        temperature_grid=(D("0.5"), D("1"), D("2")),
    )


def test_feature_hyperparameters_are_selected_without_reading_holdout_rows():
    rows = _dataset()
    before = _run_small_feature_experiments(rows)

    holdout_rows = split_blocks(rows)[HOLDOUT_BLOCK]
    mutated_rows = [
        replace(row, home_goals_90=9, away_goals_90=0, result="H") if row in holdout_rows else row
        for row in rows
    ]
    after = _run_small_feature_experiments(mutated_rows)

    selected_before = {report.variant: report.selected_params for report in before}
    selected_after = {report.variant: report.selected_params for report in after}
    assert selected_after == selected_before
    for old_report, new_report in zip(before, after, strict=True):
        assert old_report.validation == new_report.validation


def test_feature_experiments_report_baselines_and_new_variants():
    reports = _run_small_feature_experiments(_dataset())

    variants = [report.variant for report in reports]
    assert variants == [
        "poisson",
        "time_decay_poisson",
        "dixon_coles",
        "calibrated",
        "elo_adjusted_poisson",
        "time_decay_elo",
        "rest_adjusted",
    ]
    for report in reports[4:]:
        assert report.validation.matches > 0
        assert report.holdout.matches > 0
        assert report.validation.brier_market is not None
        assert report.selected_params["selection_block"] == "2024/25"
        assert report.selected_params["evaluation_block"] == "2025/26"


def test_feature_predictions_ignore_same_day_and_future_rows():
    rows = _dataset()
    validation_rows = split_blocks(rows)[HOLDOUT_BLOCK]
    target = validation_rows[0]
    same_day = next(
        row for row in validation_rows if row.played_on == target.played_on and row != target
    )
    future = next(row for row in validation_rows if row.played_on > target.played_on)
    params = {
        "variant": "time_decay_elo",
        "decay": D("2"),
        "k_elo": D("0.2"),
        "min_train": 1,
    }
    baseline = predict_rows(rows, predict_for=[target], **params)[0]

    mutated_rows = [
        replace(row, home_goals_90=9, away_goals_90=0, result="H")
        if row in (same_day, future)
        else row
        for row in rows
    ]
    mutated = predict_rows(mutated_rows, predict_for=[target], **params)[0]

    assert mutated.model == baseline.model
