from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.db.models import (
    Competition,
    DecisionLog,
    MarketLine,
    Match,
    ModelPrediction,
    OddsSnapshot,
    PaperBet,
    SourceFetchRun,
)
from packages.domain.enums import FetchRunStatus, MarketType, MatchStatus, Side
from packages.feedback.service import ensure_model_version
from packages.ingest.quality import QualityInput, evaluate_quality
from packages.ingest.triggers import bet_intent_key as build_bet_intent_key
from packages.ingest.triggers import decision_slot_key as build_decision_slot_key
from packages.ledger.experiments import active_experiment
from packages.ledger.service import LedgerService, PlaceBetRequest
from packages.models.poisson import (
    HadPrediction,
    fit_poisson_ratings,
    predict_had,
    save_had_predictions,
)
from packages.models.shrinkage import (
    CHALLENGER_MODEL_VERSION,
    shrink_had_prediction,
)
from packages.payoff.kelly import kelly_fraction
from packages.payoff.returns import MIN_ODDS, expected_value, return_distribution
from packages.shared.config import get_settings
from packages.shared.time import ensure_utc, utc_now

MIN_EDGE: Final[Decimal] = Decimal("0.03")
FRACTIONAL_KELLY: Final[Decimal] = Decimal("0.25")
MAX_STAKE_FRACTION: Final[Decimal] = Decimal("0.02")
MAX_ODDS_AGE: Final[timedelta] = timedelta(minutes=10)
MIN_STAKE: Final[Decimal] = Decimal("1.00")
STRATEGY_VERSION: Final[str] = "g1"
CHALLENGER_LANE: Final[str] = "challenger"
CHALLENGER_WEIGHT: Final[Decimal] = Decimal("0.50")
HAD_LINE_KEY: Final[str] = "0.0"

STATUS_BET: Final[str] = "bet"
STATUS_NO_BET: Final[str] = "no_bet"
STATUS_PREDICTION_ONLY: Final[str] = "prediction_only"
STATUS_SKIPPED: Final[str] = "skipped"

