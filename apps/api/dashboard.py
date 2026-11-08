from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from packages.db.models import (
    BankrollAccount,
    CalibrationMetric,
    Competition,
    DecisionLog,
    LedgerExperiment,
    MarketLine,
    Match,
    ModelPrediction,
    ModelVersion,
    OddsSnapshot,
    PaperBet,
    RawPayload,
    Settlement,
    SourceFetchRun,
    StrategyVersion,
    Team,
    WeightSnapshot,
)
from packages.domain.enums import MarketType, MatchStatus, Side, SnapshotKind
from packages.ledger.experiments import active_experiment
from packages.ledger.service import LedgerService
from packages.shared.config import Settings, get_settings
from packages.shared.time import ensure_utc, utc_now

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_HAD = MarketType.HAD
_HAD_LINE = "0.0"
_SIDES: tuple[Side, Side, Side] = (Side.H, Side.D, Side.A)
_MONEY = Decimal("0.01")
_ZERO = Decimal("0.00")
_DATA_COMPETITIONS = ("EPL", "LALIGA", "BUNDESLIGA", "SERIEA", "LIGUE1", "UCL")


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def _settings(request: Request) -> Settings:
    configured = getattr(request.app.state, "settings", None)
    return configured if isinstance(configured, Settings) else get_settings()


def _iso(value: datetime | None) -> str | None:
    return None if value is None else ensure_utc(value).isoformat()


def _plain(value: Any) -> str | None:
    return None if value is None else str(value)


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(_MONEY))


def _enum(value: Any) -> Any:
    return getattr(value, "value", value)


def _safe_all(session: Session, statement: Any) -> list[Any]:
    try:
        return list(session.execute(statement).all())
    except SQLAlchemyError:
        session.rollback()
        return []


def _safe_scalar(session: Session, statement: Any) -> Any:
    try:
        return session.scalar(statement)
    except SQLAlchemyError:
        session.rollback()
        return None


def _count(session: Session, model: Any) -> int:
    value = _safe_scalar(session, select(func.count()).select_from(model))
    return int(value or 0)


def _database_status(session: Session) -> str:
    try:
        _ = session.execute(text("SELECT 1"))
        return "up"
    except SQLAlchemyError:
        session.rollback()
        return "down"


def _redis_status(request: Request) -> str:
    client = getattr(request.app.state, "redis", None)
    if client is None:
        return "not_configured"
    try:
        client.ping()
    except Exception:  # noqa: BLE001 - any failure means the dependency is down
        return "down"
    return "up"


def _account(session: Session, account_id: str) -> BankrollAccount | None:
    return _safe_scalar(
        session,
        select(BankrollAccount).where(BankrollAccount.account_id == account_id),
    )


def _predicted_match_count(
    session: Session, experiment: LedgerExperiment | None
) -> int:
    """Matches with an actual bet/no-bet decision, excluding prediction-only."""
    statement = (
        select(func.count(func.distinct(DecisionLog.match_id)))
        .select_from(DecisionLog)
        .where(DecisionLog.status.in_(("bet", "no_bet")))
    )
    if experiment is not None:
        statement = statement.where(DecisionLog.experiment_id == experiment.id)
    else:
        statement = statement.where(DecisionLog.experiment_id.is_(None))
    value = _safe_scalar(session, statement)
    return int(value or 0)


def _scoped_count(session: Session, model: Any, experiment: LedgerExperiment | None) -> int:
    statement = select(func.count()).select_from(model)
    if experiment is not None:
        statement = statement.where(model.experiment_id == experiment.id)
    value = _safe_scalar(session, statement)
    return int(value or 0)


