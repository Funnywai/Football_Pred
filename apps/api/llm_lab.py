from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from packages.llm.prompts.registry import PromptRegistry
from packages.llm.roster import AGENTS

router = APIRouter(prefix="/llm", tags=["llm"])

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts" / "llm"
_PHASE = "foundation"
_INITIAL_WEIGHT = Decimal(1) / Decimal(len(AGENTS))


def _prompt_payloads() -> list[dict[str, Any]]:
    registry = PromptRegistry.from_directory(_PROMPT_DIR)
    return [
        {
            "name": record.name,
            "sha256": record.sha256,
            "bytes": len(record.text.encode("utf-8")),
        }
        for record in (registry.get("system"), registry.get("market_agent"))
    ]


@router.get("/status")
def llm_status() -> dict[str, Any]:
    prompts = _prompt_payloads()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "phase": _PHASE,
        "runtime": {
            "decision_layer": "llm_not_connected",
            "data_plane": "deterministic",
            "paper_ledger": "separate_not_opened",
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
            "evidence_packets": 0,
            "agent_runs": 0,
            "predictions": 0,
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
