from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import aliased

from apps.api.dashboard import SessionDep
from packages.db.models import (
    BankrollAccount,
    Competition,
    LlmAgentRun,
    LlmEnsemblePrediction,
    LlmEvidencePacket,
    LlmResearchFinding,
    LlmResearchRun,
    MarketLine,
    Match,
    OddsSnapshot,
    PaperBet,
    Settlement,
    Team,
)
from packages.domain.enums import MarketType, MatchStatus, Side, SnapshotKind
from packages.ledger.experiments import active_experiment
from packages.ledger.service import LedgerService
from packages.llm.prompts.registry import PromptRegistry
from packages.llm.roster import AGENTS
from packages.shared.time import utc_now

router = APIRouter(prefix="/llm", tags=["llm"])

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts" / "llm"
_PHASE = "phase-3"
_INITIAL_WEIGHT = Decimal(1) / Decimal(len(AGENTS))


def _prompt_payloads() -> list[dict[str, Any]]:
    registry = PromptRegistry.from_directory(_PROMPT_DIR)
    names = ["system", *(agent.agent_id for agent in AGENTS if agent.agent_id != "risk_agent")]
    return [
        {
            "name": record.name,
            "sha256": record.sha256,
            "bytes": len(record.text.encode("utf-8")),
        }
        for record in (registry.get(name) for name in names)
    ]


def _count(session: SessionDep, model: Any) -> int:
    try:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)
    except SQLAlchemyError:
        session.rollback()
        return 0


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(Decimal("0.01")))


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    return parsed if parsed.is_finite() else None


def _odds_for_match(session: SessionDep, match_id: object) -> dict[str, str]:
    snapshot = session.scalar(
        select(OddsSnapshot)
        .where(
            OddsSnapshot.match_id == match_id,
            OddsSnapshot.market == MarketType.HAD,
            OddsSnapshot.snapshot_kind == SnapshotKind.T30M,
        )
        .order_by(OddsSnapshot.snapshot_at.desc(), OddsSnapshot.id.desc())
        .limit(1)
    )
    if snapshot is None:
        snapshot = session.scalar(
            select(OddsSnapshot)
            .where(
                OddsSnapshot.match_id == match_id,
                OddsSnapshot.market == MarketType.HAD,
            )
            .order_by(OddsSnapshot.snapshot_at.desc(), OddsSnapshot.id.desc())
            .limit(1)
        )
    if snapshot is None:
        return {}
    rows = session.execute(
        select(MarketLine.side, MarketLine.odds_decimal).where(
            MarketLine.snapshot_id == snapshot.id,
            MarketLine.odds_type == MarketType.HAD,
            MarketLine.condition_raw == "0.0",
        )
    ).all()
    return {row[0].value: str(row[1]) for row in rows}


def _competition_codes(value: object) -> list[str]:
    raw = value if isinstance(value, str) else "UCL"
    return sorted({code.strip().upper() for code in raw.split(",") if code.strip()})


def _llm_ledger(session: SessionDep) -> tuple[dict[str, Any] | None, int]:
    try:
        experiment = active_experiment(session, "llm")
        if experiment is None:
            return None, 0
        summary = LedgerService(session, experiment_id=experiment.id).summary()
        account = session.scalar(
            select(BankrollAccount).where(
                BankrollAccount.account_id == experiment.account_id
            )
        )
        paper_bets = int(
            session.scalar(
                select(func.count())
                .select_from(PaperBet)
                .where(PaperBet.experiment_id == experiment.id)
            )
            or 0
        )
    except SQLAlchemyError:
        session.rollback()
        return None, 0
    reserved = Decimal(str(account.reserved_stake)) if account is not None else Decimal("0.00")
    balance = Decimal(str(summary.bankroll))
    return (
        {
            "experiment_id": str(experiment.id),
            "label": experiment.label,
            "model_version": experiment.model_version,
            "strategy_version": experiment.strategy_version,
            "initial_bankroll": str(experiment.initial_bankroll),
            "bankroll": str(summary.bankroll),
            "available": str(balance - reserved),
            "reserved": str(reserved),
            "currency": account.currency if account is not None else "HKD",
            "total_stake": str(summary.total_stake),
            "total_payout": str(summary.total_payout),
            "roi": str(summary.roi),
            "settled_bets": summary.settled_count,
            "pending_bets": summary.pending_count,
            "max_drawdown": str(summary.max_drawdown),
        },
        paper_bets,
    )

def _next_fixtures(session: SessionDep, competition_codes: list[str]) -> list[dict[str, Any]]:
    if not competition_codes:
        return []
    home = aliased(Team)
    away = aliased(Team)
    try:
        rows = session.execute(
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
                Competition.code.in_(competition_codes),
                Match.status == MatchStatus.SCHEDULED,
                Match.kickoff_at >= utc_now(),
            )
            .order_by(Match.kickoff_at.asc(), Match.id.asc())
            .limit(8)
        ).all()
    except SQLAlchemyError:
        session.rollback()
        return []
    return [
        {
            "match_id": str(row[0]),
            "kickoff_at": _iso(row[1]),
            "competition": row[3],
            "home_team": row[4],
            "away_team": row[5],
            "status": row[2].value if hasattr(row[2], "value") else str(row[2]),
        }
        for row in rows
    ]


