from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

from packages.adapters.football_data_co_uk import HistoricalMatchRow
from packages.backtest.walk_forward import HAD_OUTCOMES, multiclass_log_loss
from packages.models.poisson import (
    DEFAULT_AWAY_GOALS,
    DEFAULT_HOME_GOALS,
    PoissonRatings,
    TeamStrength,
    predict_had,
)

DEFAULT_MAX_GOALS = 10
DAYS_PER_YEAR = Decimal(365)
ZERO = Decimal(0)
DEFAULT_TEMPERATURE_GRID: tuple[Decimal, ...] = (
    Decimal("0.50"),
    Decimal("0.60"),
    Decimal("0.70"),
    Decimal("0.80"),
    Decimal("0.90"),
    Decimal("1.00"),
    Decimal("1.10"),
    Decimal("1.20"),
    Decimal("1.30"),
    Decimal("1.40"),
    Decimal("1.50"),
    Decimal("1.75"),
    Decimal("2.00"),
    Decimal("2.50"),
    Decimal("3.00"),
)


def _as_of_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def _empty_ratings() -> PoissonRatings:
    return PoissonRatings(
        league_avg_home=DEFAULT_HOME_GOALS,
        league_avg_away=DEFAULT_AWAY_GOALS,
        league_avg_goals=(DEFAULT_HOME_GOALS + DEFAULT_AWAY_GOALS) / Decimal(2),
        teams=MappingProxyType({}),
    )


def fit_weighted_ratings(
    rows: Iterable[HistoricalMatchRow],
    *,
    as_of: date | datetime,
    prior_matches: float = 5.0,
    decay: Decimal | float | str = ZERO,
) -> PoissonRatings:
    """Poisson ratings with an exponential recency weight per match.

    A weight of exp(-decay * age_days / 365) multiplies every goal count, so the
    prior pseudo-counts stay fixed while recent results dominate the posterior.
    """
    prior = Decimal(str(prior_matches))
    if not prior.is_finite() or prior < 0:
        raise ValueError("prior_matches must be a non-negative finite number")
    decay_value = Decimal(str(decay))
    if not decay_value.is_finite() or decay_value < 0:
        raise ValueError("decay must be a non-negative finite number")

    cutoff = _as_of_date(as_of)
    # Strictly prior dates only: same-day results are never visible to a prediction.
    completed = [row for row in rows if row.played_on < cutoff]
    if not completed:
        return _empty_ratings()

    weighted: list[tuple[HistoricalMatchRow, Decimal]] = []
    for row in completed:
        age_days = Decimal((cutoff - row.played_on).days)
        weight = (-decay_value * age_days / DAYS_PER_YEAR).exp()
        weighted.append((row, weight))

    total_weight = sum((weight for _, weight in weighted), Decimal(0))
    if not total_weight.is_finite() or total_weight <= 0:
        return _empty_ratings()

    weighted_home_goals = sum(
        (Decimal(row.home_goals_90) * weight for row, weight in weighted), Decimal(0)
    )
    weighted_away_goals = sum(
        (Decimal(row.away_goals_90) * weight for row, weight in weighted), Decimal(0)
    )
    league_avg_home = weighted_home_goals / total_weight
    league_avg_away = weighted_away_goals / total_weight
    league_avg_goals = (league_avg_home + league_avg_away) / Decimal(2)

    stats: dict[uuid.UUID, list[Decimal]] = {}
    for row, weight in weighted:
        home_goals = Decimal(row.home_goals_90)
        away_goals = Decimal(row.away_goals_90)
        home = stats.setdefault(team_key(row.home_team), [Decimal(0)] * 3)
        home[0] += home_goals * weight
        home[1] += away_goals * weight
        home[2] += weight
        away = stats.setdefault(team_key(row.away_team), [Decimal(0)] * 3)
        away[0] += away_goals * weight
        away[1] += home_goals * weight
        away[2] += weight

    if league_avg_goals <= 0:
        teams = {key: TeamStrength(attack=Decimal(1), defense=Decimal(1)) for key in stats}
    else:
        teams = {}
        for key, (goals_for, goals_against, played) in stats.items():
            adjusted_for = (goals_for + prior * league_avg_goals) / (played + prior)
            adjusted_against = (goals_against + prior * league_avg_goals) / (
                played + prior
            )
            teams[key] = TeamStrength(
                attack=adjusted_for / league_avg_goals,
                defense=adjusted_against / league_avg_goals,
            )

    return PoissonRatings(
        league_avg_home=league_avg_home,
        league_avg_away=league_avg_away,
        league_avg_goals=league_avg_goals,
        teams=MappingProxyType(teams),
    )


def team_key(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, name)