def _bankroll(
    session: Session,
    settings: Settings,
    experiment: LedgerExperiment | None,
) -> dict[str, str]:
    initial = (
        Decimal(str(experiment.initial_bankroll))
        if experiment is not None
        else settings.initial_bankroll
    )
    account_id = experiment.account_id if experiment is not None else "paper"
    account = _account(session, account_id)
    if account is None:
        return {
            "initial": _money(initial) or "0.00",
            "balance": _money(initial) or "0.00",
            "reserved": "0.00",
            "available": _money(initial) or "0.00",
            "currency": "HKD",
        }
    balance = Decimal(str(account.bankroll_balance))
    reserved = Decimal(str(account.reserved_stake))
    return {
        "initial": _money(initial) or "0.00",
        "balance": _money(balance) or "0.00",
        "reserved": _money(reserved) or "0.00",
        "available": _money(balance - reserved) or "0.00",
        "currency": account.currency,
    }


@router.get("/overview")
def overview(request: Request, session: SessionDep) -> dict[str, Any]:
    settings = _settings(request)
    now = utc_now()
    experiment = active_experiment(session)
    summary = None
    try:
        summary = LedgerService(
            session,
            initial_bankroll=settings.initial_bankroll,
            experiment_id=experiment.id if experiment is not None else None,
        ).summary()
    except SQLAlchemyError:
        session.rollback()

    if summary is None:
        ledger = {
            "total_stake": "0.00",
            "total_payout": "0.00",
            "roi": str(_ZERO),
            "settled_bets": 0,
            "pending_bets": 0,
            "max_drawdown": str(_ZERO),
        }
    else:
        ledger = {
            "total_stake": _money(summary.total_stake),
            "total_payout": _money(summary.total_payout),
            "roi": _plain(summary.roi),
            "settled_bets": summary.settled_count,
            "pending_bets": summary.pending_count,
            "max_drawdown": _plain(summary.max_drawdown),
        }

    home = aliased(Team)
    away = aliased(Team)
    fixture_rows = _safe_all(
        session,
        select(
            Match.id,
            Match.kickoff_at,
            Match.status,
            Competition.code,
            home.name,
            away.name,
        )
        .join(Competition, Competition.id == Match.competition_id)
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .where(
            Competition.code.in_(_DATA_COMPETITIONS),
            Match.status == MatchStatus.SCHEDULED,
            Match.kickoff_at >= now,
        )
        .order_by(Match.kickoff_at.asc(), Match.id.asc())
        .limit(8),
    )

    calibration_rows = _safe_all(
        session,
        select(CalibrationMetric)
        .order_by(CalibrationMetric.created_at.desc(), CalibrationMetric.id.desc())
        .limit(10),
    )

    ranked_sources = (
        select(
            SourceFetchRun.id.label("id"),
            func.row_number()
            .over(
                partition_by=SourceFetchRun.source_name,
                order_by=(
                    SourceFetchRun.started_at.desc(),
                    SourceFetchRun.id.desc(),
                ),
            )
            .label("rn"),
        )
        .subquery()
    )
    source_rows = _safe_all(
        session,
        select(SourceFetchRun)
        .join(ranked_sources, ranked_sources.c.id == SourceFetchRun.id)
        .where(ranked_sources.c.rn == 1)
        .order_by(SourceFetchRun.started_at.desc(), SourceFetchRun.id.desc())
        .limit(10),
    )

    return {
        "generated_at": _iso(now),
        "health": {
            "api": "ok",
            "database": _database_status(session),
            "redis": _redis_status(request),
        },
        "bankroll": _bankroll(session, settings, experiment),
        "experiment": {
            "id": str(experiment.id) if experiment is not None else None,
            "label": experiment.label if experiment is not None else "legacy",
            "model_version": experiment.model_version if experiment is not None else None,
            "strategy_version": experiment.strategy_version if experiment is not None else None,
            "initial_bankroll": _money(
                Decimal(str(experiment.initial_bankroll))
                if experiment is not None
                else settings.initial_bankroll
            ),
        },
        "ledger": ledger,
        "counts": {
            "matches": _count(session, Match),
            "predictions": _count(session, ModelPrediction),
            "predicted_matches": _predicted_match_count(session, experiment),
            "bets": _scoped_count(session, PaperBet, experiment),
            "settlements": _count(session, Settlement),
            "decisions": _scoped_count(session, DecisionLog, experiment),
        },
        "next_fixtures": [
            {
                "match_id": str(row[0]),
                "kickoff_at": _iso(row[1]),
                "competition": row[3],
                "home_team": row[4],
                "away_team": row[5],
                "status": _enum(row[2]),
            }
            for row in fixture_rows
        ],
        "latest_calibration": [
            {
                "model_version": row[0].model_version,
                "strategy_version": row[0].strategy_version,
                "competition": row[0].competition,
                "market": row[0].market,
                "time_block": row[0].time_block,
                "sample_count": row[0].sample_count,
                "brier": _plain(row[0].brier),
                "log_loss": _plain(row[0].log_loss),
                "roi": _plain(row[0].roi),
                "clv": _plain(row[0].clv),
            }
            for row in calibration_rows
        ],
        "latest_sources": [
            {
                "source_name": row[0].source_name,
                "status": _enum(row[0].status),
                "finished_at": _iso(row[0].finished_at),
                "error_count": row[0].error_count,
            }
            for row in source_rows
        ],
    }


