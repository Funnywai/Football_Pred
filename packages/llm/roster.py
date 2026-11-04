from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    agent_id: str
    name: str
    scope: str
    kind: str
    phase: str = "phase-3"


AGENTS: tuple[AgentDefinition, ...] = (
    AgentDefinition("market_agent", "Market", "Odds, implied probability, line movement", "specialist"),
    AgentDefinition("form_agent", "Form", "Domestic and European form, schedule strength", "specialist"),
    AgentDefinition("tactical_agent", "Tactical", "Shape, matchup, pressing and set pieces", "specialist"),
    AgentDefinition("availability_agent", "Availability", "Injuries, suspensions, rotation and lineups", "specialist"),
    AgentDefinition("context_agent", "Context", "Rest, travel, venue, weather and motivation", "specialist"),
    AgentDefinition("base_rate_agent", "Base rates", "Competition base rates and scoring environment", "specialist"),
    AgentDefinition("red_team_agent", "Red team", "Challenges consensus and hunts narrative bias", "critic"),
    AgentDefinition("judge_agent", "Judge", "Synthesizes disagreement and abstention advice", "aggregator"),
    AgentDefinition("risk_agent", "Risk", "Deterministic paper-ledger gates", "guardrail"),
)
