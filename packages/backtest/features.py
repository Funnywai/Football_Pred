from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

from packages.adapters.football_data_co_uk import HistoricalMatchRow
from packages.backtest.models import DEFAULT_MAX_GOALS, ZERO
from packages.models.poisson import PoissonRatings, predict_had

ELO_INITIAL = Decimal(1500)
ELO_K = Decimal(20)
ELO_HOME_ADVANTAGE = Decimal(60)
ELO_SCALE = Decimal(400)
LN10 = Decimal("2.302585092994045684017991454684364")
DRAW_SCORE = Decimal("0.5")
WIN_SCORE = Decimal(1)
LOSS_SCORE = Decimal(0)
REST_DAYS_PER_UNIT = Decimal(7)


def _as_of_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def _ordered(rows: Iterable[HistoricalMatchRow]) -> list[HistoricalMatchRow]:
    return sorted(
        rows,
        key=lambda row: (row.played_on, row.home_team, row.away_team),
    )


def _result_score(result: str) -> Decimal:
    if result == "H":
        return WIN_SCORE
    if result == "D":
        return DRAW_SCORE
    if result == "A":
        return LOSS_SCORE
    raise ValueError(f"unknown result {result!r}")


def elo_expected_home_score(
    elo_home: Decimal | float | str,
    elo_away: Decimal | float | str,
    *,
    home_advantage: Decimal | float | str = ELO_HOME_ADVANTAGE,
) -> Decimal:
    """Standard Elo expectation with the home advantage folded into the rating gap."""
    advantage = Decimal(str(home_advantage))
    difference = (Decimal(str(elo_home)) + advantage - Decimal(str(elo_away))) / ELO_SCALE
    # 10 ** (-x) expressed through exp/ln keeps the whole calculation in Decimal.
    exponent = (-difference * LN10).exp()
    return Decimal(1) / (Decimal(1) + exponent)


def elo_ratings(
    rows: Iterable[HistoricalMatchRow],
    *,
    as_of: date | datetime,
    k: Decimal | float | str = ELO_K,
    home_advantage: Decimal | float | str = ELO_HOME_ADVANTAGE,
    initial: Decimal | float | str = ELO_INITIAL,
) -> Mapping[str, Decimal]:
    """Pre-match Elo ratings from results strictly before ``as_of``.

    Same-day matches are excluded so a prediction never sees the result it is
    trying to forecast.
    """
    k_value = Decimal(str(k))
    initial_value = Decimal(str(initial))
    cutoff = _as_of_date(as_of)
    ratings: dict[str, Decimal] = {}
    for row in _ordered(rows):
        if row.played_on >= cutoff:
            continue
        home_rating = ratings.get(row.home_team, initial_value)
        away_rating = ratings.get(row.away_team, initial_value)
        expected = elo_expected_home_score(home_rating, away_rating, home_advantage=home_advantage)
        delta = k_value * (_result_score(row.result) - expected)
        ratings[row.home_team] = home_rating + delta
        ratings[row.away_team] = away_rating - delta
    return MappingProxyType(ratings)


def elo_rating(
    ratings: Mapping[str, Decimal],
    team: str,
    *,
    initial: Decimal | float | str = ELO_INITIAL,
) -> Decimal:
    return ratings.get(team, Decimal(str(initial)))


def rest_days(
    rows: Iterable[HistoricalMatchRow],
    team: str,
    *,
    as_of: date | datetime,
) -> int | None:
    """Days since the team's last match strictly before ``as_of``."""
    cutoff = _as_of_date(as_of)
    played = [
        row.played_on
        for row in rows
        if row.played_on < cutoff and team in (row.home_team, row.away_team)
    ]
    if not played:
        return None
    return (cutoff - max(played)).days


def _elo_factors(
    *,
    elo_home: Decimal,
    elo_away: Decimal,
    k_elo: Decimal,
    home_advantage: Decimal,
) -> tuple[Decimal, Decimal]:
    difference = (elo_home + home_advantage - elo_away) / ELO_SCALE
    return (k_elo * difference).exp(), (-k_elo * difference).exp()


def _rest_factors(
    *,
    rest_home: int | None,
    rest_away: int | None,
    k_rest: Decimal,
) -> tuple[Decimal, Decimal]:
    if rest_home is None or rest_away is None or k_rest == ZERO:
        return Decimal(1), Decimal(1)
    difference = Decimal(rest_home - rest_away) / REST_DAYS_PER_UNIT
    factor = (k_rest * difference).exp()
    return factor, Decimal(1) / factor


def adjusted_had(
    ratings: PoissonRatings,
    home_team_id: uuid.UUID,
    away_team_id: uuid.UUID,
    *,
    elo_home: Decimal | float | str,
    elo_away: Decimal | float | str,
    k_elo: Decimal | float | str,
    home_advantage: Decimal | float | str = ELO_HOME_ADVANTAGE,
    rest_home: int | None = None,
    rest_away: int | None = None,
    k_rest: Decimal | float | str = ZERO,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> dict[str, Decimal]:
    """Poisson HAD with Elo and optional rest factors applied to the goal rates.

    ``league_avg_home`` and ``league_avg_away`` are the only multiplicative
    entries in the Poisson goal rates, so scaling them applies the feature
    without touching the fitted team strengths.
    """
    home_factor, away_factor = _elo_factors(
        elo_home=Decimal(str(elo_home)),
        elo_away=Decimal(str(elo_away)),
        k_elo=Decimal(str(k_elo)),
        home_advantage=Decimal(str(home_advantage)),
    )
    rest_home_factor, rest_away_factor = _rest_factors(
        rest_home=rest_home,
        rest_away=rest_away,
        k_rest=Decimal(str(k_rest)),
    )
    scaled = replace(
        ratings,
        league_avg_home=ratings.league_avg_home * home_factor * rest_home_factor,
        league_avg_away=ratings.league_avg_away * away_factor * rest_away_factor,
    )
    prediction = predict_had(scaled, home_team_id, away_team_id, max_goals=max_goals)
    return {
        "H": prediction.p_home,
        "D": prediction.p_draw,
        "A": prediction.p_away,
    }