def _odds_for_match(session: Session, match_id: uuid.UUID) -> dict[Side, Decimal]:
    snapshot = _safe_scalar(
        session,
        select(OddsSnapshot)
        .where(
            OddsSnapshot.match_id == match_id,
            OddsSnapshot.market == _HAD,
            OddsSnapshot.snapshot_kind == SnapshotKind.T30M,
        )
        .order_by(OddsSnapshot.snapshot_at.desc(), OddsSnapshot.id.desc())
        .limit(1),
    )
    if snapshot is None:
        snapshot = _safe_scalar(
            session,
            select(OddsSnapshot)
            .where(
                OddsSnapshot.match_id == match_id,
                OddsSnapshot.market == _HAD,
            )
            .order_by(OddsSnapshot.snapshot_at.desc(), OddsSnapshot.id.desc())
            .limit(1),
        )
    if snapshot is None:
        return {}
    rows = _safe_all(
        session,
        select(MarketLine.side, MarketLine.odds_decimal).where(
            MarketLine.snapshot_id == snapshot.id,
            MarketLine.odds_type == _HAD,
            MarketLine.condition_raw == _HAD_LINE,
        ),
    )
    return {row[0]: Decimal(str(row[1])) for row in rows}


def _decision_for_match(
    session: Session,
    match_id: uuid.UUID,
    *,
    experiment_id: uuid.UUID | None = None,
    model_version: str | None = None,
) -> DecisionLog | None:
    if experiment_id is not None:
        found = _safe_scalar(
            session,
            select(DecisionLog).where(
                DecisionLog.decision_slot_key
                == f"g1:{experiment_id}:{match_id}:T-30m"
            ),
        )
        if found is not None:
            return found
    legacy = _safe_scalar(
        session,
        select(DecisionLog).where(
            DecisionLog.decision_slot_key == f"g1:{match_id}:T-30m"
        ),
    )
    if legacy is not None:
        return legacy
    conditions = [DecisionLog.match_id == match_id]
    if model_version is not None:
        conditions.append(DecisionLog.model_version == model_version)
    return _safe_scalar(
        session,
        select(DecisionLog)
        .where(*conditions)
        .order_by(DecisionLog.decision_at.desc(), DecisionLog.id.desc())
        .limit(1),
    )


