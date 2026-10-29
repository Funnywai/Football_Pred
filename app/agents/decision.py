"""C decision agent: approve or reject an A candidate after a lineups-only brief.

The LLM is advisory infrastructure, not a price source: it can only return
``approve`` or ``reject``. Stake, odds, and edge always come from the A decision,
and only an approval copies them. Missing or partial lineups are rejected before
the LLM is called, so a provider outage can never create a bet.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import NamedTuple, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.analyst import LineupSource, build_brief
from app.agents.decision_support import (
    AGENT_DECISION,
    DECISION_APPROVE,
    SYSTEM_PROMPT,
    blocking_reason,
    build_prompt,
    candidate_payload,
    truncate_reason,
    validate_response,
)
from app.agents.llm import AgentLLMClient, AgentLLMError, session_id_for
from app.agents.risk import ACTION_BET, ACTION_NO_BET, AGENT_RISK
from app.config import Settings
from app.db.models import AgentDecision, AnalystBrief, Match


class CompletionClient(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = ...,
        session_id: str | None = None,
    ) -> dict[str, object]: ...


class DecisionRunSummary(NamedTuple):
    run_id: str
    candidates: int
    approved: int
    rejected: int
    prefilters: int
    llm_calls: int
    briefs: int


async def a_bet_decisions(session: AsyncSession, run_id: str) -> list[AgentDecision]:
    rows = (
        (
            await session.execute(
                select(AgentDecision)
                .where(
                    AgentDecision.run_id == run_id,
                    AgentDecision.action == ACTION_BET,
                    AgentDecision.agent == AGENT_RISK,
                )
                .order_by(AgentDecision.match_id, AgentDecision.id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def _write_decision(
    session: AsyncSession,
    *,
    run_id: str,
    candidate: AgentDecision,
    action: str,
    confidence: float | None,
    reason: str,
    snapshot: dict[str, object],
    evaluated_at: datetime,
) -> None:
    approved = action == ACTION_BET
    session.add(
        AgentDecision(
            run_id=run_id,
            match_id=candidate.match_id,
            model_version_id=candidate.model_version_id,
            target=candidate.target,
            outcome=candidate.outcome,
            action=action,
            stake=candidate.stake if approved else None,
            odds=candidate.odds if approved else None,
            edge=candidate.edge if approved else None,
            signal_edge=candidate.signal_edge,
            confidence=confidence,
            agent=AGENT_DECISION,
            reason=truncate_reason(reason),
            evaluated_at=evaluated_at,
            input_snapshot=snapshot,
        )
    )


async def decide_abc(
    session: AsyncSession,
    settings: Settings,
    run_id: str,
    llm_client: CompletionClient | None = None,
    *,
    briefs: Sequence[AnalystBrief] | None = None,
    striker_client: LineupSource | None = None,
    max_kickoff_minutes: int | None = None,
) -> DecisionRunSummary:
    candidates = await a_bet_decisions(session, run_id)
    prebuilt = {brief.match_id: brief for brief in briefs or ()}
    kickoffs = dict(
        (
            await session.execute(
                select(Match.id, Match.kickoff_time).where(
                    Match.id.in_([candidate.match_id for candidate in candidates])
                )
            )
        ).all()
    )
    if max_kickoff_minutes is not None:
        now = datetime.now(UTC)
        cutoff = now + timedelta(minutes=max_kickoff_minutes)
        candidates = [
            candidate
            for candidate in candidates
            if (kickoff := kickoffs.get(candidate.match_id)) is not None
            and now < kickoff <= cutoff
        ]
    owned_llm = llm_client is None
    client = llm_client or AgentLLMClient(settings)
    approved = rejected = prefilters = llm_calls = 0
    used_briefs: set[int] = set()
    evaluated_at = datetime.now(UTC)
    try:
        for candidate in candidates:
            existing = (
                await session.execute(
                    select(AgentDecision).where(
                        AgentDecision.run_id == run_id,
                        AgentDecision.match_id == candidate.match_id,
                        AgentDecision.agent == AGENT_DECISION,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing.action == ACTION_BET:
                    approved += 1
                else:
                    rejected += 1
                continue
            brief = prebuilt.get(candidate.match_id)
            if brief is None:
                brief = await build_brief(
                    session,
                    settings,
                    run_id,
                    candidate.match_id,
                    striker_client=striker_client,
                )
            used_briefs.add(brief.id)
            kickoff = kickoffs.get(candidate.match_id)
            snapshot: dict[str, object] = {
                "a_decision_id": candidate.id,
                "brief_id": brief.id,
                "brief_run_id": brief.run_id,
                "model": settings.agent_llm_model,
                "a_decision": candidate_payload(candidate, brief, kickoff)["a_candidate"],
                "lineups": brief.facts,
                "missing": brief.missing,
                "uncertainties": brief.uncertainties,
                "llm_called": False,
                "system": None,
                "prompt": None,
                "response": None,
            }
            blocking = blocking_reason(brief)
            if blocking is not None:
                prefilters += 1
                rejected += 1
                _write_decision(
                    session,
                    run_id=run_id,
                    candidate=candidate,
                    action=ACTION_NO_BET,
                    confidence=None,
                    reason=f"prefilter: {blocking}",
                    snapshot=snapshot,
                    evaluated_at=evaluated_at,
                )
                continue

            prompt = build_prompt(candidate, brief, kickoff)
            snapshot.update(
                {"llm_called": True, "system": SYSTEM_PROMPT, "prompt": prompt}
            )
            llm_calls += 1
            try:
                data = await client.complete(
                    prompt,
                    system=SYSTEM_PROMPT,
                    session_id=session_id_for(run_id, candidate.match_id),
                )
            except AgentLLMError as exc:
                rejected += 1
                snapshot.update({"response": None, "error": str(exc)})
                _write_decision(
                    session,
                    run_id=run_id,
                    candidate=candidate,
                    action=ACTION_NO_BET,
                    confidence=None,
                    reason=f"llm_error: {exc}",
                    snapshot=snapshot,
                    evaluated_at=evaluated_at,
                )
                continue
            snapshot["response"] = data
            try:
                verdict, confidence, llm_reason = validate_response(data)
            except (TypeError, ValueError) as exc:
                rejected += 1
                _write_decision(
                    session,
                    run_id=run_id,
                    candidate=candidate,
                    action=ACTION_NO_BET,
                    confidence=None,
                    reason=f"llm_malformed: {exc}",
                    snapshot=snapshot,
                    evaluated_at=evaluated_at,
                )
                continue
            if verdict == DECISION_APPROVE:
                approved += 1
                action = ACTION_BET
                reason = f"approved: {llm_reason}"
            else:
                rejected += 1
                action = ACTION_NO_BET
                reason = f"rejected: {llm_reason}"
            _write_decision(
                session,
                run_id=run_id,
                candidate=candidate,
                action=action,
                confidence=confidence,
                reason=reason,
                snapshot=snapshot,
                evaluated_at=evaluated_at,
            )
    finally:
        if owned_llm and isinstance(client, AgentLLMClient):
            await client.aclose()
    await session.flush()
    return DecisionRunSummary(
        run_id=run_id,
        candidates=len(candidates),
        approved=approved,
        rejected=rejected,
        prefilters=prefilters,
        llm_calls=llm_calls,
        briefs=len(used_briefs),
    )
