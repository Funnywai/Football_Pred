from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROBABILITY_TOLERANCE = Decimal("0.001")
HAD_OUTCOMES = ("H", "D", "A")


class ResearchFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    confidence: Decimal = Field(ge=0, le=1)
    direction: Literal["H", "D", "A", "neutral", "abstain"] = "neutral"
    evidence_refs: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    abstain: bool = False
    abstain_reason: str | None = None

    @field_validator("agent_id")
    @classmethod
    def non_empty_agent(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("agent_id must not be blank")
        return value

    @model_validator(mode="after")
    def abstain_is_consistent(self) -> ResearchFinding:
        if self.abstain and self.direction != "abstain":
            raise ValueError("abstaining findings must use direction=abstain")
        if not self.abstain and not self.evidence_refs:
            raise ValueError("non-abstaining findings must cite evidence_refs")
        return self


class MainAgentDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    report: dict[str, Any]
    probabilities: dict[Literal["H", "D", "A"], Decimal]
    recommended_side: Literal["H", "D", "A", "abstain"]
    recommended_stake_pct: Decimal = Field(ge=0, le=1)
    confidence: Decimal = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list)
    abstain: bool = False
    abstain_reason: str | None = None

    @field_validator("probabilities")
    @classmethod
    def validate_probabilities(
        cls, value: Mapping[str, Decimal]
    ) -> dict[str, Decimal]:
        if set(value) != set(HAD_OUTCOMES):
            raise ValueError("probabilities must contain exactly H, D, A")
        if any(probability < 0 or probability > 1 for probability in value.values()):
            raise ValueError("probabilities must be between 0 and 1")
        if abs(sum(value.values(), Decimal(0)) - Decimal(1)) > PROBABILITY_TOLERANCE:
            raise ValueError("probabilities must sum to 1")
        return dict(value)

    @model_validator(mode="after")
    def abstain_is_consistent(self) -> MainAgentDecision:
        if self.abstain and self.recommended_side != "abstain":
            raise ValueError("abstaining decision must use recommended_side=abstain")
        if self.abstain and self.recommended_stake_pct != 0:
            raise ValueError("abstaining decision must use stake_pct=0")
        return self


ROLE_AGENTS: tuple[tuple[str, str, str], ...] = (
    ("environment_agent", "Environment", "venue, weather, travel, rest, home environment"),
    ("availability_agent", "Availability", "lineups, injuries, suspensions, rotation"),
    ("market_agent", "Market", "odds, implied probability, line movement, market disagreement"),
    ("form_agent", "Form", "recent matches, home/away splits, schedule strength"),
    ("tactical_agent", "Tactical", "formation, pressing, build-up, set pieces, matchups"),
    ("news_agent", "News", "team news, manager comments, motivation, off-field context"),
    ("base_rate_agent", "Base rate", "competition base rates, draw frequency, scoring environment"),
)
