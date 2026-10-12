"""Training dataset assembly: DB rows -> feature frame -> temporal split."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import League, Match, OddsSnapshot, Result, Season
from app.ml.deviq import devig_multiplicative
from app.ml.features import (
    FEATURE_VERSION,
    MarketPrior,
    MatchRow,
    build_feature_rows,
    football_data_close_odds,
    hkjc_had_odds,
    hkjc_hdc_main,
)
from app.ml.labels import handicap_label, label_1x2

CALIBRATION_FRACTION = 0.1
EVAL_FRACTION = 0.2
MIN_DATASET_ROWS = 10


@dataclass
class Dataset:
    train: pd.DataFrame
    calibration: pd.DataFrame
    eval: pd.DataFrame
    feature_version: str = FEATURE_VERSION


async def load_training_rows(
    session: AsyncSession,
    settings: Settings,
    before: datetime | None = None,
) -> list[MatchRow]:
    """Confirmed results from the configured history window, oldest first."""
    stmt = (
        select(Match, Result, League.code, Season.label)
        .join(Result, Result.match_id == Match.id)
        .join(League, League.id == Match.league_id)
        .join(Season, Season.id == Match.season_id)
        .where(Result.confirmed.is_(True))
        .where(Match.kickoff_time >= datetime(settings.ml_history_from_year, 7, 1, tzinfo=UTC))
        .where(League.code.in_(settings.league_whitelist))
        .order_by(Match.kickoff_time, Match.id)
    )
    if before is not None:
        stmt = stmt.where(Match.kickoff_time < before)
    rows = (await session.execute(stmt)).all()
    return [
        MatchRow(
            match_id=match.id,
            kickoff_time=match.kickoff_time,
            home_team_id=match.home_team_id,
            away_team_id=match.away_team_id,
            league_code=league_code,
            season_label=season_label,
            home_score=result.home_score,
            away_score=result.away_score,
        )
        for match, result, league_code, season_label in rows
    ]


def _prior_cutoff(kickoff_col, lead_hours: int, dialect: str):
    """SQL for ``kickoff_col - lead_hours``, dialect-aware; ``None`` for the legacy path."""
    if lead_hours <= 0:
        return None
    if dialect == "sqlite":
        return func.datetime(kickoff_col, f"-{lead_hours} hours")
    return kickoff_col - func.make_interval(0, 0, 0, 0, lead_hours)


async def _latest_hkjc_snapshots(
    session: AsyncSession, rows: list[MatchRow], odds_type: str, lead_hours: int = 0
) -> dict[int, OddsSnapshot]:
    if not rows:
        return {}
    cutoff = _prior_cutoff(Match.kickoff_time, lead_hours, session.get_bind().dialect.name)
    ranked = (
        select(
            OddsSnapshot.id.label("snapshot_id"),
            func.row_number()
            .over(
                partition_by=OddsSnapshot.match_id,
                order_by=OddsSnapshot.captured_at.desc(),
            )
            .label("rn"),
        )
        .join(Match, Match.id == OddsSnapshot.match_id)
        .where(OddsSnapshot.match_id.in_([row.match_id for row in rows]))
        .where(OddsSnapshot.odds_type == odds_type)
        .where(OddsSnapshot.source == "hkjc")
        .where(OddsSnapshot.inplay.is_(False))
        .where(
            OddsSnapshot.captured_at < cutoff
            if cutoff is not None
            else OddsSnapshot.captured_at < Match.kickoff_time
        )
        .subquery()
    )
    stmt = (
        select(OddsSnapshot)
        .join(ranked, ranked.c.snapshot_id == OddsSnapshot.id)
        .where(ranked.c.rn == 1)
    )
    return {snapshot.match_id: snapshot for snapshot in (await session.execute(stmt)).scalars()}


async def _football_data_snapshots(
    session: AsyncSession, rows: list[MatchRow]
) -> dict[int, OddsSnapshot]:
    if not rows:
        return {}
    stmt = (
        select(OddsSnapshot)
        .where(OddsSnapshot.match_id.in_([row.match_id for row in rows]))
        .where(OddsSnapshot.odds_type == "HAD")
        .where(OddsSnapshot.source == "football_data")
    )
    return {snapshot.match_id: snapshot for snapshot in (await session.execute(stmt)).scalars()}


async def load_hkjc_priors(
    session: AsyncSession, rows: list[MatchRow], lead_hours: int = 0
) -> dict[int, MarketPrior]:
    """HKJC-only de-vigged priors. ``lead_hours > 0`` selects the last snapshot
    strictly before ``kickoff - lead_hours`` (the serving-time information set); 0
    keeps the legacy "latest snapshot strictly before kickoff" (used for CLV closes)."""
    had = await _latest_hkjc_snapshots(session, rows, "HAD", lead_hours)
    hdc = await _latest_hkjc_snapshots(session, rows, "HDC", lead_hours)
    priors: dict[int, MarketPrior] = {}
    for row in rows:
        had_probs = had_odds = None
        snapshot = had.get(row.match_id)
        if snapshot is not None:
            had_odds = hkjc_had_odds(snapshot.payload)
            if had_odds is not None:
                fair = devig_multiplicative([had_odds["H"], had_odds["D"], had_odds["A"]])
                had_probs = {"H": fair[0], "D": fair[1], "A": fair[2]}
        hdc_line = hdc_probs = hdc_odds = None
        snapshot = hdc.get(row.match_id)
        if snapshot is not None:
            main = hkjc_hdc_main(snapshot.payload)
            if main is not None:
                hdc_line, hdc_odds = main
                fair = devig_multiplicative([hdc_odds["H"], hdc_odds["A"]])
                hdc_probs = {"H": fair[0], "A": fair[1]}
        priors[row.match_id] = MarketPrior(
            had_probs=had_probs,
            had_odds=had_odds,
            hdc_line=hdc_line,
            hdc_probs=hdc_probs,
            hdc_odds=hdc_odds,
            source="hkjc" if had_probs is not None else "none",
        )
    return priors


async def load_market_priors(
    session: AsyncSession, rows: list[MatchRow], lead_hours: int = 0
) -> dict[int, MarketPrior]:
    """HKJC priors where available (see ``load_hkjc_priors``), else football-data close."""
    priors = await load_hkjc_priors(session, rows, lead_hours)
    missing = [row for row in rows if priors[row.match_id].had_probs is None]
    if not missing:
        return priors
    fallback = await _football_data_snapshots(session, missing)
    for row in missing:
        snapshot = fallback.get(row.match_id)
        if snapshot is None:
            continue
        odds = football_data_close_odds(snapshot.payload)
        if odds is None:
            continue
        fair = devig_multiplicative([odds["H"], odds["D"], odds["A"]])
        prior = priors[row.match_id]
        priors[row.match_id] = MarketPrior(
            had_probs={"H": fair[0], "D": fair[1], "A": fair[2]},
            had_odds=odds,
            hdc_line=prior.hdc_line,
            hdc_probs=prior.hdc_probs,
            hdc_odds=prior.hdc_odds,
            source="football_data",
        )
    return priors


def temporal_split(
    df: pd.DataFrame,
    calibration_fraction: float = CALIBRATION_FRACTION,
    eval_fraction: float = EVAL_FRACTION,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronological train/calibration/eval split (oldest -> newest)."""
    ordered = df.sort_values(["kickoff_time", "match_id"]).reset_index(drop=True)
    n = len(ordered)
    if n < MIN_DATASET_ROWS:
        raise ValueError(f"need at least {MIN_DATASET_ROWS} rows, got {n}")
    n_eval = max(1, int(n * eval_fraction))
    n_cal = max(1, int(n * calibration_fraction))
    n_train = n - n_eval - n_cal
    if n_train < 1:
        raise ValueError(f"split leaves no training rows (n={n})")
    return (
        ordered.iloc[:n_train].copy(),
        ordered.iloc[n_train : n_train + n_cal].copy(),
        ordered.iloc[n_train + n_cal :].copy(),
    )


