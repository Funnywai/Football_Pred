from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.backtest.walk_forward import (
    HAD_OUTCOMES,
    calibration_bins,
    devig_had,
    multiclass_brier,
    multiclass_log_loss,
)
from packages.db.models import (
    Competition,
    LedgerExperiment,
    LlmEnsemblePrediction,
    MarketLine,
    Match,
    ModelPrediction,
    OddsSnapshot,
    PaperBet,
)
from packages.domain.enums import MarketType, MatchStatus, Side, SnapshotKind
from packages.ledger.service import LedgerService
from packages.shared.time import ensure_utc, utc_now

D = Decimal
SCHEMA_VERSION = "evaluation-report-v1"
_Z_95 = 1.959963984540054
_HAD_SIDES = (Side.H, Side.D, Side.A)


@dataclass
class _Group:
    model_version: str
    competition: str
    season: str
    observations: list[tuple[dict[str, Decimal], str]] = field(default_factory=list)
    market_observations: list[tuple[dict[str, Decimal], str]] = field(default_factory=list)
    paired_observations: list[
        tuple[dict[str, Decimal], dict[str, Decimal], str]
    ] = field(default_factory=list)


def _actual(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


def _iso(value: datetime | None) -> str | None:
    return None if value is None else ensure_utc(value).isoformat()


def _mean_ci(values: list[Decimal]) -> list[str] | None:
    if len(values) < 2:
        return None
    mean = sum(values, D(0)) / D(len(values))
    variance = sum(((value - mean) ** 2 for value in values), D(0)) / D(
        len(values) - 1
    )
    margin = Decimal(str(_Z_95)) * (variance / D(len(values))).sqrt()
    return [str(mean - margin), str(mean + margin)]


def _paired_delta_ci(
    paired: list[tuple[dict[str, Decimal], dict[str, Decimal], str]],
) -> dict[str, list[str] | None]:
    if len(paired) < 2:
        return {"brier": None, "log_loss": None}
    brier_deltas = [
        multiclass_brier(model, actual) - multiclass_brier(market, actual)
        for model, market, actual in paired
    ]
    log_loss_deltas = [
        multiclass_log_loss(model, actual) - multiclass_log_loss(market, actual)
        for model, market, actual in paired
    ]
    return {
        "brier": _mean_ci(brier_deltas),
        "log_loss": _mean_ci(log_loss_deltas),
    }


def _metric_block(
    observations: list[tuple[dict[str, Decimal], str]],
) -> dict[str, Any]:
    if not observations:
        return {
            "samples": 0,
            "brier": None,
            "log_loss": None,
            "calibration": {},
        }
    count = D(len(observations))
    brier = sum((multiclass_brier(probs, actual) for probs, actual in observations), D(0))
    log_loss = sum(
        (multiclass_log_loss(probs, actual) for probs, actual in observations), D(0)
    )
    brier_values = [
        multiclass_brier(probs, actual) for probs, actual in observations
    ]
    log_loss_values = [
        multiclass_log_loss(probs, actual) for probs, actual in observations
    ]
    bins = calibration_bins(observations)
    return {
        "samples": len(observations),
        "brier": str(brier / count),
        "log_loss": str(log_loss / count),
        "brier_ci95": _mean_ci(brier_values),
        "log_loss_ci95": _mean_ci(log_loss_values),
        "calibration": {
            outcome: [
                {
                    "bin": item.bin_index,
                    "count": item.count,
                    "positives": item.positives,
                    "predicted_mean": str(item.predicted_mean),
                    "observed_rate": str(item.observed_rate),
                }
                for item in outcome_bins
            ]
            for outcome, outcome_bins in bins.items()
        },
    }


def _market_probabilities(
    session: Session,
    match_id: uuid.UUID,
    decision_at: datetime,
    snapshot_cache: dict[tuple[uuid.UUID, datetime], tuple[dict[Side, Decimal], uuid.UUID] | None],
) -> tuple[dict[str, Decimal], uuid.UUID] | None:
    key = (match_id, decision_at)
    if key in snapshot_cache:
        return snapshot_cache[key]
    snapshot = session.scalar(
        select(OddsSnapshot)
        .where(
            OddsSnapshot.match_id == match_id,
            OddsSnapshot.market == MarketType.HAD,
            OddsSnapshot.snapshot_kind == SnapshotKind.T30M,
            OddsSnapshot.snapshot_at <= decision_at,
        )
        .order_by(OddsSnapshot.snapshot_at.desc(), OddsSnapshot.id.desc())
        .limit(1)
    )
    if snapshot is None:
        snapshot_cache[key] = None
        return None
    lines = session.scalars(
        select(MarketLine).where(
            MarketLine.snapshot_id == snapshot.id,
            MarketLine.odds_type == MarketType.HAD,
            MarketLine.condition_raw == "0.0",
        )
    ).all()
    odds = {line.side: Decimal(str(line.odds_decimal)) for line in lines}
    if set(odds) != set(_HAD_SIDES):
        snapshot_cache[key] = None
        return None
    devig = devig_had(odds[Side.H], odds[Side.D], odds[Side.A])
    if devig is None:
        snapshot_cache[key] = None
        return None
    probabilities = {
        "H": devig[0],
        "D": devig[1],
        "A": devig[2],
    }
    result = (probabilities, snapshot.id)
    snapshot_cache[key] = result
    return result


def _latest_prediction_runs(
    session: Session,
) -> list[tuple[ModelPrediction, Match, Competition]]:
    rows = session.execute(
        select(ModelPrediction, Match, Competition)
        .join(Match, Match.id == ModelPrediction.match_id)
        .join(Competition, Competition.id == Match.competition_id)
        .where(
            ModelPrediction.market == MarketType.HAD,
            ModelPrediction.line_key == "0.0",
            ModelPrediction.outcome.in_(_HAD_SIDES),
        )
        .order_by(
            ModelPrediction.match_id,
            ModelPrediction.model_version,
            ModelPrediction.decision_at.desc(),
            ModelPrediction.analysis_run_key.desc(),
            ModelPrediction.id.desc(),
        )
    ).all()
    chosen: dict[tuple[uuid.UUID, str], tuple[str, datetime]] = {}
    for prediction, _match, _competition in rows:
        key = (prediction.match_id, prediction.model_version)
        if key not in chosen:
            chosen[key] = (prediction.analysis_run_key, prediction.decision_at)
    return [
        (prediction, match, competition)
        for prediction, match, competition in rows
        if chosen.get((prediction.match_id, prediction.model_version))
        == (prediction.analysis_run_key, prediction.decision_at)
    ]


def _bet_report(session: Session) -> list[dict[str, Any]]:
    experiment_ids = list(
        session.scalars(select(PaperBet.experiment_id).distinct()).all()
    )
    output: list[dict[str, Any]] = []
    for experiment_id in experiment_ids:
        experiment = (
            session.get(LedgerExperiment, experiment_id)
            if experiment_id is not None
            else None
        )
        if experiment is None:
            continue
        summary = LedgerService(session, experiment_id=experiment.id).summary()
        output.append(
            {
                "experiment_id": str(experiment.id),
                "label": experiment.label,
                "lane": experiment.lane,
                "model_version": experiment.model_version,
                "strategy_version": experiment.strategy_version,
                "initial_bankroll": str(experiment.initial_bankroll),
                "bankroll": str(summary.bankroll),
                "total_stake": str(summary.total_stake),
                "total_payout": str(summary.total_payout),
                "roi": str(summary.roi),
                "settled_bets": summary.settled_count,
                "pending_bets": summary.pending_count,
                "max_drawdown": str(summary.max_drawdown),
            }
        )
    return output


def build_evaluation_report(
    session: Session,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = ensure_utc(now or utc_now())
    matches = session.scalars(select(Match)).all()
    predictions = _latest_prediction_runs(session)
    snapshot_cache: dict[
        tuple[uuid.UUID, datetime], tuple[dict[str, Decimal], uuid.UUID] | None
    ] = {}
    groups: dict[tuple[str, str, str], _Group] = {}
    after_kickoff = 0
    missing_market = 0
    finished_matches = [
        match for match in matches if match.status is MatchStatus.FINISHED
    ]
    finished_missing_result_available_at = sum(
        1 for match in finished_matches if match.result_available_at is None
    )
    result_timestamp_coverage = (
        D(len(finished_matches) - finished_missing_result_available_at)
        / D(len(finished_matches))
        if finished_matches
        else D(0)
    )
    by_run: dict[tuple[uuid.UUID, str, str], list[tuple[ModelPrediction, Match, Competition]]] = defaultdict(list)
    for prediction, match, competition in predictions:
        by_run[(prediction.match_id, prediction.model_version, prediction.analysis_run_key)].append(
            (prediction, match, competition)
        )
    for run_rows in by_run.values():
        first_prediction, match, competition = run_rows[0]
        probabilities = {
            row[0].outcome.value: Decimal(str(row[0].probability))
            for row in run_rows
        }
        if set(probabilities) != set(HAD_OUTCOMES):
            continue
        if match.status is not MatchStatus.FINISHED:
            continue
        if match.home_goals_90 is None or match.away_goals_90 is None:
            continue
        if ensure_utc(first_prediction.decision_at) >= ensure_utc(match.kickoff_at):
            after_kickoff += 1
        actual = _actual(match.home_goals_90, match.away_goals_90)
        key = (first_prediction.model_version, competition.code, match.season)
        group = groups.setdefault(
            key,
            _Group(
                model_version=first_prediction.model_version,
                competition=competition.code,
                season=match.season,
            ),
        )
        group.observations.append((probabilities, actual))
        market = _market_probabilities(
            session,
            match.id,
            ensure_utc(first_prediction.decision_at),
            snapshot_cache,
        )
        if market is not None:
            group.market_observations.append((market[0], actual))
    llm_rows = session.execute(
        select(LlmEnsemblePrediction, Match, Competition)
        .join(Match, Match.id == LlmEnsemblePrediction.match_id)
        .join(Competition, Competition.id == Match.competition_id)
        .order_by(
            LlmEnsemblePrediction.match_id,
            LlmEnsemblePrediction.created_at.desc(),
            LlmEnsemblePrediction.id.desc(),
        )
    ).all()
    chosen_llm: set[uuid.UUID] = set()
    for prediction, match, competition in llm_rows:
        if prediction.match_id in chosen_llm:
            continue
        chosen_llm.add(prediction.match_id)
        if match.status is not MatchStatus.FINISHED:
            continue
        if match.home_goals_90 is None or match.away_goals_90 is None:
            continue
        probabilities = {
            outcome: Decimal(str(value))
            for outcome, value in prediction.probabilities.items()
        }
        if set(probabilities) != set(HAD_OUTCOMES):
            continue
        if ensure_utc(prediction.created_at) >= ensure_utc(match.kickoff_at):
            after_kickoff += 1
        actual = _actual(match.home_goals_90, match.away_goals_90)
        key = (prediction.model_version, competition.code, match.season)
        group = groups.setdefault(
            key,
            _Group(
                model_version=prediction.model_version,
                competition=competition.code,
                season=match.season,
            ),
        )
        group.observations.append((probabilities, actual))
        market = _market_probabilities(
            session,
            match.id,
            ensure_utc(prediction.created_at),
            snapshot_cache,
        )
        if market is not None:
            group.market_observations.append((market[0], actual))
            group.paired_observations.append((probabilities, market[0], actual))
        else:
            missing_market += 1

    group_payload: list[dict[str, Any]] = []
    for group in sorted(groups.values(), key=lambda item: (item.competition, item.season, item.model_version)):
        model_metrics = _metric_block(group.observations)
        market_metrics = _metric_block(group.market_observations)
        model_brier = model_metrics["brier"]
        market_brier = market_metrics["brier"]
        model_log_loss = model_metrics["log_loss"]
        market_log_loss = market_metrics["log_loss"]
        group_payload.append(
            {
                "model_version": group.model_version,
                "competition": group.competition,
                "season": group.season,
                "matches": len(group.observations),
                "market_matches": len(group.market_observations),
                "model": model_metrics,
                "market": market_metrics,
                "delta_brier": (
                    str(D(model_brier) - D(market_brier))
                    if model_brier is not None and market_brier is not None
                    else None
                ),
                "delta_log_loss": (
                    str(D(model_log_loss) - D(market_log_loss))
                    if model_log_loss is not None and market_log_loss is not None
                    else None
                ),
                "delta_ci95": _paired_delta_ci(group.paired_observations),
            }
        )
        missing_market += max(0, len(group.observations) - len(group.market_observations))
    bet_rows = _bet_report(session)
    legacy_bet_count = int(
        session.scalar(
            select(func.count())
            .select_from(PaperBet)
            .where(PaperBet.experiment_id.is_(None))
        )
        or 0
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": current.isoformat(),
        "universe": {
            "matches": len(matches),
            "finished_matches": len(finished_matches),
            "prediction_runs": sum(len(group.observations) for group in groups.values()),
        },
        "models": group_payload,
        "bets": bet_rows,
        "integrity": {
            "finished_matches_missing_result_available_at": finished_missing_result_available_at,
            "result_timestamp_coverage": str(result_timestamp_coverage),
            "predictions_after_kickoff": after_kickoff,
            "predictions_without_t30_market": missing_market,
            "bets_missing_experiment": legacy_bet_count,
        },
    }