def goal_rates(
    ratings: PoissonRatings,
    home_team_id: uuid.UUID,
    away_team_id: uuid.UUID,
) -> tuple[Decimal, Decimal]:
    home_strength = ratings.strength(home_team_id)
    away_strength = ratings.strength(away_team_id)
    lambda_home = ratings.league_avg_home * home_strength.attack * away_strength.defense
    lambda_away = ratings.league_avg_away * away_strength.attack * home_strength.defense
    return lambda_home, lambda_away


def poisson_had(
    ratings: PoissonRatings,
    home_team_id: uuid.UUID,
    away_team_id: uuid.UUID,
    *,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> dict[str, Decimal]:
    prediction = predict_had(
        ratings, home_team_id, away_team_id, max_goals=max_goals
    )
    return {
        "H": prediction.p_home,
        "D": prediction.p_draw,
        "A": prediction.p_away,
    }


def _dixon_coles_tau(
    home_goals: int,
    away_goals: int,
    lambda_home: Decimal,
    lambda_away: Decimal,
    rho: Decimal,
) -> Decimal:
    if home_goals == 0 and away_goals == 0:
        return Decimal(1) - lambda_home * lambda_away * rho
    if home_goals == 0 and away_goals == 1:
        return Decimal(1) + lambda_home * rho
    if home_goals == 1 and away_goals == 0:
        return Decimal(1) + lambda_away * rho
    if home_goals == 1 and away_goals == 1:
        return Decimal(1) - rho
    return Decimal(1)


def dixon_coles_had(
    ratings: PoissonRatings,
    home_team_id: uuid.UUID,
    away_team_id: uuid.UUID,
    *,
    rho: Decimal | float | str,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> dict[str, Decimal]:
    """Poisson score grid with the Dixon-Coles low-score dependence correction."""
    rho_value = Decimal(str(rho))
    if not rho_value.is_finite():
        raise ValueError("rho must be finite")

    prediction = predict_had(
        ratings, home_team_id, away_team_id, max_goals=max_goals
    )
    lambda_home, lambda_away = goal_rates(ratings, home_team_id, away_team_id)

    adjusted: dict[tuple[int, int], Decimal] = {}
    total = Decimal(0)
    for (home_goals, away_goals), probability in prediction.score_distribution.items():
        tau = _dixon_coles_tau(
            home_goals, away_goals, lambda_home, lambda_away, rho_value
        )
        if tau < 0:
            tau = Decimal(0)
        value = probability * tau
        adjusted[(home_goals, away_goals)] = value
        total += value

    if not total.is_finite() or total <= 0:
        raise ValueError("Dixon-Coles score distribution has no finite mass")

    distribution = {score: value / total for score, value in adjusted.items()}
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
    return {"H": p_home, "D": p_draw, "A": p_away}


def apply_temperature(
    probabilities: Mapping[str, Decimal],
    temperature: Decimal | float | str,
) -> dict[str, Decimal]:
    """Power temperature scaling: p_i ** (1 / T), renormalized.

    T > 1 softens overconfident probabilities and T < 1 sharpens them.
    """
    temperature_value = Decimal(str(temperature))
    if not temperature_value.is_finite() or temperature_value <= 0:
        raise ValueError("temperature must be a positive finite number")

    scaled: dict[str, Decimal] = {}
    total = Decimal(0)
    for outcome in HAD_OUTCOMES:
        if outcome not in probabilities:
            raise ValueError(f"probabilities missing outcome {outcome}")
        probability = probabilities[outcome]
        if not probability.is_finite() or probability < 0 or probability > 1:
            raise ValueError("probabilities must be finite and between 0 and 1")
        if probability <= 0:
            value = Decimal(0)
        else:
            value = (probability.ln() / temperature_value).exp()
        scaled[outcome] = value
        total += value

    if total <= 0:
        uniform = Decimal(1) / Decimal(len(HAD_OUTCOMES))
        return {outcome: uniform for outcome in HAD_OUTCOMES}
    return {outcome: value / total for outcome, value in scaled.items()}


def fit_temperature(
    observations: Iterable[tuple[Mapping[str, Decimal], str]],
    *,
    grid: Sequence[Decimal] = DEFAULT_TEMPERATURE_GRID,
) -> Decimal:
    """Grid-search the temperature with the lowest validation log-loss."""
    materialized = list(observations)
    if not materialized:
        return Decimal(1)

    best_temperature = Decimal(1)
    best_loss: Decimal | None = None
    for temperature in grid:
        total = Decimal(0)
        for probabilities, actual in materialized:
            scaled = apply_temperature(probabilities, temperature)
            total += multiclass_log_loss(scaled, actual)
        loss = total / Decimal(len(materialized))
        if best_loss is None or loss < best_loss:
            best_loss = loss
            best_temperature = Decimal(str(temperature))
    return best_temperature

