from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import (
    CalibrationMetric,
    Competition,
    DecisionLog,
    Match,
    ModelPrediction,
    ModelVersion,
    PaperBet,
    Settlement,
    StrategyVersion,
    WeightSnapshot,
)
from packages.domain.enums import BetStatus

CALIBRATION_BINS = 10
_LOG_EPSILON = 1e-6
_QUANTUM = Decimal("0.000001")
_ZERO = Decimal(0)


def _six(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM)


def ensure_model_version(
    session: Session,
    version: str,
    family: str,
    params: dict[str, object],
    training_window: dict[str, object],
    validation_metrics: dict[str, object],
    status: str = "research",
) -> ModelVersion:
    """Register a model version; repeated calls update metadata but not status."""
    existing = session.scalar(
        select(ModelVersion).where(ModelVersion.version == version)
    )
    if existing is None:
        existing = ModelVersion(
            version=version,
            family=family,
            params=dict(params),
            training_window=dict(training_window),
            validation_metrics=dict(validation_metrics),
            status=status,
        )
        session.add(existing)
        session.flush()
        return existing
    existing.family = family
    existing.params = dict(params)
    existing.training_window = dict(training_window)
    existing.validation_metrics = dict(validation_metrics)
    return existing


def ensure_strategy_version(
    session: Session,
    version: str,
    model_version: str,
    policy_params: dict[str, object],
    status: str = "research",
) -> StrategyVersion:
    """Register a strategy version; repeated calls update metadata but not status."""
    existing = session.scalar(
        select(StrategyVersion).where(StrategyVersion.version == version)
    )
    if existing is None:
        existing = StrategyVersion(
            version=version,
            model_version=model_version,
            policy_params=dict(policy_params),
            status=status,
        )
        session.add(existing)
        session.flush()
        return existing
    existing.model_version = model_version
    existing.policy_params = dict(policy_params)
    return existing


def ensure_g1_versions(session: Session) -> tuple[ModelVersion, StrategyVersion]:
    model = ensure_model_version(session, "poisson-v1", "poisson", {}, {}, {})
    strategy = ensure_strategy_version(session, "g1", "poisson-v1", {})
    return model, strategy