@router.get("/predictions")
def predictions(
    session: SessionDep,
    limit: int = 50,
    model_version: str = "poisson-v1",
) -> list[dict[str, Any]]:
    clamped = max(1, min(limit, 200))
    experiment = active_experiment(
        session,
        "challenger" if model_version == "poisson-v2-shrunk" else "deterministic",
    )
    run_stats = (
        select(
            ModelPrediction.match_id.label("match_id"),
            ModelPrediction.analysis_run_key.label("analysis_run_key"),
            func.max(ModelPrediction.decision_at).label("latest_decision_at"),
            func.count(func.distinct(ModelPrediction.outcome)).label("outcome_count"),
        )
        .where(
            ModelPrediction.model_version == model_version,
            ModelPrediction.market == _HAD,
            ModelPrediction.line_key == _HAD_LINE,
            ModelPrediction.outcome.in_(_SIDES),
        )
        .group_by(ModelPrediction.match_id, ModelPrediction.analysis_run_key)
        .subquery()
    )
    ranked = (
        select(
            run_stats.c.match_id,
            run_stats.c.analysis_run_key,
            run_stats.c.latest_decision_at,
            func.row_number()
            .over(
                partition_by=run_stats.c.match_id,
                order_by=(
                    run_stats.c.latest_decision_at.desc(),
                    run_stats.c.analysis_run_key.desc(),
                ),
            )
            .label("rn"),
        )
        .where(run_stats.c.outcome_count == 3)
        .subquery()
    )
    chosen = (
        select(
            ranked.c.match_id,
            ranked.c.analysis_run_key,
            ranked.c.latest_decision_at,
        )
        .where(ranked.c.rn == 1)
        .subquery()
    )
    home = aliased(Team)
    away = aliased(Team)
    rows = _safe_all(
        session,
        select(
            ModelPrediction.match_id,
            ModelPrediction.outcome,
            ModelPrediction.probability,
            ModelPrediction.model_version,
            chosen.c.latest_decision_at,
            Match.kickoff_at,
            Competition.code,
            home.name,
            away.name,
            Match.status,
            Match.home_goals_90,
            Match.away_goals_90,
            Match.home_goals_final,
            Match.away_goals_final,
        )
        .join(
            chosen,
            and_(
                chosen.c.match_id == ModelPrediction.match_id,
                chosen.c.analysis_run_key == ModelPrediction.analysis_run_key,
            ),
        )
        .join(Match, Match.id == ModelPrediction.match_id)
        .join(Competition, Competition.id == Match.competition_id)
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .where(
            ModelPrediction.market == _HAD,
            ModelPrediction.line_key == _HAD_LINE,
            ModelPrediction.outcome.in_(_SIDES),
        )
        .order_by(Match.kickoff_at.asc(), Match.id.asc()),
    )

    grouped: dict[uuid.UUID, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row)

    output: list[dict[str, Any]] = []
    for match_id, match_rows in list(grouped.items())[:clamped]:
        first = match_rows[0]
        probabilities = {row[1]: Decimal(str(row[2])) for row in match_rows}
        if len(probabilities) != 3:
            continue
        odds = _odds_for_match(session, match_id)
        decision = _decision_for_match(
            session,
            match_id,
            experiment_id=experiment.id if experiment is not None else None,
            model_version=model_version,
        )
        output.append(
            {
                "match_id": str(match_id),
                "kickoff_at": _iso(first[5]),
                "competition": first[6],
                "home_team": first[7],
                "away_team": first[8],
                "status": _enum(first[9]),
                "home_goals_90": first[10],
                "away_goals_90": first[11],
                "home_goals_final": first[12],
                "away_goals_final": first[13],
                "probabilities": {
                    side.value: _plain(probabilities[side]) for side in _SIDES
                },
                "odds": {
                    side.value: _plain(odds.get(side)) for side in _SIDES
                },
                "ev": {
                    side.value: _plain(
                        probabilities[side] * odds[side] - Decimal(1)
                    )
                    if side in odds
                    else None
                    for side in _SIDES
                },
                "model_version": first[3],
                "decision_at": _iso(first[4]),
                "decision_status": decision.status if decision is not None else "pending",
                "decision_reason": decision.reason if decision is not None else "",
            }
        )
    return output


