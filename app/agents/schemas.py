from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AgentBriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: str
    match_id: int
    source: str
    captured_at: datetime
    facts: dict[str, Any]
    uncertainties: list[str]
    missing: list[str]
    trust_score: float | None
    raw_snapshot: dict[str, Any]


class AgentDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: str
    match_id: int
    model_version_id: int
    target: str
    outcome: str
    action: str
    stake: float | None
    odds: float | None
    edge: float | None
    signal_edge: float | None
    confidence: float | None
    agent: str
    reason: str
    input_snapshot: dict[str, Any]
    evaluated_at: datetime
    league_code: str
    home_team: str
    away_team: str
