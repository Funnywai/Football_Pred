from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from apps.api.dashboard import SessionDep
from packages.db.models import (
    Competition,
    LlmAgentRun,
    LlmEnsemblePrediction,
    LlmEvidencePacket,
    Match,
    Team,
)
from packages.llm.prompts.registry import PromptRegistry
from packages.llm.roster import AGENTS

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


@router.get("/status")
def llm_status(request: Request, session: SessionDep) -> dict[str, Any]:
    prompts = _prompt_payloads()
    settings = getattr(request.app.state, "settings", None)
    enabled = bool(getattr(settings, "llm_enabled", False))
    provider = getattr(settings, "llm_provider", "openai_compatible")
    model = getattr(settings, "llm_model", "deepseek-v4.1-flash")
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "phase": _PHASE,
        "runtime": {
            "decision_layer": "configured" if enabled else "llm_not_connected",
            "data_plane": "deterministic",
            "paper_ledger": "separate_not_opened",
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
            "paper_bets": 0,
        },
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
        output.append(
            {
                "match_id": match_id,
                "kickoff_at": _iso(match.kickoff_at),
                "competition": competition.code if competition else None,
                "home_team": home.name if home else None,
                "away_team": away.name if away else None,
                "probabilities": row.probabilities,
                "weights": row.weights,
                "active_agents": row.active_agents,
                "red_team": row.red_team,
                "judge": row.judge,
                "model_version": row.model_version,
                "generated_at": _iso(row.created_at),
                "decision_status": "prediction_only",
            }
        )
        if len(output) >= limit:
            break
    return output
