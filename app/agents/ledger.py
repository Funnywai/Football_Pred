"""Paper-only agent ledger, kept apart from production and shadow books.

Settlement reuses ``settle_bets``; every bet records the decision run that
produced it, and one bet is allowed per ``(variant, match_id)``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.analyst import LineupSource
from app.agents.decision import (
    AGENT_DECISION,
    CompletionClient,
    decide_abc,
)
from app.agents.risk import ACTION_BET, AGENT_RISK, evaluate_risk
from app.agents.striker import StrikerLineupsClient
from app.config import Settings
from app.db.models import AgentBet, AgentDecision
from app.services.ledger import EquityPoint, LedgerSummary, settle_bets
from app.services.runs import track_run

AGENT_LEDGER_JOB_ID = "agent_ledger_update"
AGENT_ABC_JOB_ID = "agent_abc_update"
AGENT_VARIANTS = ("a_only", "abc")
DEFAULT_AGENT_VARIANT = "a_only"
AGENT_BY_VARIANT = {"a_only": AGENT_RISK, "abc": AGENT_DECISION}


class AbcRunSummary(NamedTuple):
    run_id: str
    matches_considered: int
    candidates: int
    briefs: int
    approved: int
    rejected: int
    prefilters: int
    llm_calls: int
    bets_settled: int
    bets_placed: int


def _check_variant(variant: str) -> None:
    if variant not in AGENT_VARIANTS:
        raise ValueError(f"unknown agent variant {variant!r}; expected one of {AGENT_VARIANTS}")


async def agent_bankroll_now(session: AsyncSession, settings: Settings, variant: str) -> float:
    """Derived agent bankroll for one variant: initial + realized − open stakes."""
    _check_variant(variant)
    settled = select(func.coalesce(func.sum(AgentBet.profit), 0.0)).where(
        AgentBet.variant == variant,
        AgentBet.status != "pending",
    )
    open_stakes = select(func.coalesce(func.sum(AgentBet.stake), 0.0)).where(
        AgentBet.variant == variant,
        AgentBet.status == "pending",
    )
    realized = (await session.execute(settled)).scalar_one()
    open_total = (await session.execute(open_stakes)).scalar_one()
    return settings.ledger_initial_bankroll + float(realized or 0.0) - float(open_total or 0.0)


async def agent_summary(
    session: AsyncSession, settings: Settings, variant: str
) -> LedgerSummary:
    """Aggregate summary for one agent variant, using the shared summary shape."""
    _check_variant(variant)
    rows = (
        await session.execute(
            select(AgentBet.status, AgentBet.stake, AgentBet.profit).where(
                AgentBet.variant == variant
            )
        )
    ).all()
    settled = [(status, stake, profit) for status, stake, profit in rows if status != "pending"]
    settled_stakes = sum(stake for _, stake, _ in settled)
    open_stakes = sum(stake for status, stake, _ in rows if status == "pending")
    realized = sum(profit if profit is not None else 0.0 for _, _, profit in settled)
    stakes_total = settled_stakes + open_stakes
    return LedgerSummary(
        initial_bankroll=settings.ledger_initial_bankroll,
        bankroll=settings.ledger_initial_bankroll + realized - open_stakes,
        n_bets=len(rows),
        n_settled=len(settled),
        n_open=len(rows) - len(settled),
        stakes_total=stakes_total,
        open_stakes=open_stakes,
        realized_profit=realized,
        roi=realized / settled_stakes if settled_stakes else 0.0,
        yield_pct=realized / stakes_total if stakes_total else 0.0,
    )


async def agent_equity_curve(
    session: AsyncSession, settings: Settings, variant: str
) -> list[EquityPoint]:
    """Realized-wealth points for one agent variant (mirrors the production curve)."""
    _check_variant(variant)
    bets = (
        (
            await session.execute(
                select(AgentBet)
                .where(AgentBet.variant == variant)
                .order_by(AgentBet.placed_at, AgentBet.id)
            )
        )
        .scalars()
        .all()
    )
    settled = sorted(
        [bet for bet in bets if bet.status != "pending" and bet.settled_at is not None],
        key=lambda bet: (bet.settled_at, bet.id),
    )
    points = [EquityPoint(t=None, bankroll=settings.ledger_initial_bankroll)]
    realized = 0.0
    for bet in settled:
        realized += bet.profit if bet.profit is not None else 0.0
        t_i = bet.settled_at
        assert t_i is not None  # filtered above
        open_at = sum(
            other.stake
            for other in bets
            if other.placed_at <= t_i and (other.settled_at is None or other.settled_at > t_i)
        )
        points.append(
            EquityPoint(t=t_i, bankroll=settings.ledger_initial_bankroll + realized - open_at)
        )
    points.append(
        EquityPoint(
            t=datetime.now(UTC),
            bankroll=await agent_bankroll_now(session, settings, variant),
        )
    )
    return points


async def place_agent_bets(
    session: AsyncSession,
    settings: Settings,
    run_id: str,
    variant: str = DEFAULT_AGENT_VARIANT,
) -> int:
    """Create paper bets from one agent run, one per match and variant.

    ``a_only`` reads the risk agent and ``abc`` reads the C decision agent. Only
    ``action=bet`` rows are used, stored odds/stake/edge are locked as-is, and
    existing ``(variant, match_id)`` bets make this idempotent.
    """
    _check_variant(variant)
    decisions = (
        (
            await session.execute(
                select(AgentDecision)
                .where(
                    AgentDecision.run_id == run_id,
                    AgentDecision.action == ACTION_BET,
                    AgentDecision.agent == AGENT_BY_VARIANT[variant],
                )
                .order_by(AgentDecision.match_id, AgentDecision.id)
            )
        )
        .scalars()
        .all()
    )
    if not decisions:
        return 0
    match_ids = {decision.match_id for decision in decisions}
    existing = set(
        (
            await session.execute(
                select(AgentBet.match_id).where(
                    AgentBet.variant == variant,
                    AgentBet.match_id.in_(match_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    bankroll = await agent_bankroll_now(session, settings, variant)
    placed = 0
    for decision in decisions:
        if decision.match_id in existing:
            continue
        if decision.odds is None or decision.stake is None:
            continue
        session.add(
            AgentBet(
                run_id=run_id,
                match_id=decision.match_id,
                model_version_id=decision.model_version_id,
                target=decision.target,
                outcome=decision.outcome,
                variant=variant,
                line=None,
                odds=decision.odds,
                stake=decision.stake,
                bankroll_at_place=bankroll,
                edge=decision.edge,
                kelly_multiplier=settings.ledger_kelly_multiplier,
            )
        )
        existing.add(decision.match_id)
        placed += 1
    await session.flush()
    return placed


async def agent_ledger_update(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    variant: str = DEFAULT_AGENT_VARIANT,
) -> int:
    """CLI entry point: settle confirmed agent bets, evaluate risk, then place.

    Tracks one ``ingestion_runs`` row under ``agent_ledger_update``. Returns the
    number of bets settled or placed.
    """
    _check_variant(variant)

    async def work(session: AsyncSession) -> int:
        settled = await settle_bets(session, AgentBet)
        risk = await evaluate_risk(session, settings)
        placed = await place_agent_bets(session, settings, risk.run_id, variant)
        return settled + placed

    return await track_run(session_factory, AGENT_LEDGER_JOB_ID, work)


async def agent_abc_update(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    striker_client: LineupSource | None = None,
    llm_client: CompletionClient | None = None,
    max_kickoff_minutes: int | None = None,
) -> AbcRunSummary:
    """Settle, run A, build B briefs, run C, then place the ``abc`` paper bets."""
    owned_striker = striker_client is None
    source: LineupSource = striker_client or StrikerLineupsClient(settings)
    holder: dict[str, AbcRunSummary] = {}

    async def work(session: AsyncSession) -> int:
        settled = await settle_bets(session, AgentBet)
        risk = await evaluate_risk(session, settings)
        decisions = await decide_abc(
            session,
            settings,
            risk.run_id,
            llm_client,
            striker_client=source,
            max_kickoff_minutes=max_kickoff_minutes,
        )
        placed = await place_agent_bets(session, settings, risk.run_id, "abc")
        holder["summary"] = AbcRunSummary(
            run_id=risk.run_id,
            matches_considered=risk.matches_considered,
            candidates=decisions.candidates,
            briefs=decisions.briefs,
            approved=decisions.approved,
            rejected=decisions.rejected,
            prefilters=decisions.prefilters,
            llm_calls=decisions.llm_calls,
            bets_settled=settled,
            bets_placed=placed,
        )
        return settled + placed

    try:
        await track_run(session_factory, AGENT_ABC_JOB_ID, work)
    finally:
        if owned_striker and isinstance(source, StrikerLineupsClient):
            await source.aclose()
    return holder["summary"]
