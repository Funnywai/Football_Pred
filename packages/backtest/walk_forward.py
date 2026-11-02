from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

from packages.adapters.football_data_co_uk import HistoricalMatchRow
from packages.models.poisson import (
    DEFAULT_AWAY_GOALS,
    DEFAULT_HOME_GOALS,
    MODEL_VERSION,
    PoissonRatings,
    TeamStrength,
    predict_had,
)

HAD_OUTCOMES: tuple[str, str, str] = ("H", "D", "A")
CALIBRATION_BINS = 10
# Log-loss needs a floor; the value is applied to a copy, never to the model output.
LOG_EPSILON = Decimal("1e-15")
MIN_EV = Decimal("0.03")


def team_id(team_name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, team_name)


def _as_of_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError("as_of must be a date or datetime")


def fit_historical_ratings(
    rows: Iterable[HistoricalMatchRow],
    *,
    as_of: date | datetime,
    prior_matches: float = 5.0,
) -> PoissonRatings:
    prior = Decimal(str(prior_matches))
    if not prior.is_finite() or prior < 0:
        raise ValueError("prior_matches must be a non-negative finite number")
    cutoff = _as_of_date(as_of)

    # Strictly prior dates only: same-day results are never visible to a prediction.
    completed = [row for row in rows if row.played_on < cutoff]
    if not completed:
        return PoissonRatings(
            league_avg_home=DEFAULT_HOME_GOALS,
            league_avg_away=DEFAULT_AWAY_GOALS,
            league_avg_goals=(DEFAULT_HOME_GOALS + DEFAULT_AWAY_GOALS) / Decimal(2),
            teams=MappingProxyType({}),
        )

    total_home_goals = sum(row.home_goals_90 for row in completed)
    total_away_goals = sum(row.away_goals_90 for row in completed)
    match_count = Decimal(len(completed))
    league_avg_home = Decimal(total_home_goals) / match_count
    league_avg_away = Decimal(total_away_goals) / match_count
    league_avg_goals = (league_avg_home + league_avg_away) / Decimal(2)

    stats: dict[uuid.UUID, list[int]] = {}
    for row in completed:
        home = stats.setdefault(team_id(row.home_team), [0, 0, 0])
        home[0] += row.home_goals_90
        home[1] += row.away_goals_90
        home[2] += 1
        away = stats.setdefault(team_id(row.away_team), [0, 0, 0])
        away[0] += row.away_goals_90
        away[1] += row.home_goals_90
        away[2] += 1

    if league_avg_goals <= 0:
        teams = {key: TeamStrength(attack=Decimal(1), defense=Decimal(1)) for key in stats}
    else:
        teams = {}
        for key, (goals_for, goals_against, played) in stats.items():
            adjusted_for = (Decimal(goals_for) + prior * league_avg_goals) / (
                Decimal(played) + prior
            )
            adjusted_against = (Decimal(goals_against) + prior * league_avg_goals) / (
                Decimal(played) + prior
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


def devig_had(
    home_odds: Decimal | None,
    draw_odds: Decimal | None,
    away_odds: Decimal | None,
) -> tuple[Decimal, Decimal, Decimal] | None:
    if home_odds is None or draw_odds is None or away_odds is None:
        return None
    odds = (home_odds, draw_odds, away_odds)
    for value in odds:
        if not value.is_finite() or value <= Decimal(1):
            return None

    implied = (Decimal(1) / odds[0], Decimal(1) / odds[1], Decimal(1) / odds[2])
    overround = implied[0] + implied[1] + implied[2]
    if not overround.is_finite() or overround <= 0:
        return None

    normalized = (implied[0] / overround, implied[1] / overround, implied[2] / overround)
    if abs(normalized[0] + normalized[1] + normalized[2] - Decimal(1)) > Decimal("1e-9"):
        return None
    return normalized


@dataclass(frozen=True)
class MarketQuote:
    bookmaker: str
    odds: tuple[Decimal, Decimal, Decimal]
    probabilities: tuple[Decimal, Decimal, Decimal]


def _complete_odds(
    odds: tuple[Decimal | None, Decimal | None, Decimal | None],
) -> tuple[Decimal, Decimal, Decimal] | None:
    if odds[0] is None or odds[1] is None or odds[2] is None:
        return None
    return (odds[0], odds[1], odds[2])


def market_had_quote(row: HistoricalMatchRow) -> MarketQuote | None:
    b365 = (row.b365_home, row.b365_draw, row.b365_away)
    b365_odds = _complete_odds(b365)
    if b365_odds is not None:
        probabilities = devig_had(*b365_odds)
        if probabilities is None:
            return None
        return MarketQuote("B365", b365_odds, probabilities)

    # A partial B365 quote is not a reason to fall back; only a fully absent one is.
    if b365 != (None, None, None):
        return None

    ps_odds = _complete_odds((row.ps_home, row.ps_draw, row.ps_away))
    if ps_odds is None:
        return None
    probabilities = devig_had(*ps_odds)
    if probabilities is None:
        return None
    return MarketQuote("PS", ps_odds, probabilities)


def _validate_probabilities(probabilities: Mapping[str, Decimal], actual: str) -> None:
    if actual not in HAD_OUTCOMES:
        raise ValueError("actual must be one of H, D, A")
    for outcome in HAD_OUTCOMES:
        if outcome not in probabilities:
            raise ValueError(f"probabilities missing outcome {outcome}")
        value = probabilities[outcome]
        if not value.is_finite() or value < 0 or value > 1:
            raise ValueError("probabilities must be finite and between 0 and 1")


def multiclass_brier(probabilities: Mapping[str, Decimal], actual: str) -> Decimal:
    _validate_probabilities(probabilities, actual)
    total = Decimal(0)
    for outcome in HAD_OUTCOMES:
        target = Decimal(1) if outcome == actual else Decimal(0)
        difference = probabilities[outcome] - target
        total += difference * difference
    return total


def multiclass_log_loss(probabilities: Mapping[str, Decimal], actual: str) -> Decimal:
    _validate_probabilities(probabilities, actual)
    probability = probabilities[actual]
    working = max(LOG_EPSILON, probability)
    return -working.ln()


@dataclass(frozen=True)
class CalibrationBin:
    bin_index: int
    count: int
    positives: int
    predicted_mean: Decimal
    observed_rate: Decimal


def calibration_bins(
    observations: Iterable[tuple[Mapping[str, Decimal], str]],
) -> dict[str, tuple[CalibrationBin, ...]]:
    predicted_sums: dict[str, dict[int, Decimal]] = {outcome: {} for outcome in HAD_OUTCOMES}
    counts: dict[str, dict[int, int]] = {outcome: {} for outcome in HAD_OUTCOMES}
    positives: dict[str, dict[int, int]] = {outcome: {} for outcome in HAD_OUTCOMES}

    for probabilities, actual in observations:
        _validate_probabilities(probabilities, actual)
        for outcome in HAD_OUTCOMES:
            probability = probabilities[outcome]
            index = min(int(probability * Decimal(CALIBRATION_BINS)), CALIBRATION_BINS - 1)
            predicted_sums[outcome][index] = (
                predicted_sums[outcome].get(index, Decimal(0)) + probability
            )
            counts[outcome][index] = counts[outcome].get(index, 0) + 1
            if outcome == actual:
                positives[outcome][index] = positives[outcome].get(index, 0) + 1

    table: dict[str, tuple[CalibrationBin, ...]] = {}
    for outcome in HAD_OUTCOMES:
        bins: list[CalibrationBin] = []
        for index in sorted(counts[outcome]):
            count = counts[outcome][index]
            hits = positives[outcome].get(index, 0)
            bins.append(
                CalibrationBin(
                    bin_index=index,
                    count=count,
                    positives=hits,
                    predicted_mean=predicted_sums[outcome][index] / Decimal(count),
                    observed_rate=Decimal(hits) / Decimal(count),
                )
            )
        if bins:
            table[outcome] = tuple(bins)
    return table


@dataclass(frozen=True)
class WalkForwardPrediction:
    row: HistoricalMatchRow
    model: Mapping[str, Decimal]
    market: Mapping[str, Decimal] | None
    market_odds: tuple[Decimal, Decimal, Decimal] | None


@dataclass(frozen=True)
class WalkForwardReport:
    matches_total: int
    matches_evaluated: int
    matches_skipped: int
    brier_model: Decimal | None
    brier_market: Decimal | None
    log_loss_model: Decimal | None
    log_loss_market: Decimal | None
    roi_model: Decimal | None
    calibration: Mapping[str, tuple[CalibrationBin, ...]]
    model_version: str = MODEL_VERSION
    matches_with_market: int = 0
    bets_placed: int = 0


def walk_forward_predictions(
    rows: Iterable[HistoricalMatchRow],
    *,
    min_train: int = 50,
    prior_matches: float = 5.0,
) -> list[WalkForwardPrediction]:
    if min_train < 0:
        raise ValueError("min_train must be non-negative")

    ordered = sorted(rows, key=lambda row: (row.played_on, row.home_team, row.away_team))
    predictions: list[WalkForwardPrediction] = []
    for index, row in enumerate(ordered):
        if index < min_train:
            continue
        ratings = fit_historical_ratings(
            ordered,
            as_of=row.played_on,
            prior_matches=prior_matches,
        )
        if not ratings.teams:
            continue
        prediction = predict_had(
            ratings,
            team_id(row.home_team),
            team_id(row.away_team),
        )
        model = {
            "H": prediction.p_home,
            "D": prediction.p_draw,
            "A": prediction.p_away,
        }
        quote = market_had_quote(row)
        market = None
        market_odds = None
        if quote is not None:
            market = {
                "H": quote.probabilities[0],
                "D": quote.probabilities[1],
                "A": quote.probabilities[2],
            }
            market_odds = quote.odds
        predictions.append(
            WalkForwardPrediction(
                row=row,
                model=model,
                market=market,
                market_odds=market_odds,
            )
        )
    return predictions


def _best_ev(
    probabilities: Mapping[str, Decimal],
    odds: tuple[Decimal, Decimal, Decimal],
) -> tuple[int, Decimal]:
    best_index = 0
    best_ev = probabilities[HAD_OUTCOMES[0]] * odds[0] - Decimal(1)
    for index in (1, 2):
        value = probabilities[HAD_OUTCOMES[index]] * odds[index] - Decimal(1)
        if value > best_ev:
            best_index = index
            best_ev = value
    return best_index, best_ev


def run_walk_forward(
    rows: Iterable[HistoricalMatchRow],
    *,
    min_train: int = 50,
    prior_matches: float = 5.0,
) -> WalkForwardReport:
    row_list = list(rows)
    predictions = walk_forward_predictions(
        row_list,
        min_train=min_train,
        prior_matches=prior_matches,
    )
    total = len(row_list)
    evaluated = len(predictions)
    if evaluated == 0:
        return WalkForwardReport(
            matches_total=total,
            matches_evaluated=0,
            matches_skipped=total,
            brier_model=None,
            brier_market=None,
            log_loss_model=None,
            log_loss_market=None,
            roi_model=None,
            calibration={},
        )

    observations: list[tuple[Mapping[str, Decimal], str]] = []
    brier_model_total = Decimal(0)
    log_loss_model_total = Decimal(0)
    brier_market_total = Decimal(0)
    log_loss_market_total = Decimal(0)
    market_count = 0
    total_stake = Decimal(0)
    total_payout = Decimal(0)
    bets_placed = 0

    for prediction in predictions:
        actual = prediction.row.result
        observations.append((prediction.model, actual))
        brier_model_total += multiclass_brier(prediction.model, actual)
        log_loss_model_total += multiclass_log_loss(prediction.model, actual)

        if prediction.market is None or prediction.market_odds is None:
            continue
        market_count += 1
        brier_market_total += multiclass_brier(prediction.market, actual)
        log_loss_market_total += multiclass_log_loss(prediction.market, actual)

        best_index, best_ev = _best_ev(prediction.model, prediction.market_odds)
        if best_ev < MIN_EV:
            continue
        bets_placed += 1
        total_stake += Decimal(1)
        if actual == HAD_OUTCOMES[best_index]:
            total_payout += prediction.market_odds[best_index]

    return WalkForwardReport(
        matches_total=total,
        matches_evaluated=evaluated,
        matches_skipped=total - evaluated,
        brier_model=brier_model_total / Decimal(evaluated),
        brier_market=(
            brier_market_total / Decimal(market_count) if market_count > 0 else None
        ),
        log_loss_model=log_loss_model_total / Decimal(evaluated),
        log_loss_market=(
            log_loss_market_total / Decimal(market_count) if market_count > 0 else None
        ),
        roi_model=(
            (total_payout - total_stake) / total_stake if total_stake > 0 else None
        ),
        calibration=calibration_bins(observations),
        model_version=MODEL_VERSION,
        matches_with_market=market_count,
        bets_placed=bets_placed,
    )