@router.get("/status")
def llm_status(request: Request, session: SessionDep) -> dict[str, Any]:
    prompts = _prompt_payloads()
    settings = getattr(request.app.state, "settings", None)
    enabled = bool(getattr(settings, "llm_enabled", False))
    provider = getattr(settings, "llm_provider", "openai_compatible")
    model = getattr(settings, "llm_model", "deepseek-v4.1-flash")
    competition_codes = _competition_codes(getattr(settings, "llm_competitions", "EPL,LALIGA,BUNDESLIGA,SERIEA,LIGUE1,UCL"))
    ledger, paper_bets = _llm_ledger(session)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "phase": _PHASE,
        "competitions": competition_codes,
        "runtime": {
            "decision_layer": "configured" if enabled else "llm_not_connected",
            "data_plane": "deterministic",
            "paper_ledger": "opened" if ledger is not None else "separate_not_opened",
            "provider": provider,
            "model": model,
        },
        "safety": {
            "paper_only": True,
            "real_money": False,
            "llm_may_write_database": False,
            "llm_may_settle": False,
        },
        "counts": {
            "agents": len(AGENTS),
            "prompts": len(prompts),
            "evidence_packets": _count(session, LlmEvidencePacket),
            "agent_runs": _count(session, LlmAgentRun),
            "predictions": _count(session, LlmEnsemblePrediction),
            "paper_bets": paper_bets,
        },
        "ledger": ledger,
        "next_fixtures": _next_fixtures(session, competition_codes),
        "agents": [asdict(agent) for agent in AGENTS],
        "weights": [
            {
                "agent_id": agent.agent_id,
                "weight": str(_INITIAL_WEIGHT.quantize(Decimal("0.0001"))),
                "sample_count": 0,
                "status": "not_trained",
            }
            for agent in AGENTS
        ],
        "prompts": prompts,
        "separation": [
            {
                "lane": "deterministic",
                "label": "Football_Pred",
                "detail": "Data ingestion, quality gates, poisson-v1, g1 paper ledger.",
            },
            {
                "lane": "llm",
                "label": "LLM Ensemble Lab",
                "detail": "LLM agents, weighted aggregation, separate paper ledger.",
            },
        ],
    }


@router.get("/research-runs")
def llm_research_runs(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    try:
        rows = session.scalars(
            select(LlmResearchRun)
            .order_by(LlmResearchRun.created_at.desc(), LlmResearchRun.id.desc())
            .limit(limit)
        ).all()
    except SQLAlchemyError:
        session.rollback()
        return []
    return [_research_run_payload(row) for row in rows]


@router.get("/research-runs/{run_id}")
def llm_research_run(run_id: str, session: SessionDep) -> dict[str, Any]:
    try:
        run = session.get(LlmResearchRun, uuid.UUID(run_id))
    except (ValueError, SQLAlchemyError):
        return {}
    if run is None:
        return {}
    findings = session.scalars(
        select(LlmResearchFinding)
        .where(LlmResearchFinding.run_id == run.id)
        .order_by(LlmResearchFinding.agent_id)
    ).all()
    payload = _research_run_payload(run)
    payload["findings"] = [
        {
            "agent_id": finding.agent_id,
            "summary": finding.summary,
            "findings": finding.findings,
            "confidence": str(finding.confidence) if finding.confidence is not None else None,
            "direction": finding.direction,
            "evidence_refs": finding.evidence_refs,
            "uncertainties": finding.uncertainties,
            "abstain": finding.abstain,
            "error": finding.error,
        }
        for finding in findings
    ]
    return payload


def _research_run_payload(run: LlmResearchRun) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "match_id": str(run.match_id),
        "stage": run.stage,
        "as_of": _iso(run.as_of),
        "status": run.status,
        "model_version": run.model_version,
        "prompt_version": run.prompt_version,
        "provider": run.provider,
        "report": run.report,
        "probabilities": run.probabilities,
        "recommended_side": run.recommended_side,
        "recommended_stake_pct": str(run.recommended_stake_pct)
        if run.recommended_stake_pct is not None
        else None,
        "confidence": str(run.confidence) if run.confidence is not None else None,
        "abstain": run.abstain,
        "risk": run.risk,
        "error": run.error,
        "created_at": _iso(run.created_at),
    }