def record_weight_snapshot(
    session: Session,
    strategy_version: str,
    weights: dict[str, object],
    reason: str,
    evaluation_period: str | None = None,
) -> WeightSnapshot:
    snapshot = WeightSnapshot(
        strategy_version=strategy_version,
        weights=dict(weights),
        reason=reason,
        evaluation_period=evaluation_period,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


@dataclass
class _Bin:
    count: int = 0
    probability_sum: Decimal = _ZERO
    wins: int = 0


@dataclass
class _Group:
    model_version: str
    strategy_version: str | None
    competition: str
    market: str
    sample_count: int = 0
    stake: Decimal = _ZERO
    payout: Decimal = _ZERO
    brier_sum: Decimal = _ZERO
    brier_count: int = 0
    log_loss_sum: Decimal = _ZERO
    log_loss_count: int = 0
    clv_sum: Decimal = _ZERO
    clv_count: int = 0
    bins: list[_Bin] = field(default_factory=lambda: [_Bin() for _ in range(CALIBRATION_BINS)])


def _latest_prediction(
    session: Session,
    bet: PaperBet,
    model_version: str | None,
) -> ModelPrediction | None:
    conditions = [
        ModelPrediction.match_id == bet.match_id,
        ModelPrediction.market == bet.market,
        ModelPrediction.line_key == bet.line_key,
        ModelPrediction.outcome == bet.selection,
        ModelPrediction.decision_at <= bet.decision_at,
    ]
    if model_version is not None:
        conditions.append(ModelPrediction.model_version == model_version)
    return session.scalar(
        select(ModelPrediction)
        .where(*conditions)
        .order_by(ModelPrediction.decision_at.desc(), ModelPrediction.id.desc())
        .limit(1)
    )


def _strategy_from_slot(slot_key: str) -> str | None:
    prefix = slot_key.split(":", 1)[0].strip()
    return prefix or None


def _log_loss(probability: Decimal, won: bool) -> Decimal:
    p = min(max(float(probability), _LOG_EPSILON), 1.0 - _LOG_EPSILON)
    value = -math.log(p if won else 1.0 - p)
    return Decimal(str(value))


def _calibration_bins(group: _Group) -> list[dict[str, object]]:
    bins: list[dict[str, object]] = []
    for index, bucket in enumerate(group.bins):
        lower = Decimal(index) / Decimal(CALIBRATION_BINS)
        upper = Decimal(index + 1) / Decimal(CALIBRATION_BINS)
        mean_predicted = (
            str(_six(bucket.probability_sum / bucket.count)) if bucket.count else None
        )
        observed = (
            str(_six(Decimal(bucket.wins) / bucket.count)) if bucket.count else None
        )
        bins.append(
            {
                "bin": index,
                "lower": str(lower),
                "upper": str(upper),
                "count": bucket.count,
                "mean_predicted": mean_predicted,
                "observed_win_rate": observed,
            }
        )
    return bins


def _accumulate(group: _Group, bet: PaperBet, settlement: Settlement, probability: Decimal) -> None:
    group.sample_count += 1
    group.stake += bet.stake
    group.payout += settlement.payout
    if settlement.clv is not None:
        group.clv_sum += settlement.clv
        group.clv_count += 1

    status = settlement.result_status
    if status not in (BetStatus.WON, BetStatus.LOST):
        # VOID/PUSH and half-ball results have no binary outcome for scoring.
        return
    won = status is BetStatus.WON
    outcome = Decimal(1) if won else Decimal(0)
    group.brier_sum += (probability - outcome) ** 2
    group.brier_count += 1
    group.log_loss_sum += _log_loss(probability, won)
    group.log_loss_count += 1

    index = min(int(probability * CALIBRATION_BINS), CALIBRATION_BINS - 1)
    bucket = group.bins[index]
    bucket.count += 1
    bucket.probability_sum += probability
    if won:
        bucket.wins += 1


def _upsert_metric(session: Session, group: _Group, time_block: str) -> CalibrationMetric:
    conditions = [
        CalibrationMetric.model_version == group.model_version,
        CalibrationMetric.competition == group.competition,
        CalibrationMetric.market == group.market,
        CalibrationMetric.time_block == time_block,
    ]
    if group.strategy_version is None:
        conditions.append(CalibrationMetric.strategy_version.is_(None))
    else:
        conditions.append(CalibrationMetric.strategy_version == group.strategy_version)
    metric = session.scalar(select(CalibrationMetric).where(*conditions))
    if metric is None:
        metric = CalibrationMetric(
            model_version=group.model_version,
            strategy_version=group.strategy_version,
            competition=group.competition,
            market=group.market,
            time_block=time_block,
        )
        session.add(metric)

    metric.sample_count = group.sample_count
    metric.brier = (
        _six(group.brier_sum / group.brier_count) if group.brier_count else None
    )
    metric.log_loss = (
        _six(group.log_loss_sum / group.log_loss_count)
        if group.log_loss_count
        else None
    )
    metric.roi = (
        _six((group.payout - group.stake) / group.stake)
        if group.stake > _ZERO
        else None
    )
    metric.clv = _six(group.clv_sum / group.clv_count) if group.clv_count else None
    metric.calibration = _calibration_bins(group)
    return metric


def build_calibration_report(
    session: Session,
    *,
    time_block: str,
    model_version: str | None = None,
) -> list[CalibrationMetric]:
    """Aggregate settled paper bets into per-version calibration metrics.

    ROI is gross settlement ROI: (payout - stake) / stake. It intentionally
    ignores the bankroll fee, matching the simple reporting contract.
    """
    rows = session.execute(
        select(PaperBet, Settlement, DecisionLog, Match, Competition)
        .join(Settlement, Settlement.paper_bet_id == PaperBet.id)
        .join(DecisionLog, DecisionLog.decision_slot_key == PaperBet.decision_slot_key)
        .join(Match, Match.id == PaperBet.match_id)
        .join(Competition, Competition.id == Match.competition_id)
        .where(Settlement.provisional.is_(False))
        .order_by(PaperBet.decision_at, PaperBet.id)
    ).all()

    groups: dict[tuple[str, str | None, str, str], _Group] = {}
    for bet, settlement, _log, _match, competition in rows:
        prediction = _latest_prediction(session, bet, model_version)
        if prediction is None:
            continue
        strategy_version = _strategy_from_slot(bet.decision_slot_key)
        key = (
            prediction.model_version,
            strategy_version,
            competition.code,
            bet.market.value,
        )
        group = groups.get(key)
        if group is None:
            group = _Group(
                model_version=prediction.model_version,
                strategy_version=strategy_version,
                competition=competition.code,
                market=bet.market.value,
            )
            groups[key] = group
        _accumulate(group, bet, settlement, Decimal(prediction.probability))

    metrics = [_upsert_metric(session, group, time_block) for group in groups.values()]
    session.flush()
    return metrics