def _bet_model_version(session: Session, bet: PaperBet) -> str | None:
    log = _safe_scalar(
        session,
        select(DecisionLog).where(
            DecisionLog.decision_slot_key == bet.decision_slot_key
        ),
    )
    if log is not None and log.model_version:
        return log.model_version
    return _safe_scalar(
        session,
        select(ModelPrediction.model_version)
        .where(
            ModelPrediction.match_id == bet.match_id,
            ModelPrediction.market == bet.market,
            ModelPrediction.line_key == bet.line_key,
            ModelPrediction.outcome == bet.selection,
            ModelPrediction.decision_at <= bet.decision_at,
        )
        .order_by(
            ModelPrediction.decision_at.desc(),
            ModelPrediction.id.desc(),
        )
        .limit(1),
    )


def _bets_for_experiment(
    session: Session,
    experiment: LedgerExperiment | None,
    limit: int,
) -> list[dict[str, Any]]:
    home = aliased(Team)
    away = aliased(Team)
    statement = (
        select(
            PaperBet,
            Match.kickoff_at,
            Competition.code,
            home.name,
            away.name,
            Match.home_goals_90,
            Match.away_goals_90,
            Match.home_goals_final,
            Match.away_goals_final,
            Settlement,
        )
        .join(Match, Match.id == PaperBet.match_id)
        .join(Competition, Competition.id == Match.competition_id)
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .outerjoin(Settlement, Settlement.paper_bet_id == PaperBet.id)
        .order_by(PaperBet.placed_at.desc(), PaperBet.id.desc())
        .limit(limit)
    )
    if experiment is not None:
        statement = statement.where(PaperBet.experiment_id == experiment.id)
    rows = _safe_all(session, statement)

    output: list[dict[str, Any]] = []
    for row in rows:
        bet: PaperBet = row[0]
        settlement: Settlement | None = row[9]
        payout = (
            Decimal(str(settlement.payout)) if settlement is not None else None
        )
        output.append(
            {
                "bet_id": str(bet.id),
                "match_id": str(bet.match_id),
                "kickoff_at": _iso(row[1]),
                "competition": row[2],
                "home_team": row[3],
                "away_team": row[4],
                "home_goals_90": row[5],
                "away_goals_90": row[6],
                "home_goals_final": row[7],
                "away_goals_final": row[8],
                "market": _enum(bet.market),
                "selection": _enum(bet.selection),
                "line_key": bet.line_key,
                "odds": _plain(bet.odds_decimal),
                "stake": _money(bet.stake),
                "status": _enum(bet.status),
                "placed_at": _iso(bet.placed_at),
                "settled_at": _iso(settlement.settled_at) if settlement else None,
                "payout": _money(payout),
                "profit": _money(payout - Decimal(str(bet.stake)))
                if payout is not None
                else None,
                "clv": _plain(settlement.clv) if settlement else None,
                "brier": _plain(settlement.brier_score) if settlement else None,
                "model_version": _bet_model_version(session, bet),
                "lane": experiment.lane if experiment is not None else "legacy",
                "decision_slot_key": bet.decision_slot_key,
            }
        )
    return output


@router.get("/bets")
def bets(request: Request, session: SessionDep, limit: int = 100) -> list[dict[str, Any]]:
    clamped = max(1, min(limit, 500))
    return _bets_for_experiment(session, active_experiment(session), clamped)


