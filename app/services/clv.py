"""Live closing-line value (CLV) tracking and the paper-validation stop/go gate.

``update_clv`` records, once per prediction, the de-vigged closing probability and
raw closing odds from the last pre-kickoff snapshot (HKJC first, football-data as
fallback). ``summary`` aggregates those records and combines them with settled
paper-ledger bets into a strict gate verdict. Both are read-only apart from the
idempotent insert in ``update_clv``; neither commits (the caller owns the
transaction).
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import TypedDict

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import (
    ClvRecord,
    LedgerBet,
    Match,
    ModelVersion,
    Prediction,
    Result,
    ShadowLedgerBet,
)
from app.ml.dataset import load_market_priors
from app.ml.features import MatchRow
from app.ml.labels import label_1x2
from app.services.runs import track_run

CLV_JOB_ID = "clv_update"
CLV_SOURCES = {"hkjc", "football_data", "all"}
LEDGER_BOOKS: dict[str, type[LedgerBet | ShadowLedgerBet]] = {
    "production": LedgerBet,
    "shadow": ShadowLedgerBet,
}
OUTCOMES = ("H", "D", "A")
LABEL_INDEX = {"H": 0, "D": 1, "A": 2}
LOG_EPSILON = 1e-15


class Metrics(TypedDict):
    n: int
    mean_edge: float | None
    beat_fraction: float | None
    beat_ci95: list[float] | None
    mean_edge_ci95: list[float] | None


class Calibration(TypedDict):
    model_brier: float | None
    model_logloss: float | None
    market_brier: float | None
    market_logloss: float | None
    n_matches: int


class Roi(TypedDict):
    roi_real: float | None
    roi_real_ci95: list[float] | None
    n_settled_bets: int
    settled_stakes: float


class Criterion(TypedDict):
    key: str
    passed: bool
    actual: float | int | None
    required: float | int | None


class Gate(TypedDict):
    ready: bool
    verdict: str
    days_elapsed: int
    days_remaining: int
    criteria: list[Criterion]


async def _backfill_labels(session: AsyncSession) -> int:
    """Fill ``label`` on records inserted before the result was confirmed.

    ``update_clv`` skips predictions that already have a CLV record, so a record
    created while the match had no confirmed result would otherwise keep
    ``label=None`` forever and calibration would stay empty. This pass is
    idempotent and only touches confirmed results.
    """
    rows = (
        await session.execute(
            select(ClvRecord, Result)
            .join(Result, Result.match_id == ClvRecord.match_id)
            .where(ClvRecord.label.is_(None))
            .where(Result.confirmed.is_(True))
        )
    ).all()
    for record, result in rows:
        record.label = label_1x2(result.home_score, result.away_score)
    return len(rows)


async def update_clv(
    session: AsyncSession, settings: Settings, limit: int = 5000
) -> int:
    """Insert one CLV record per prediction whose match has kicked off.

    Predictions already carrying a record are skipped, so repeated runs are
    idempotent. Predictions without a usable closing price are left unrecorded
    and retried on the next run. Records whose match result was not confirmed at
    insertion time get their label backfilled on a later run. Returns the number
    of inserted records plus backfilled labels.
    """
    backfilled = await _backfill_labels(session)
    now = datetime.now(UTC)
    stmt = (
        select(Prediction, Match, Result)
        .join(Match, Match.id == Prediction.match_id)
        .outerjoin(Result, Result.match_id == Match.id)
        .outerjoin(ClvRecord, ClvRecord.prediction_id == Prediction.id)
        .where(Match.kickoff_time < now)
        .where(ClvRecord.id.is_(None))
        .order_by(Match.kickoff_time, Prediction.id)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        await session.flush()
        return backfilled
    match_rows = [
        MatchRow(
            match_id=match.id,
            kickoff_time=match.kickoff_time,
            home_team_id=0,
            away_team_id=0,
            league_code="",
            season_label="",
        )
        for _, match, _ in rows
    ]
    priors = await load_market_priors(session, match_rows, 0)
    inserted = 0
    for prediction, match, result in rows:
        prior = priors.get(match.id)
        if prior is None or prior.had_odds is None or prior.had_probs is None:
            continue
        closing_odds = prior.had_odds.get(prediction.outcome)
        closing_prob = prior.had_probs.get(prediction.outcome)
        if closing_odds is None or closing_prob is None:
            continue
        label = (
            label_1x2(result.home_score, result.away_score)
            if result is not None and result.confirmed
            else None
        )
        model_prob = float(prediction.prob)
        session.add(
            ClvRecord(
                prediction_id=prediction.id,
                match_id=prediction.match_id,
                model_version_id=prediction.model_version_id,
                target=prediction.target,
                outcome=prediction.outcome,
                model_prob=model_prob,
                closing_prob=float(closing_prob),
                closing_odds=float(closing_odds),
                edge=model_prob - float(closing_prob),
                beat=model_prob >= float(closing_prob),
                is_value=(
                    prediction.recommended_fraction is not None
                    and prediction.recommended_fraction > 0
                ),
                label=label,
                source=prior.source,
            )
        )
        inserted += 1
    await session.flush()
    return inserted + backfilled


async def clv_update(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> int:
    """Scheduled entry point: record CLV inside one tracked transaction."""

    async def work(session: AsyncSession) -> int:
        return await update_clv(session, settings)

    return await track_run(session_factory, CLV_JOB_ID, work)


def _wilson_interval(successes: int, n: int, z: float = 1.96) -> list[float] | None:
    if n <= 0:
        return None
    proportion = successes / n
    denominator = 1.0 + z * z / n
    center = (proportion + z * z / (2.0 * n)) / denominator
    half = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / n + z * z / (4.0 * n * n))
        / denominator
    )
    return [max(0.0, center - half), min(1.0, center + half)]


def _normal_ci95(values: list[float]) -> list[float] | None:
    array = np.asarray(values, dtype=float)
    if array.size < 2:
        return None
    mean = float(array.mean())
    half = 1.96 * float(array.std(ddof=1)) / math.sqrt(array.size)
    return [mean - half, mean + half]


def _metrics(records: list[ClvRecord]) -> Metrics:
    n = len(records)
    if n == 0:
        return {
            "n": 0,
            "mean_edge": None,
            "beat_fraction": None,
            "beat_ci95": None,
            "mean_edge_ci95": None,
        }
    edges = [float(record.edge) for record in records]
    beats = [1 if record.beat else 0 for record in records]
    return {
        "n": n,
        "mean_edge": float(np.mean(edges)),
        "beat_fraction": float(np.mean(beats)),
        "beat_ci95": _wilson_interval(int(sum(beats)), n),
        "mean_edge_ci95": _normal_ci95(edges),
    }


def _empty_calibration() -> Calibration:
    return {
        "model_brier": None,
        "model_logloss": None,
        "market_brier": None,
        "market_logloss": None,
        "n_matches": 0,
    }


async def _calibration(
    session: AsyncSession,
    source: str,
    model_version_id: int | None,
    target: str | None,
) -> Calibration:
    if target is not None and target != "1x2":
        return _empty_calibration()
    filters = [ClvRecord.target == "1x2"]
    if source != "all":
        filters.append(ClvRecord.source == source)
    if model_version_id is not None:
        filters.append(ClvRecord.model_version_id == model_version_id)
    rows = (
        await session.execute(
            select(ClvRecord, Result)
            .outerjoin(Result, Result.match_id == ClvRecord.match_id)
            .where(*filters)
        )
    ).all()
    by_match: dict[int, dict[str, ClvRecord]] = {}
    label_by_match: dict[int, str] = {}
    for record, result in rows:
        label = record.label
        if label is None and result is not None and result.confirmed:
            label = label_1x2(result.home_score, result.away_score)
        if label is None:
            continue
        by_match.setdefault(record.match_id, {})[record.outcome] = record
        label_by_match[record.match_id] = label
    model_probs: list[list[float]] = []
    market_probs: list[list[float]] = []
    labels: list[str] = []
    for match_id in sorted(by_match):
        outcomes = by_match[match_id]
        if set(outcomes) != set(OUTCOMES):
            continue
        model_probs.append([float(outcomes[outcome].model_prob) for outcome in OUTCOMES])
        market_probs.append([float(outcomes[outcome].closing_prob) for outcome in OUTCOMES])
        labels.append(label_by_match[match_id])
    if not model_probs:
        return _empty_calibration()
    model = np.asarray(model_probs, dtype=float)
    market = np.asarray(market_probs, dtype=float)
    indices = np.asarray([LABEL_INDEX[label] for label in labels], dtype=int)
    onehot = np.zeros_like(model)
    onehot[np.arange(len(indices)), indices] = 1.0
    model_brier = float(np.mean(np.sum((model - onehot) ** 2, axis=1)))
    market_brier = float(np.mean(np.sum((market - onehot) ** 2, axis=1)))
    model_actual = np.clip(model[np.arange(len(indices)), indices], LOG_EPSILON, 1.0)
    market_actual = np.clip(market[np.arange(len(indices)), indices], LOG_EPSILON, 1.0)
    return {
        "model_brier": model_brier,
        "model_logloss": float(np.mean(-np.log(model_actual))),
        "market_brier": market_brier,
        "market_logloss": float(np.mean(-np.log(market_actual))),
        "n_matches": len(labels),
    }


async def _roi_real(
    session: AsyncSession,
    model_version_id: int | None,
    target: str | None,
    bet_model: type[LedgerBet | ShadowLedgerBet] = LedgerBet,
) -> Roi:
    filters = [bet_model.status != "pending"]
    if model_version_id is not None:
        filters.append(bet_model.model_version_id == model_version_id)
    if target is not None:
        filters.append(bet_model.target == target)
    bets = (await session.execute(select(bet_model).where(*filters))).scalars().all()
    settled: list[tuple[float, float]] = []
    for bet in bets:
        if bet.stake > 0 and bet.profit is not None:
            settled.append((float(bet.stake), float(bet.profit)))
    if not settled:
        return {
            "roi_real": None,
            "roi_real_ci95": None,
            "n_settled_bets": 0,
            "settled_stakes": 0.0,
        }
    total_stake = sum(stake for stake, _ in settled)
    total_profit = sum(profit for _, profit in settled)
    returns = [profit / stake for stake, profit in settled]
    return {
        "roi_real": float(total_profit / total_stake) if total_stake > 0 else None,
        "roi_real_ci95": _normal_ci95(returns),
        "n_settled_bets": len(settled),
        "settled_stakes": float(total_stake),
    }


async def _days_elapsed(session: AsyncSession, settings: Settings) -> int:
    today = datetime.now(UTC).date()
    start: date | None = None
    if settings.clv_gate_start_date:
        try:
            start = date.fromisoformat(settings.clv_gate_start_date)
        except ValueError:
            start = None
    if start is None:
        earliest = (
            await session.execute(select(func.min(ClvRecord.computed_at)))
        ).scalar_one_or_none()
        if earliest is not None:
            start = earliest.date()
    if start is None:
        return 0
    return max(0, (today - start).days)


def _gate(
    settings: Settings,
    metrics: Metrics,
    calibration: Calibration,
    roi: Roi,
    days_elapsed: int,
) -> Gate:
    min_n = settings.clv_gate_min_n
    min_fraction = settings.clv_gate_min_fraction
    min_bets = settings.clv_gate_min_bets
    min_roi = settings.clv_gate_min_roi
    beat_ci = metrics["beat_ci95"]
    wilson_lower = beat_ci[0] if beat_ci is not None else None
    roi_ci = roi["roi_real_ci95"]
    roi_lower = roi_ci[0] if roi_ci is not None else None
    beat_fraction = metrics["beat_fraction"]
    roi_real = roi["roi_real"]
    model_logloss = calibration["model_logloss"]
    market_logloss = calibration["market_logloss"]
    model_brier = calibration["model_brier"]
    market_brier = calibration["market_brier"]
    criteria: list[Criterion] = [
        {
            "key": "clv_n",
            "passed": metrics["n"] >= min_n,
            "actual": metrics["n"],
            "required": min_n,
        },
        {
            "key": "clv_fraction",
            "passed": beat_fraction is not None and beat_fraction >= min_fraction,
            "actual": beat_fraction,
            "required": min_fraction,
        },
        {
            "key": "clv_wilson_lower",
            "passed": wilson_lower is not None and wilson_lower > 0.5,
            "actual": wilson_lower,
            "required": 0.5,
        },
        {
            "key": "roi_real",
            "passed": roi_real is not None and roi_real > min_roi,
            "actual": roi_real,
            "required": min_roi,
        },
        {
            "key": "roi_ci_lower",
            "passed": roi_lower is not None and roi_lower > 0.0,
            "actual": roi_lower,
            "required": 0.0,
        },
        {
            "key": "n_settled_bets",
            "passed": roi["n_settled_bets"] >= min_bets,
            "actual": roi["n_settled_bets"],
            "required": min_bets,
        },
        {
            "key": "calibration_logloss",
            "passed": (
                model_logloss is not None
                and market_logloss is not None
                and model_logloss <= market_logloss
            ),
            "actual": model_logloss,
            "required": market_logloss,
        },
        {
            "key": "calibration_brier",
            "passed": (
                model_brier is not None
                and market_brier is not None
                and model_brier <= market_brier
            ),
            "actual": model_brier,
            "required": market_brier,
        },
    ]
    ready = all(criterion["passed"] for criterion in criteria)
    days_remaining = max(0, settings.clv_gate_days - days_elapsed)
    if ready:
        verdict = "pass"
    elif metrics["n"] < min_n or days_remaining > 0:
        verdict = "collecting"
    else:
        verdict = "fail"
    return {
        "ready": ready,
        "verdict": verdict,
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "criteria": criteria,
    }


async def summary(
    session: AsyncSession,
    settings: Settings,
    source: str = "hkjc",
    model_version_id: int | None = None,
    target: str | None = None,
    value_only: bool = False,
    book: str = "production",
) -> dict[str, object]:
    """Aggregate live CLV, calibration, realized ROI and the stop/go gate."""
    if source not in CLV_SOURCES:
        raise ValueError(f"unknown CLV source: {source}")
    if book not in LEDGER_BOOKS:
        raise ValueError(f"unknown ledger book: {book}")
    base_filters = []
    if model_version_id is not None:
        base_filters.append(ClvRecord.model_version_id == model_version_id)
    if target is not None:
        base_filters.append(ClvRecord.target == target)
    count_filters = list(base_filters)
    if value_only:
        count_filters.append(ClvRecord.is_value.is_(True))
    source_counts: dict[str, int] = {"hkjc": 0, "football_data": 0}
    count_rows = (
        await session.execute(
            select(ClvRecord.source, func.count())
            .where(*count_filters)
            .group_by(ClvRecord.source)
        )
    ).all()
    for record_source, count in count_rows:
        source_counts[str(record_source)] = int(count)
    fallback = source_counts.get("football_data", 0)

    filters = list(base_filters)
    if source != "all":
        filters.append(ClvRecord.source == source)
    if value_only:
        filters.append(ClvRecord.is_value.is_(True))
    rows = (
        await session.execute(
            select(ClvRecord, ModelVersion)
            .join(ModelVersion, ModelVersion.id == ClvRecord.model_version_id)
            .where(*filters)
            .order_by(ClvRecord.id)
        )
    ).all()
    records = [record for record, _ in rows]
    metrics = _metrics(records)
    by_outcome = {
        outcome: _metrics([record for record in records if record.outcome == outcome])
        for outcome in OUTCOMES
    }
    model_meta: dict[int, dict[str, object]] = {}
    model_records: dict[int, list[ClvRecord]] = {}
    for record, version in rows:
        model_meta.setdefault(
            version.id,
            {
                "model_version_id": version.id,
                "target": version.target,
                "status": version.status,
                "algorithm": version.algorithm,
            },
        )
        model_records.setdefault(version.id, []).append(record)
    by_model: list[dict[str, object]] = [
        {**model_meta[version_id], **_metrics(model_records[version_id])}
        for version_id in sorted(model_meta)
    ]
    value = _metrics([record for record in records if record.is_value])
    calibration = await _calibration(session, source, model_version_id, target)
    roi = await _roi_real(session, model_version_id, target, LEDGER_BOOKS[book])
    days_elapsed = await _days_elapsed(session, settings)
    gate = _gate(settings, metrics, calibration, roi, days_elapsed)
    return {
        "source": source,
        "book": book,
        "n": metrics["n"],
        "mean_edge": metrics["mean_edge"],
        "beat_fraction": metrics["beat_fraction"],
        "beat_ci95": metrics["beat_ci95"],
        "mean_edge_ci95": metrics["mean_edge_ci95"],
        "by_outcome": by_outcome,
        "by_model": by_model,
        "value": value,
        "source_counts": source_counts,
        "fallback": fallback,
        "calibration": calibration,
        "roi_real": roi["roi_real"],
        "roi_real_ci95": roi["roi_real_ci95"],
        "n_settled_bets": roi["n_settled_bets"],
        "settled_stakes": roi["settled_stakes"],
        "gate": gate,
    }
