"""Paper/audit agents for the A (risk), B (lineups), and C (decision) split.

Everything here is paper-only: no real bet and no write to the production or
shadow ledger. Phase 3a adds the lineups-only analyst brief and the LLM-backed
C decision agent used by the ``abc`` variant.
"""

from app.agents.analyst import BriefError, build_brief
from app.agents.decision import (
    AGENT_DECISION,
    DecisionRunSummary,
    decide_abc,
)
from app.agents.ledger import (
    AGENT_ABC_JOB_ID,
    AGENT_LEDGER_JOB_ID,
    AGENT_VARIANTS,
    DEFAULT_AGENT_VARIANT,
    AbcRunSummary,
    agent_abc_update,
    agent_bankroll_now,
    agent_equity_curve,
    agent_ledger_update,
    agent_summary,
    place_agent_bets,
)
from app.agents.llm import AgentLLMClient, AgentLLMError
from app.agents.risk import RiskRunSummary, evaluate_risk
from app.agents.schemas import AgentBriefOut, AgentDecisionOut
from app.agents.striker import LineupFetch, StrikerError, StrikerLineupsClient

__all__ = [
    "AGENT_ABC_JOB_ID",
    "AGENT_DECISION",
    "AGENT_LEDGER_JOB_ID",
    "AGENT_VARIANTS",
    "DEFAULT_AGENT_VARIANT",
    "AbcRunSummary",
    "AgentBriefOut",
    "AgentDecisionOut",
    "AgentLLMClient",
    "AgentLLMError",
    "BriefError",
    "DecisionRunSummary",
    "LineupFetch",
    "RiskRunSummary",
    "StrikerError",
    "StrikerLineupsClient",
    "agent_abc_update",
    "agent_bankroll_now",
    "agent_equity_curve",
    "agent_ledger_update",
    "agent_summary",
    "build_brief",
    "decide_abc",
    "evaluate_risk",
    "place_agent_bets",
]
