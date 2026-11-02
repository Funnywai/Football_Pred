from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.db.models import Match, ModelPrediction
from packages.domain.enums import MarketType, MatchStatus, Side
from packages.models.poisson import (
    DEFAULT_AWAY_GOALS,
    DEFAULT_HOME_GOALS,
    MODEL_VERSION,
    PoissonRatings,
    fit_poisson_ratings,
    predict_had,
    save_had_predictions,
)

D = Decimal
AS_OF = datetime(2026, 9, 1, tzinfo=UTC)
KICKOFF = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)


def _add_match(
    session: Session,
    competition_id: uuid.UUID,
    home_team_id: uuid.UUID,
    away_team_id: uuid.UUID,
    home_goals: int,
    away_goals: int,
    *,
    kickoff: datetime = KICKOFF,
) -> None:
    match = Match(
        competition_id=competition_id,
        season="2025/26",
        kickoff_at=kickoff,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        status=MatchStatus.FINISHED,
        home_goals_90=home_goals,
        away_goals_90=away_goals,
        source_match_ids={},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()


def test_no_history_uses_default_league_averages(session: Session):
    ratings = fit_poisson_ratings(session, uuid.uuid4(), as_of=AS_OF)

    assert ratings.league_avg_home == DEFAULT_HOME_GOALS
    assert ratings.league_avg_away == DEFAULT_AWAY_GOALS
    assert ratings.model_version == MODEL_VERSION

    prediction = predict_had(ratings, uuid.uuid4(), uuid.uuid4())
    total = prediction.p_home + prediction.p_draw + prediction.p_away

    assert abs(total - D(1)) <= D("1e-9")
    for probability in (prediction.p_home, prediction.p_draw, prediction.p_away):
        assert probability.is_finite()
        assert D(0) <= probability <= D(1)
    assert prediction.model_version == MODEL_VERSION


def test_synthetic_results_shift_strength_in_expected_direction(session: Session):
    competition_id = uuid.uuid4()
    strong = uuid.uuid4()
    weak = uuid.uuid4()
    _add_match(session, competition_id, strong, weak, 5, 0)
    _add_match(session, competition_id, weak, strong, 0, 5)

    ratings = fit_poisson_ratings(session, competition_id, as_of=AS_OF)

    assert ratings.teams[strong].attack > ratings.teams[weak].attack
    assert ratings.teams[strong].defense < ratings.teams[weak].defense

    strong_home = predict_had(ratings, strong, weak)
    weak_home = predict_had(ratings, weak, strong)

    assert strong_home.p_home > weak_home.p_home
    assert strong_home.p_home > strong_home.p_away


def test_unknown_team_uses_neutral_strength(session: Session):
    ratings = fit_poisson_ratings(session, uuid.uuid4(), as_of=AS_OF)
    neutral = ratings.strength(uuid.uuid4())

    assert neutral.attack == D(1)
    assert neutral.defense == D(1)


def test_score_grid_is_normalized_and_tail_is_recorded(session: Session):
    ratings = fit_poisson_ratings(session, uuid.uuid4(), as_of=AS_OF)
    prediction = predict_had(ratings, uuid.uuid4(), uuid.uuid4())

    assert len(prediction.score_distribution) == 121
    assert prediction.score_grid_max == 10
    assert {(0, 0), (10, 10)} <= set(prediction.score_distribution)

    total = sum(prediction.score_distribution.values(), D(0))
    assert abs(total - D(1)) <= D("1e-9")
    assert prediction.tail_mass >= D(0)

    expected_tail_handling = (
        "truncated_renormalized"
        if prediction.tail_mass > D("1e-6")
        else "grid_complete"
    )
    assert prediction.tail_handling == expected_tail_handling


def test_zero_probability_outcomes_are_not_clipped():
    ratings = PoissonRatings(
        league_avg_home=D("2.0"),
        league_avg_away=D("0"),
        league_avg_goals=D("1.0"),
        teams={},
    )
    prediction = predict_had(ratings, uuid.uuid4(), uuid.uuid4())

    assert prediction.p_away == D(0)
    assert prediction.score_distribution[(0, 1)] == D(0)
    assert prediction.p_home > D(0)
    assert abs(prediction.p_home + prediction.p_draw + prediction.p_away - D(1)) <= D("1e-9")


def test_save_had_predictions_creates_three_rows_and_is_idempotent(session: Session):
    match_id = uuid.uuid4()
    ratings = fit_poisson_ratings(session, uuid.uuid4(), as_of=AS_OF)
    prediction = predict_had(ratings, uuid.uuid4(), uuid.uuid4())

    first = save_had_predictions(
        session,
        match_id=match_id,
        prediction=prediction,
        decision_at=AS_OF,
        analysis_run_key="run-1",
    )

    assert len(first) == 3
    assert {row.outcome for row in first} == {Side.H, Side.D, Side.A}
    assert session.scalar(select(func.count()).select_from(ModelPrediction)) == 3

    for row in first:
        assert row.match_id == match_id
        assert row.market is MarketType.HAD
        assert row.line_key == "0.0"
        assert row.return_distribution is None
        assert row.model_version == MODEL_VERSION
        assert row.analysis_run_key == "run-1"
        assert len(row.score_distribution) == 121
        assert isinstance(row.score_distribution["0,0"], str)

    second = save_had_predictions(
        session,
        match_id=match_id,
        prediction=prediction,
        decision_at=AS_OF,
        analysis_run_key="run-1",
    )

    assert [row.id for row in second] == [row.id for row in first]
    assert session.scalar(select(func.count()).select_from(ModelPrediction)) == 3