_MONEY_QUANTUM: Final[Decimal] = Decimal("0.01")
_POOL_SELLING_STARTED: Final[str] = "SELLINGSTARTED"
_LINE_AVAILABLE: Final[str] = "AVAILABLE"
_HAD_SIDES: Final[tuple[Side, Side, Side]] = (Side.H, Side.D, Side.A)
_UCL_CODE: Final[str] = "UCL"
_PREDICTION_COMPETITIONS: Final[frozenset[str]] = frozenset(
    {"EPL", "LALIGA", "BUNDESLIGA", "SERIEA", "LIGUE1", "UCL"}
)
_DECISION_TRIGGER: Final[str] = "T-30m"
_DEGRADED_SOURCE_LOOKBACK: Final[timedelta] = timedelta(minutes=30)
# An audit log can only move forward through these states. A retry may never
# turn a placed paper bet back into a skip.
_STATUS_RANK: Final[dict[str, int]] = {
    STATUS_SKIPPED: 0,
    STATUS_PREDICTION_ONLY: 1,
    STATUS_NO_BET: 2,
    STATUS_BET: 3,
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DecisionResult:
    status: str
    prediction: HadPrediction | None
    selected_side: Side | None
    expected_value: Decimal | None
    kelly_fraction: Decimal | None
    stake: Decimal | None
    paper_bet_id: uuid.UUID | None
    reason: str


def _skipped(reason: str) -> DecisionResult:
    return DecisionResult(
        status=STATUS_SKIPPED,
        prediction=None,
        selected_side=None,
        expected_value=None,
        kelly_fraction=None,
        stake=None,
        paper_bet_id=None,
        reason=reason,
    )


def _paper_competition_codes() -> frozenset[str]:
    configured = get_settings().paper_competitions
    return frozenset(
        code.strip().upper() for code in configured.split(",") if code.strip()
    )


def _load_had_lines(
    session: Session,
    snapshot: OddsSnapshot,
) -> tuple[dict[Side, MarketLine], str | None]:
    rows = session.scalars(
        select(MarketLine).where(
            MarketLine.snapshot_id == snapshot.id,
            MarketLine.odds_type == MarketType.HAD,
            MarketLine.condition_raw == HAD_LINE_KEY,
            MarketLine.side.in_(_HAD_SIDES),
        )
    ).all()
    lines: dict[Side, MarketLine] = {}
    for row in rows:
        if row.side in lines:
            return {}, f"duplicate HAD line for side {row.side.value}"
        lines[row.side] = row
    for side in _HAD_SIDES:
        line = lines.get(side)
        if line is None:
            return {}, f"HAD line missing for side {side.value}"
        if (
            line.pool_status != _POOL_SELLING_STARTED
            or line.line_status != _LINE_AVAILABLE
        ):
            return {}, f"HAD line for side {side.value} is suspended"
        if line.odds_decimal < MIN_ODDS:
            return {}, f"HAD odds for side {side.value} are below {MIN_ODDS}"
    return lines, None


def _decide_match(
    session: Session,
    match: Match,
    snapshot: OddsSnapshot | None,
    *,
    now: datetime | None = None,
    experiment_id: uuid.UUID | None = None,
    experiment_is_legacy: bool = False,
    model_version: str | None = None,
    market_weight: Decimal | None = None,
) -> DecisionResult:
    """Run the deterministic HAD decision for one T-30m odds snapshot."""
    competition = session.get(Competition, match.competition_id)
    if competition is None or competition.code not in _PREDICTION_COMPETITIONS:
        return _skipped("competition is not supported")
    if match.status != MatchStatus.SCHEDULED:
        return _skipped("match is not scheduled")
    if snapshot is None or snapshot.market != MarketType.HAD:
        return _skipped("odds snapshot is not a HAD snapshot")

    decision_at = ensure_utc(snapshot.snapshot_at)
    current = ensure_utc(now) if now is not None else utc_now()
    if current - decision_at > MAX_ODDS_AGE:
        return _skipped(f"odds snapshot is older than {MAX_ODDS_AGE}")
    if match.first_seen_at is None:
        return _skipped("match first_seen_at is missing")
    if ensure_utc(match.first_seen_at) > decision_at:
        return _skipped("match was first seen after the decision time")

    lines, line_error = _load_had_lines(session, snapshot)
    if line_error is not None:
        return _skipped(line_error)

    # HAD is not lineup-dependent in G1, so the quality gate runs without a
    # lineup requirement. It still fails closed on stale odds and degraded
    # sources before any model work happens.
    quality = evaluate_quality(
        QualityInput(
            competition_code=competition.code,
            kickoff_at=match.kickoff_at,
            now=current,
            odds_fetched_at=snapshot.snapshot_at,
            has_standard_lineup=False,
            has_predicted_lineup=False,
            has_xg=False,
            news_item_count=0,
            requires_lineup=False,
            requires_xg=competition.code != _UCL_CODE,
            degraded_sources=_degraded_sources(session, current),
        )
    )
    if not quality.can_bet:
        return _skipped(
            "quality gate veto: " + ", ".join(quality.veto_reasons)
        )

    ratings = fit_poisson_ratings(session, match.competition_id, as_of=decision_at)
    prediction = predict_had(ratings, match.home_team_id, match.away_team_id)
    if model_version == CHALLENGER_MODEL_VERSION:
        shrunken = shrink_had_prediction(
            prediction,
            {side: lines[side].odds_decimal for side in _HAD_SIDES},
            market_weight if market_weight is not None else CHALLENGER_WEIGHT,
        )
        if shrunken is None:
            return _skipped("market shrinkage unavailable")
        prediction = shrunken
    analysis_run_key = f"{prediction.model_version}:{match.id}:{_DECISION_TRIGGER}"
    _ = save_had_predictions(
        session,
        match_id=match.id,
        prediction=prediction,
        decision_at=decision_at,
        analysis_run_key=analysis_run_key,
    )

    if competition.code not in _paper_competition_codes():
        return DecisionResult(
            status=STATUS_PREDICTION_ONLY,
            prediction=prediction,
            selected_side=None,
            expected_value=None,
            kelly_fraction=None,
            stake=None,
            paper_bet_id=None,
            reason="competition is not enabled for paper betting",
        )

    evaluations: list[tuple[Side, Decimal, Decimal, Decimal]] = []
    for side in _HAD_SIDES:
        line = lines[side]
        distribution = return_distribution(
            prediction.score_distribution,
            MarketType.HAD,
            side,
            HAD_LINE_KEY,
            line.odds_decimal,
        )
        evaluations.append(
            (
                side,
                expected_value(distribution, line.odds_decimal),
                kelly_fraction(distribution, line.odds_decimal),
                line.odds_decimal,
            )
        )
    selected_side, best_ev, best_kelly, selected_odds = max(
        evaluations,
        key=lambda item: item[1],
    )

    if best_ev < MIN_EDGE:
        return DecisionResult(
            status=STATUS_NO_BET,
            prediction=prediction,
            selected_side=None,
            expected_value=best_ev,
            kelly_fraction=best_kelly,
            stake=None,
            paper_bet_id=None,
            reason=f"best EV {best_ev} is below minimum edge {MIN_EDGE}",
        )
    if best_kelly <= 0:
        return DecisionResult(
            status=STATUS_NO_BET,
            prediction=prediction,
            selected_side=None,
            expected_value=best_ev,
            kelly_fraction=best_kelly,
            stake=None,
            paper_bet_id=None,
            reason="kelly fraction is not positive",
        )

    ledger = LedgerService(session, experiment_id=experiment_id)
    available_bankroll = ledger.available_bankroll()
    stake = min(
        available_bankroll * best_kelly * FRACTIONAL_KELLY,
        available_bankroll * MAX_STAKE_FRACTION,
    ).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if stake < MIN_STAKE:
        return DecisionResult(
            status=STATUS_NO_BET,
            prediction=prediction,
            selected_side=None,
            expected_value=best_ev,
            kelly_fraction=best_kelly,
            stake=None,
            paper_bet_id=None,
            reason=f"stake {stake} is below minimum stake {MIN_STAKE}",
        )

    decision_slot = build_decision_slot_key(
        match.id,
        strategy_version=STRATEGY_VERSION,
        trigger=_DECISION_TRIGGER,
        experiment_id=None if experiment_is_legacy else experiment_id,
    )
    intent_key = build_bet_intent_key(
        decision_slot,
        MarketType.HAD,
        HAD_LINE_KEY,
        selected_side,
    )
    bet = ledger.place_bet(
        PlaceBetRequest(
            match_id=match.id,
            market=MarketType.HAD,
            line_key=HAD_LINE_KEY,
            selection=selected_side,
            odds_decimal=selected_odds,
            stake=stake,
            analysis_run_key=analysis_run_key,
            decision_slot_key=decision_slot,
            bet_intent_key=intent_key,
            decision_at=decision_at,
            odds_snapshot_id=snapshot.id,
        )
    )
    return DecisionResult(
        status=STATUS_BET,
        prediction=prediction,
        selected_side=bet.selection,
        expected_value=best_ev,
        kelly_fraction=best_kelly,
        stake=bet.stake,
        paper_bet_id=bet.id,
        reason="",
    )


def _prediction_count(session: Session, match: Match, prediction: HadPrediction | None) -> int:
    if prediction is None:
        return 0
    analysis_run_key = f"{prediction.model_version}:{match.id}:{_DECISION_TRIGGER}"
    count = session.scalar(
        select(func.count())
        .select_from(ModelPrediction)
        .where(
            ModelPrediction.analysis_run_key == analysis_run_key,
            ModelPrediction.market == MarketType.HAD,
        )
    )
    return int(count or 0)


def _degraded_sources(session: Session, now: datetime) -> tuple[str, ...]:
    cutoff = ensure_utc(now) - _DEGRADED_SOURCE_LOOKBACK
    sources = session.scalars(
        select(SourceFetchRun.source_name)
        .where(
            SourceFetchRun.status == FetchRunStatus.FAILED,
            SourceFetchRun.finished_at.is_not(None),
            SourceFetchRun.finished_at >= cutoff,
        )
        .distinct()
    ).all()
    return tuple(sorted({str(source) for source in sources}))


def _select_log(session: Session, slot_key: str) -> DecisionLog | None:
    return session.scalar(
        select(DecisionLog).where(DecisionLog.decision_slot_key == slot_key)
    )


def _log_decision(
    session: Session,
    match: Match,
    snapshot: OddsSnapshot | None,
    result: DecisionResult,
    *,
    now: datetime | None,
    experiment_id: uuid.UUID | None = None,
    experiment_is_legacy: bool = False,
) -> None:
    """Upsert the audit log for one deterministic decision slot."""
    slot_key = build_decision_slot_key(
        match.id,
        strategy_version=STRATEGY_VERSION,
        trigger=_DECISION_TRIGGER,
        experiment_id=None if experiment_is_legacy else experiment_id,
    )
    if snapshot is not None:
        decision_at = ensure_utc(snapshot.snapshot_at)
    elif now is not None:
        decision_at = ensure_utc(now)
    else:
        decision_at = utc_now()
    reason = result.reason.strip()
    if not reason and result.status != STATUS_BET:
        reason = f"decision {result.status}"
    model_version = result.prediction.model_version if result.prediction else None
    prediction_count = _prediction_count(session, match, result.prediction)

    paper_bet_id = result.paper_bet_id
    if paper_bet_id is None:
        paper_bet_id = session.scalar(
            select(PaperBet.id).where(PaperBet.decision_slot_key == slot_key)
        )

    log = _select_log(session, slot_key)
    is_new = log is None
    if log is None:
        candidate = DecisionLog(
            experiment_id=experiment_id,
            match_id=match.id,
            decision_slot_key=slot_key,
            snapshot_id=snapshot.id if snapshot is not None else None,
            decision_at=decision_at,
            status=result.status,
            reason=reason,
            model_version=model_version,
            prediction_count=prediction_count,
            paper_bet_id=paper_bet_id,
        )
        try:
            # A concurrent trigger may insert the same unique slot key first.
            with session.begin_nested():
                session.add(candidate)
                session.flush()
            log = candidate
        except IntegrityError:
            log = _select_log(session, slot_key)
            if log is None:
                raise
            is_new = False

    if not is_new and log.paper_bet_id is not None:
        paper_bet_id = log.paper_bet_id
    if not is_new and _STATUS_RANK.get(result.status, 0) < _STATUS_RANK.get(log.status, 0):
        if log.paper_bet_id is None and paper_bet_id is not None:
            log.paper_bet_id = paper_bet_id
            session.flush()
        return

    log.experiment_id = experiment_id
    log.snapshot_id = snapshot.id if snapshot is not None else None
    log.decision_at = decision_at
    log.status = result.status
    log.reason = reason
    log.model_version = model_version
    log.prediction_count = prediction_count
    log.paper_bet_id = paper_bet_id
    session.flush()


def decide_match(
    session: Session,
    match: Match,
    snapshot: OddsSnapshot | None,
    *,
    now: datetime | None = None,
) -> DecisionResult:
    """Run the deterministic paper HAD decision and record an audit log."""
    experiment = active_experiment(session)
    experiment_id = experiment.id if experiment is not None else None
    experiment_is_legacy = bool(experiment.is_legacy) if experiment is not None else False
    result = _decide_match(
        session,
        match,
        snapshot,
        now=now,
        experiment_id=experiment_id,
        experiment_is_legacy=experiment_is_legacy,
    )
    _log_decision(
        session,
        match,
        snapshot,
        result,
        now=now,
        experiment_id=experiment_id,
        experiment_is_legacy=experiment_is_legacy,
    )
    try:
        with session.begin_nested():
            decide_challenger_match(session, match, snapshot, now=now)
    except Exception:
        logger.exception("challenger decision failed for match %s", match.id)
    return result


def decide_challenger_match(
    session: Session,
    match: Match,
    snapshot: OddsSnapshot | None,
    *,
    now: datetime | None = None,
) -> DecisionResult | None:
    """Run the market-shrunk challenger decision when its lane is active."""
    experiment = active_experiment(session, CHALLENGER_LANE)
    if experiment is None:
        return None
    _ = ensure_model_version(
        session,
        CHALLENGER_MODEL_VERSION,
        "poisson_market_shrink",
        {"base": "poisson-v1", "market_weight": "0.5", "devig": "proportional"},
        {},
        {},
    )
    result = _decide_match(
        session,
        match,
        snapshot,
        now=now,
        experiment_id=experiment.id,
        experiment_is_legacy=False,
        model_version=CHALLENGER_MODEL_VERSION,
        market_weight=CHALLENGER_WEIGHT,
    )
    _log_decision(
        session,
        match,
        snapshot,
        result,
        now=now,
        experiment_id=experiment.id,
        experiment_is_legacy=False,
    )
    return result
