from __future__ import annotations

import argparse
import json
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import create_engine, text

from packages.adapters.football_data_co_uk import HistoricalMatchRow
from packages.backtest.walk_forward import (
    HAD_OUTCOMES,
    MIN_EV,
    calibration_bins,
    devig_had,
    fit_historical_ratings,
    multiclass_brier,
    multiclass_log_loss,
)
from packages.models.poisson import predict_had

D = Decimal


@dataclass(frozen=True)
class LegacyMatch:
    match_id: int
    kickoff_at: datetime
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int


def season_start_year(day: date) -> int:
    return day.year if day.month >= 7 else day.year - 1


def result_code(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = D(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed <= D(1):
        return None
    return parsed


def parse_b365_close(payload: object) -> dict[str, Decimal] | None:
    if not isinstance(payload, dict):
        return None
    odds = payload.get("odds")
    if not isinstance(odds, dict):
        return None
    b365 = odds.get("B365")
    if not isinstance(b365, dict):
        return None
    close = b365.get("close")
    if not isinstance(close, list) or len(close) != 3:
        return None
    values = [_decimal(value) for value in close]
    if any(value is None for value in values):
        return None
    home, draw, away = values
    assert home is not None and draw is not None and away is not None
    return {"H": home, "D": draw, "A": away}


def _query_results(engine: Any) -> list[LegacyMatch]:
    statement = text(
        """
        SELECT
            m.id,
            m.kickoff_time,
            home.name_en AS home_team,
            away.name_en AS away_team,
            r.home_score,
            r.away_score
        FROM matches m
        JOIN leagues league ON league.id = m.league_id
        JOIN teams home ON home.id = m.home_team_id
        JOIN teams away ON away.id = m.away_team_id
        JOIN results r ON r.match_id = m.id AND r.confirmed = true
        WHERE league.code = 'EPL'
        ORDER BY m.kickoff_time, m.id
        """
    )
    with engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()
    return [
        LegacyMatch(
            match_id=int(row["id"]),
            kickoff_at=row["kickoff_time"],
            home_team=str(row["home_team"]),
            away_team=str(row["away_team"]),
            home_goals=int(row["home_score"]),
            away_goals=int(row["away_score"]),
        )
        for row in rows
    ]


def _query_b365_close(engine: Any) -> dict[int, dict[str, Decimal]]:
    statement = text(
        """
        SELECT DISTINCT ON (os.match_id)
            os.match_id,
            os.payload
        FROM odds_snapshots os
        JOIN matches m ON m.id = os.match_id
        JOIN leagues league ON league.id = m.league_id
        WHERE league.code = 'EPL'
          AND os.source = 'football_data'
          AND os.odds_type = 'HAD'
          AND os.inplay = false
          AND (os.payload->'odds'->'B365'->'close')::text NOT LIKE '%null%'
        ORDER BY os.match_id, os.captured_at DESC
        """
    )
    with engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()
    quotes: dict[int, dict[str, Decimal]] = {}
    for row in rows:
        parsed = parse_b365_close(row["payload"])
        if parsed is not None:
            quotes[int(row["match_id"])] = parsed
    return quotes


def _historical_row(match: LegacyMatch) -> HistoricalMatchRow:
    played_on = match.kickoff_at.date()
    return HistoricalMatchRow(
        competition_code="EPL",
        season_start_year=season_start_year(played_on),
        played_on=played_on,
        kickoff_time=None,
        home_team=match.home_team,
        away_team=match.away_team,
        home_goals_90=match.home_goals,
        away_goals_90=match.away_goals,
        result=result_code(match.home_goals, match.away_goals),
        b365_home=None,
        b365_draw=None,
        b365_away=None,
        ps_home=None,
        ps_draw=None,
        ps_away=None,
    )


@dataclass
class _SeasonMetrics:
    matches: int = 0
    bets: int = 0
    stake: Decimal = field(default_factory=Decimal)
    payout: Decimal = field(default_factory=Decimal)
    brier_model: Decimal = field(default_factory=Decimal)
    brier_market: Decimal = field(default_factory=Decimal)
    log_loss_model: Decimal = field(default_factory=Decimal)
    log_loss_market: Decimal = field(default_factory=Decimal)


def _season_label(day: date) -> str:
    start = season_start_year(day)
    return f"{start}/{str(start + 1)[-2:]}"


def run_backtest(engine: Any) -> dict[str, object]:
    matches = _query_results(engine)
    quotes = _query_b365_close(engine)
    by_date: dict[date, list[LegacyMatch]] = defaultdict(list)
    for match in matches:
        by_date[match.kickoff_at.date()].append(match)

    total = _SeasonMetrics()
    by_season: dict[str, _SeasonMetrics] = defaultdict(_SeasonMetrics)
    observations: list[tuple[dict[str, Decimal], str]] = []
    model_rows: list[HistoricalMatchRow] = []

    for played_on in sorted(by_date):
        ratings = fit_historical_ratings(model_rows, as_of=played_on)
        for match in by_date[played_on]:
            quote = quotes.get(match.match_id)
            if quote is None:
                continue
            prediction = predict_had(
                ratings,
                uuid.uuid5(uuid.NAMESPACE_URL, match.home_team),
                uuid.uuid5(uuid.NAMESPACE_URL, match.away_team),
            )
            probabilities = {
                "H": prediction.p_home,
                "D": prediction.p_draw,
                "A": prediction.p_away,
            }
            market = devig_had(quote["H"], quote["D"], quote["A"])
            if market is None:
                continue
            market_map = {"H": market[0], "D": market[1], "A": market[2]}
            actual = result_code(match.home_goals, match.away_goals)
            observations.append((probabilities, actual))
            brier_model = multiclass_brier(probabilities, actual)
            brier_market = multiclass_brier(market_map, actual)
            log_loss_model = multiclass_log_loss(probabilities, actual)
            log_loss_market = multiclass_log_loss(market_map, actual)

            best_outcome = HAD_OUTCOMES[0]
            best_ev = probabilities["H"] * quote["H"] - D(1)
            for outcome in HAD_OUTCOMES[1:]:
                value = probabilities[outcome] * quote[outcome] - D(1)
                if value > best_ev:
                    best_ev = value
                    best_outcome = outcome
            bet = best_ev >= MIN_EV
            payout = (
                quote[best_outcome]
                if bet and actual == best_outcome
                else D(0)
            )

            season = _season_label(played_on)
            for bucket in (total, by_season[season]):
                bucket.matches += 1
                bucket.brier_model += brier_model
                bucket.brier_market += brier_market
                bucket.log_loss_model += log_loss_model
                bucket.log_loss_market += log_loss_market
                if bet:
                    bucket.bets += 1
                    bucket.stake += D(1)
                    bucket.payout += payout

        model_rows.extend(_historical_row(match) for match in by_date[played_on])

    def summary(metrics: _SeasonMetrics) -> dict[str, object]:
        count = D(metrics.matches) if metrics.matches else D(1)
        return {
            "matches": metrics.matches,
            "brier_model": str(metrics.brier_model / count),
            "brier_market": str(metrics.brier_market / count),
            "log_loss_model": str(metrics.log_loss_model / count),
            "log_loss_market": str(metrics.log_loss_market / count),
            "bets": metrics.bets,
            "roi": str((metrics.payout - metrics.stake) / metrics.stake)
            if metrics.stake > D(0)
            else None,
        }

    return {
        "source": "legacy football_data B365 closing",
        "matches_total": len(matches),
        "matches_with_market": len(quotes),
        "matches_evaluated": total.matches,
        "overall": summary(total),
        "by_season": {
            season: summary(metrics)
            for season, metrics in sorted(by_season.items())
        },
        "calibration": {
            outcome: [
                {
                    "bin": item.bin_index,
                    "count": item.count,
                    "predicted_mean": str(item.predicted_mean),
                    "observed_rate": str(item.observed_rate),
                }
                for item in bins
            ]
            for outcome, bins in calibration_bins(observations).items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="EPL HAD walk-forward using legacy football_data B365 closing odds."
    )
    parser.add_argument(
        "--legacy-url",
        default=os.environ.get("LEGACY_DATABASE_URL"),
        help="SQLAlchemy URL for football_pred_legacy (or LEGACY_DATABASE_URL).",
    )
    args = parser.parse_args()
    if not args.legacy_url:
        parser.error("--legacy-url or LEGACY_DATABASE_URL is required")
    engine = create_engine(args.legacy_url, pool_pre_ping=True, future=True)
    try:
        report = run_backtest(engine)
    finally:
        engine.dispose()
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
