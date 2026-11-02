from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import Match, ModelPrediction
from packages.domain.enums import MarketType, MatchStatus, Side
from packages.shared.time import ensure_utc

MODEL_VERSION = "poisson-v1"
DEFAULT_HOME_GOALS = Decimal("1.35")
DEFAULT_AWAY_GOALS = Decimal("1.15")
TAIL_MASS_TOLERANCE = Decimal("1e-6")
HAD_LINE_KEY = "0.0"

_HAD_OUTCOMES = (Side.H, Side.D, Side.A)


@dataclass(frozen=True)
class TeamStrength:
    attack: Decimal
    defense: Decimal


_NEUTRAL_STRENGTH = TeamStrength(attack=Decimal(1), defense=Decimal(1))


@dataclass(frozen=True)
class PoissonRatings:
    league_avg_home: Decimal
    league_avg_away: Decimal
    league_avg_goals: Decimal
    teams: Mapping[uuid.UUID, TeamStrength]
    model_version: str = MODEL_VERSION

    def strength(self, team_id: uuid.UUID) -> TeamStrength:
        return self.teams.get(team_id, _NEUTRAL_STRENGTH)


@dataclass(frozen=True)
class HadPrediction:
    p_home: Decimal
    p_draw: Decimal
    p_away: Decimal
    score_distribution: Mapping[tuple[int, int], Decimal]
    tail_mass: Decimal
    score_grid_max: int
    tail_handling: str
    model_version: str = MODEL_VERSION


def _goals(value: int | None) -> int:
    if value is None:
        raise ValueError("finished match is missing 90-minute goals")
    return value


def fit_poisson_ratings(
    session: Session,
    competition_id: uuid.UUID,
    *,
    as_of: datetime,
    prior_matches: float = 5.0,
) -> PoissonRatings:
    prior = Decimal(str(prior_matches))
    if not prior.is_finite() or prior < 0:
        raise ValueError("prior_matches must be a non-negative finite number")
    as_of_utc = ensure_utc(as_of)

    statement = select(Match).where(
        Match.competition_id == competition_id,
        Match.status == MatchStatus.FINISHED,
        Match.home_goals_90.is_not(None),
        Match.away_goals_90.is_not(None),
        Match.kickoff_at < as_of_utc,
    )
    matches = session.scalars(statement).all()

    if not matches:
        return PoissonRatings(
            league_avg_home=DEFAULT_HOME_GOALS,
            league_avg_away=DEFAULT_AWAY_GOALS,
            league_avg_goals=(DEFAULT_HOME_GOALS + DEFAULT_AWAY_GOALS) / Decimal(2),
            teams=MappingProxyType({}),
        )

    home_goals = [_goals(match.home_goals_90) for match in matches]
    away_goals = [_goals(match.away_goals_90) for match in matches]
    total_home_goals = sum(home_goals)
    total_away_goals = sum(away_goals)
    match_count = Decimal(len(matches))
    league_avg_home = Decimal(total_home_goals) / match_count
    league_avg_away = Decimal(total_away_goals) / match_count
    league_avg_goals = (league_avg_home + league_avg_away) / Decimal(2)

    stats: dict[uuid.UUID, list[int]] = {}
    for match, home_score, away_score in zip(matches, home_goals, away_goals, strict=True):
        home = stats.setdefault(match.home_team_id, [0, 0, 0])
        home[0] += home_score
        home[1] += away_score
        home[2] += 1
        away = stats.setdefault(match.away_team_id, [0, 0, 0])
        away[0] += away_score
        away[1] += home_score
        away[2] += 1

    if league_avg_goals <= 0:
        teams = {team_id: _NEUTRAL_STRENGTH for team_id in stats}
    else:
        teams = {}
        for team_id, (goals_for, goals_against, played) in stats.items():
            adjusted_for = (Decimal(goals_for) + prior * league_avg_goals) / (
                Decimal(played) + prior
            )
            adjusted_against = (Decimal(goals_against) + prior * league_avg_goals) / (
                Decimal(played) + prior
            )
            teams[team_id] = TeamStrength(
                attack=adjusted_for / league_avg_goals,
                defense=adjusted_against / league_avg_goals,
            )

    return PoissonRatings(
        league_avg_home=league_avg_home,
        league_avg_away=league_avg_away,
        league_avg_goals=league_avg_goals,
        teams=MappingProxyType(teams),
    )


def _poisson_pmf(goal_rate: float, max_goals: int) -> list[float]:
    pmf = [0.0] * (max_goals + 1)
    probability = math.exp(-goal_rate)
    pmf[0] = probability
    for goals in range(1, max_goals + 1):
        probability = probability * goal_rate / goals
        pmf[goals] = probability
    return pmf


