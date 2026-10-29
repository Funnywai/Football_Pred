"""Prompt construction and response validation for the C decision agent."""

from __future__ import annotations

import json
from datetime import datetime

from app.agents.analyst import STANDARD_STARTERS
from app.db.models import AgentDecision, AnalystBrief

AGENT_DECISION = "decision"
DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"
MAX_REASON_LENGTH = 255

SYSTEM_PROMPT = """You are the C decision agent for a paper-only football betting A/B test.
You may only approve or reject the supplied A candidate.
You cannot change the outcome, stake, odds, or match.
The execution price is HKJC and is not yours to edit.
Approve only when the supplied lineups are complete (11 starters per team)
and the data is fresh and internally consistent.
If any data is missing, stale, partial, or contradictory, reject.
Reply with JSON only, exactly:
{"decision":"approve"|"reject","confidence":0.0-1.0,"reason":"..."}"""


def truncate_reason(reason: str) -> str:
    return reason[:MAX_REASON_LENGTH]


def blocking_reason(brief: AnalystBrief) -> str | None:
    facts = brief.facts
    home_starters = facts.get("home_starters")
    away_starters = facts.get("away_starters")
    complete = (
        isinstance(home_starters, int)
        and isinstance(away_starters, int)
        and home_starters == STANDARD_STARTERS
        and away_starters == STANDARD_STARTERS
    )
    if brief.trust_score is None or brief.trust_score < 1.0 or not complete:
        detail = ", ".join(str(value) for value in brief.missing) or "trust below 1.0"
        return f"lineups missing or partial ({detail})"
    return None


def candidate_payload(
    decision: AgentDecision, brief: AnalystBrief, kickoff: datetime | None
) -> dict[str, object]:
    return {
        "a_candidate": {
            "decision_id": decision.id,
            "match_id": decision.match_id,
            "target": decision.target,
            "outcome": decision.outcome,
            "hkjc_execution_odds": decision.odds,
            "execution_edge": decision.edge,
            "stake": decision.stake,
            "signal_edge": decision.signal_edge,
            "a_reason": decision.reason,
        },
        "lineups": brief.facts,
        "missing": brief.missing,
        "uncertainties": brief.uncertainties,
        "trust_score": brief.trust_score,
        "kickoff_time": kickoff.isoformat() if kickoff is not None else None,
    }


def build_prompt(
    decision: AgentDecision, brief: AnalystBrief, kickoff: datetime | None
) -> str:
    return (
        "Decide whether to approve this A candidate. Output JSON only. "
        "If the lineups are missing, partial, stale, or inconsistent, reject.\n"
        + json.dumps(
            candidate_payload(decision, brief, kickoff),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def validate_response(data: dict[str, object]) -> tuple[str, float, str]:
    raw_decision = data.get("decision")
    if not isinstance(raw_decision, str):
        raise TypeError("missing decision")
    decision = raw_decision.strip().lower()
    if decision not in (DECISION_APPROVE, DECISION_REJECT):
        raise ValueError("decision must be approve or reject")
    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise TypeError("confidence must be a number")
    score = float(confidence)
    if not 0.0 <= score <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    raw_reason = data.get("reason")
    reason = (
        raw_reason.strip()
        if isinstance(raw_reason, str) and raw_reason.strip()
        else f"LLM {decision}"
    )
    return decision, score, reason