@router.get("/challenger")
def challenger(request: Request, session: SessionDep) -> dict[str, Any]:
    settings = _settings(request)
    experiment = active_experiment(session, "challenger")
    if experiment is None:
        return {
            "experiment": None,
            "ledger": None,
            "bankroll": None,
            "counts": None,
        }
    summary = LedgerService(
        session,
        initial_bankroll=settings.initial_bankroll,
        experiment_id=experiment.id,
    ).summary()
    return {
        "experiment": {
            "id": str(experiment.id),
            "label": experiment.label,
            "lane": experiment.lane,
            "model_version": experiment.model_version,
            "strategy_version": experiment.strategy_version,
            "initial_bankroll": _money(Decimal(str(experiment.initial_bankroll))),
        },
        "bankroll": _bankroll(session, settings, experiment),
        "ledger": {
            "total_stake": _money(summary.total_stake),
            "total_payout": _money(summary.total_payout),
            "roi": _plain(summary.roi),
            "settled_bets": summary.settled_count,
            "pending_bets": summary.pending_count,
            "max_drawdown": _plain(summary.max_drawdown),
        },
        "counts": {
            "predictions": int(
                _safe_scalar(
                    session,
                    select(func.count())
                    .select_from(ModelPrediction)
                    .where(
                        ModelPrediction.model_version == "poisson-v2-shrunk"
                    ),
                )
                or 0
            ),
            "predicted_matches": _predicted_match_count(session, experiment),
            "bets": _scoped_count(session, PaperBet, experiment),
            "decisions": _scoped_count(session, DecisionLog, experiment),
            "settled_bets": summary.settled_count,
        },
    }