def _validate_goal_rate(value: Decimal, side: str) -> None:
    if not value.is_finite() or value < 0:
        raise ValueError(f"{side} goal rate must be a finite non-negative Decimal")


def predict_had(
    ratings: PoissonRatings,
    home_team_id: uuid.UUID,
    away_team_id: uuid.UUID,
    *,
    max_goals: int = 10,
) -> HadPrediction:
    if max_goals < 0:
        raise ValueError("max_goals must be non-negative")

    home_strength = ratings.strength(home_team_id)
    away_strength = ratings.strength(away_team_id)
    lambda_home = ratings.league_avg_home * home_strength.attack * away_strength.defense
    lambda_away = ratings.league_avg_away * away_strength.attack * home_strength.defense
    _validate_goal_rate(lambda_home, "home")
    _validate_goal_rate(lambda_away, "away")

    home_pmf = _poisson_pmf(float(lambda_home), max_goals)
    away_pmf = _poisson_pmf(float(lambda_away), max_goals)

    float_cells: dict[tuple[int, int], float] = {}
    raw_total = 0.0
    for home_goals in range(max_goals + 1):
        for away_goals in range(max_goals + 1):
            value = home_pmf[home_goals] * away_pmf[away_goals]
            float_cells[(home_goals, away_goals)] = value
            raw_total += value

    tail_mass = Decimal(str(max(0.0, 1.0 - raw_total)))
    decimal_cells = {
        score: Decimal(str(value)) for score, value in float_cells.items()
    }
    decimal_total = sum(decimal_cells.values(), Decimal(0))
    if not decimal_total.is_finite() or decimal_total <= 0:
        raise ValueError("score distribution has no finite mass")

    distribution = {
        score: value / decimal_total for score, value in decimal_cells.items()
    }
    p_home = sum(
        (
            value
            for (home_goals, away_goals), value in distribution.items()
            if home_goals > away_goals
        ),
        Decimal(0),
    )
    p_draw = sum(
        (
            value
            for (home_goals, away_goals), value in distribution.items()
            if home_goals == away_goals
        ),
        Decimal(0),
    )
    p_away = sum(
        (
            value
            for (home_goals, away_goals), value in distribution.items()
            if home_goals < away_goals
        ),
        Decimal(0),
    )

    tail_handling = (
        "truncated_renormalized"
        if tail_mass > TAIL_MASS_TOLERANCE
        else "grid_complete"
    )
    return HadPrediction(
        p_home=p_home,
        p_draw=p_draw,
        p_away=p_away,
        score_distribution=MappingProxyType(distribution),
        tail_mass=tail_mass,
        score_grid_max=max_goals,
        tail_handling=tail_handling,
        model_version=ratings.model_version,
    )


def save_had_predictions(
    session: Session,
    *,
    match_id: uuid.UUID,
    prediction: HadPrediction,
    decision_at: datetime,
    analysis_run_key: str,
) -> list[ModelPrediction]:
    if not analysis_run_key.strip():
        raise ValueError("analysis_run_key must not be blank")

    existing_rows = session.scalars(
        select(ModelPrediction).where(
            ModelPrediction.analysis_run_key == analysis_run_key,
            ModelPrediction.market == MarketType.HAD,
            ModelPrediction.line_key == HAD_LINE_KEY,
            ModelPrediction.outcome.in_(_HAD_OUTCOMES),
        )
    ).all()
    rows_by_outcome = {row.outcome: row for row in existing_rows}
    missing = [
        outcome for outcome in _HAD_OUTCOMES if outcome not in rows_by_outcome
    ]

    if missing:
        score_distribution = {
            f"{home},{away}": str(value)
            for (home, away), value in sorted(prediction.score_distribution.items())
        }
        probabilities = {
            Side.H: prediction.p_home,
            Side.D: prediction.p_draw,
            Side.A: prediction.p_away,
        }
        decision_at_utc = ensure_utc(decision_at)
        for outcome in missing:
            row = ModelPrediction(
                match_id=match_id,
                market=MarketType.HAD,
                line_key=HAD_LINE_KEY,
                outcome=outcome,
                probability=probabilities[outcome],
                score_distribution=score_distribution,
                return_distribution=None,
                decision_at=decision_at_utc,
                model_version=prediction.model_version,
                analysis_run_key=analysis_run_key,
            )
            session.add(row)
            rows_by_outcome[outcome] = row
        session.flush()

    return [rows_by_outcome[outcome] for outcome in _HAD_OUTCOMES]