def _frame(rows: list[MatchRow], priors: dict[int, MarketPrior]) -> pd.DataFrame:
    by_id = {row.match_id: row for row in rows}
    records: list[dict] = []
    for feature_row in build_feature_rows(rows, priors):
        row = by_id[feature_row.match_id]
        if row.home_score is None or row.away_score is None:
            continue
        prior = priors.get(feature_row.match_id)
        label_hdc = None
        if prior is not None and prior.hdc_line is not None:
            label_hdc = handicap_label(row.home_score, row.away_score, prior.hdc_line)
        records.append(
            {
                **feature_row.features,
                "match_id": feature_row.match_id,
                "kickoff_time": feature_row.kickoff_time,
                "label_1x2": label_1x2(row.home_score, row.away_score),
                "label_handicap": label_hdc,
            }
        )
    if not records:
        raise ValueError("no labelled rows could be built")
    return pd.DataFrame.from_records(records)


async def build_dataset(session: AsyncSession, settings: Settings) -> Dataset:
    """Assemble the full training dataset from the database."""
    rows = await load_training_rows(session, settings)
    if not rows:
        raise ValueError("no confirmed results in the configured history window")
    priors = await load_market_priors(session, rows, settings.ml_prior_lead_hours)
    train, calibration, evaluation = temporal_split(_frame(rows, priors))
    return Dataset(train=train, calibration=calibration, eval=evaluation)