@router.get("/challenger/bets")
def challenger_bets(
    request: Request,
    session: SessionDep,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clamped = max(1, min(limit, 500))
    experiment = active_experiment(session, "challenger")
    if experiment is None:
        return []
    return _bets_for_experiment(session, experiment, clamped)


def _equity_for_experiment(
    session: Session,
    settings: Settings,
    experiment: LedgerExperiment | None,
) -> dict[str, Any]:
    initial = (
        Decimal(str(experiment.initial_bankroll))
        if experiment is not None
        else settings.initial_bankroll
    )
    statement = (
        select(Settlement.settled_at, Settlement.payout, PaperBet.stake)
        .join(PaperBet, PaperBet.id == Settlement.paper_bet_id)
        .where(Settlement.provisional.is_(False))
        .order_by(Settlement.settled_at.asc(), Settlement.id.asc())
    )
    if experiment is not None:
        statement = statement.where(PaperBet.experiment_id == experiment.id)
    rows = _safe_all(session, statement)
    balance = initial
    points: list[dict[str, str | None]] = [{"t": None, "bankroll": _money(initial)}]
    for settled_at, payout, stake in rows:
        balance = balance - Decimal(str(stake)) + Decimal(str(payout))
        points.append({"t": _iso(settled_at), "bankroll": _money(balance)})
    return {"initial": _money(initial), "points": points}


@router.get("/equity")
def equity(request: Request, session: SessionDep) -> dict[str, Any]:
    return _equity_for_experiment(
        session,
        _settings(request),
        active_experiment(session),
    )


@router.get("/challenger/equity")
def challenger_equity(request: Request, session: SessionDep) -> dict[str, Any]:
    experiment = active_experiment(session, "challenger")
    if experiment is None:
        return {"initial": None, "points": []}
    return _equity_for_experiment(session, _settings(request), experiment)


@router.get("/calibration")
def calibration(session: SessionDep) -> dict[str, Any]:
    model_rows = _safe_all(
        session,
        select(ModelVersion).order_by(
            ModelVersion.created_at.desc(), ModelVersion.id.desc()
        ),
    )
    strategy_rows = _safe_all(
        session,
        select(StrategyVersion).order_by(
            StrategyVersion.created_at.desc(), StrategyVersion.id.desc()
        ),
    )
    metric_rows = _safe_all(
        session,
        select(CalibrationMetric)
        .order_by(CalibrationMetric.created_at.desc(), CalibrationMetric.id.desc())
        .limit(100),
    )
    weight_rows = _safe_all(
        session,
        select(WeightSnapshot)
        .order_by(WeightSnapshot.created_at.desc(), WeightSnapshot.id.desc())
        .limit(20),
    )
    return {
        "models": [
            {
                "version": row[0].version,
                "family": row[0].family,
                "status": row[0].status,
                "created_at": _iso(row[0].created_at),
                "params": row[0].params,
                "validation_metrics": row[0].validation_metrics,
            }
            for row in model_rows
        ],
        "strategies": [
            {
                "version": row[0].version,
                "model_version": row[0].model_version,
                "status": row[0].status,
                "created_at": _iso(row[0].created_at),
                "policy_params": row[0].policy_params,
            }
            for row in strategy_rows
        ],
        "metrics": [
            {
                "model_version": row[0].model_version,
                "strategy_version": row[0].strategy_version,
                "competition": row[0].competition,
                "market": row[0].market,
                "time_block": row[0].time_block,
                "sample_count": row[0].sample_count,
                "brier": _plain(row[0].brier),
                "log_loss": _plain(row[0].log_loss),
                "roi": _plain(row[0].roi),
                "clv": _plain(row[0].clv),
                "calibration": row[0].calibration,
            }
            for row in metric_rows
        ],
        "weight_snapshots": [
            {
                "strategy_version": row[0].strategy_version,
                "weights": row[0].weights,
                "reason": row[0].reason,
                "evaluation_period": row[0].evaluation_period,
                "created_at": _iso(row[0].created_at),
            }
            for row in weight_rows
        ],
    }


@router.get("/technical")
def technical(request: Request, session: SessionDep) -> dict[str, Any]:
    revision: str | None = None
    try:
        row = session.execute(text("SELECT version_num FROM alembic_version")).first()
        if row is not None:
            revision = str(row[0])
    except SQLAlchemyError:
        session.rollback()

    source_rows = _safe_all(
        session,
        select(SourceFetchRun)
        .order_by(SourceFetchRun.started_at.desc(), SourceFetchRun.id.desc())
        .limit(20),
    )
    decision_rows = _safe_all(
        session,
        select(DecisionLog)
        .order_by(DecisionLog.decision_at.desc(), DecisionLog.id.desc())
        .limit(20),
    )
    latest_odds = _safe_scalar(
        session,
        select(OddsSnapshot)
        .where(OddsSnapshot.market == _HAD)
        .order_by(OddsSnapshot.snapshot_at.desc(), OddsSnapshot.id.desc())
        .limit(1),
    )

    return {
        "alembic_revision": revision,
        "database": _database_status(session),
        "redis": _redis_status(request),
        "counts": {
            "matches": _count(session, Match),
            "predictions": _count(session, ModelPrediction),
            "bets": _count(session, PaperBet),
            "settlements": _count(session, Settlement),
            "decisions": _count(session, DecisionLog),
            "raw_payloads": _count(session, RawPayload),
            "source_runs": _count(session, SourceFetchRun),
        },
        "sources": [
            {
                "run_id": row[0].run_id,
                "source_name": row[0].source_name,
                "status": _enum(row[0].status),
                "started_at": _iso(row[0].started_at),
                "finished_at": _iso(row[0].finished_at),
                "request_count": row[0].request_count,
                "error_count": row[0].error_count,
                "error_summary": row[0].error_summary,
            }
            for row in source_rows
        ],
        "decisions": [
            {
                "match_id": str(row[0].match_id),
                "decision_slot_key": row[0].decision_slot_key,
                "decision_at": _iso(row[0].decision_at),
                "status": row[0].status,
                "reason": row[0].reason,
                "model_version": row[0].model_version,
                "strategy_version": row[0].decision_slot_key.split(":", 1)[0],
                "prediction_count": row[0].prediction_count,
                "paper_bet_id": str(row[0].paper_bet_id)
                if row[0].paper_bet_id is not None
                else None,
            }
            for row in decision_rows
        ],
        "latest_odds": {
            "snapshot_at": _iso(latest_odds.snapshot_at) if latest_odds else None,
            "market": _HAD.value,
            "match_id": str(latest_odds.match_id) if latest_odds else None,
        },
        "paper_forward": None,
    }