@router.get("/predictions")
def llm_predictions(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    try:
        rows = session.scalars(
            select(LlmEnsemblePrediction)
            .order_by(LlmEnsemblePrediction.created_at.desc())
            .limit(limit * 4)
        ).all()
    except SQLAlchemyError:
        session.rollback()
        return []
    experiment = active_experiment(session, "llm")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        match_id = str(row.match_id)
        if match_id in seen:
            continue
        seen.add(match_id)
        match = session.get(Match, row.match_id)
        if match is None:
            continue
        competition = session.get(Competition, match.competition_id)
        home = session.get(Team, match.home_team_id)
        away = session.get(Team, match.away_team_id)
        bet = (
            session.scalar(
                select(PaperBet)
                .where(
                    PaperBet.match_id == row.match_id,
                    PaperBet.experiment_id == experiment.id,
                )
                .order_by(PaperBet.placed_at.desc(), PaperBet.id.desc())
                .limit(1)
            )
            if experiment is not None
            else None
        )
        odds = _odds_for_match(session, row.match_id)
        probabilities = row.probabilities
        ev: dict[str, str | None] = {}
        for side in (Side.H, Side.D, Side.A):
            probability = _decimal(probabilities.get(side.value))
            price = _decimal(odds.get(side.value))
            ev[side.value] = (
                str(probability * price - Decimal(1))
                if probability is not None and price is not None
                else None
            )
        output.append(
            {
                "match_id": match_id,
                "kickoff_at": _iso(match.kickoff_at),
                "competition": competition.code if competition else None,
                "home_team": home.name if home else None,
                "away_team": away.name if away else None,
                "probabilities": probabilities,
                "odds": odds,
                "ev": ev,
                "weights": row.weights,
                "active_agents": row.active_agents,
                "red_team": row.red_team,
                "judge": row.judge,
                "model_version": row.model_version,
                "generated_at": _iso(row.created_at),
                "decision_status": (
                    "prediction_only"
                    if experiment is None
                    else "bet"
                    if bet is not None
                    else "no_bet"
                ),
                "paper_bet_id": str(bet.id) if bet is not None else None,
                "paper_bet_status": bet.status.value if bet is not None else None,
                "paper_bet_selection": (
                    bet.selection.value if bet is not None else None
                ),
                "paper_bet_odds": _money(bet.odds_decimal) if bet is not None else None,
                "paper_bet_stake": _money(bet.stake) if bet is not None else None,
            }
        )
        if len(output) >= limit:
            break
    return output


@router.get("/bets")
def llm_bets(
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    try:
        experiment = active_experiment(session, "llm")
    except SQLAlchemyError:
        session.rollback()
        return []
    if experiment is None:
        return []
    home = aliased(Team)
    away = aliased(Team)
    try:
        rows = session.execute(
            select(
                PaperBet,
                Match.kickoff_at,
                Competition.code,
                home.name,
                away.name,
                Settlement,
            )
            .join(Match, Match.id == PaperBet.match_id)
            .join(Competition, Competition.id == Match.competition_id)
            .join(home, home.id == Match.home_team_id)
            .join(away, away.id == Match.away_team_id)
            .outerjoin(Settlement, Settlement.paper_bet_id == PaperBet.id)
            .where(PaperBet.experiment_id == experiment.id)
            .order_by(PaperBet.placed_at.desc(), PaperBet.id.desc())
            .limit(limit)
        ).all()
    except SQLAlchemyError:
        session.rollback()
        return []
    output: list[dict[str, Any]] = []
    for row in rows:
        bet: PaperBet = row[0]
        settlement: Settlement | None = row[5]
        payout = Decimal(str(settlement.payout)) if settlement is not None else None
        output.append(
            {
                "bet_id": str(bet.id),
                "match_id": str(bet.match_id),
                "kickoff_at": _iso(row[1]),
                "competition": row[2],
                "home_team": row[3],
                "away_team": row[4],
                "market": bet.market.value,
                "selection": bet.selection.value,
                "line_key": bet.line_key,
                "odds": str(bet.odds_decimal),
                "stake": _money(bet.stake),
                "status": bet.status.value,
                "placed_at": _iso(bet.placed_at),
                "settled_at": _iso(settlement.settled_at) if settlement else None,
                "payout": _money(payout),
                "profit": _money(payout - Decimal(str(bet.stake)))
                if payout is not None
                else None,
                "clv": str(settlement.clv) if settlement and settlement.clv is not None else None,
                "brier": str(settlement.brier_score)
                if settlement and settlement.brier_score is not None
                else None,
                "model_version": bet.analysis_run_key.split(":", 1)[0],
            }
        )
    return output


@router.get("/equity")
def llm_equity(request: Request, session: SessionDep) -> dict[str, Any]:
    try:
        experiment = active_experiment(session, "llm")
    except SQLAlchemyError:
        session.rollback()
        return {"initial": None, "points": []}
    if experiment is None:
        return {"initial": None, "points": []}
    initial = Decimal(str(experiment.initial_bankroll))
    try:
        rows = session.execute(
            select(Settlement.settled_at, Settlement.payout, PaperBet.stake)
            .join(PaperBet, PaperBet.id == Settlement.paper_bet_id)
            .where(
                PaperBet.experiment_id == experiment.id,
                Settlement.provisional.is_(False),
            )
            .order_by(Settlement.settled_at.asc(), Settlement.id.asc())
        ).all()
    except SQLAlchemyError:
        session.rollback()
        return {"initial": _money(initial), "points": []}
    balance = initial
    points: list[dict[str, str | None]] = [{"t": None, "bankroll": _money(initial)}]
    for settled_at, payout, stake in rows:
        balance = balance - Decimal(str(stake)) + Decimal(str(payout))
        points.append({"t": _iso(settled_at), "bankroll": _money(balance)})
    return {"initial": _money(initial), "points": points}
