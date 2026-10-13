"""Paper ledger (sub-system C): automated staking of champion value bets.

All amounts are HKD. Bankroll is derived from the bets table, never stored.
The scheduled entry point is ``ledger_update`` (settle confirmed results,
then place new bets); both passes are idempotent.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import (
    League,
    LedgerBet,
    Match,
    ModelVersion,
    Prediction,
    Result,
    Season,
)
from app.ml.dataset import load_market_priors
from app.ml.features import MatchRow
from app.ml.labels import handicap_label, is_whole_or_half, label_1x2, quarter_halves
from app.ml.models import TARGET_HANDICAP
from app.ml.registry import STATUS_CHAMPION
from app.services.runs import track_run

logger = logging.getLogger(__name__)

LEDGER_JOB_ID = "ledger_update"


DIVIDEND_ROUNDING_CENTS = 10


def _round_dividend(amount: float) -> float:
    """HKJC football Rule 2.19(a): a dividend is rounded to the nearest 10 cents.

    Half-up, not Python's banker's rounding (``round(35.25, 1)`` gives 35.2). A returned
    stake is not a dividend and is passed through unchanged.
    """
    return math.floor(amount * DIVIDEND_ROUNDING_CENTS + 0.5) / DIVIDEND_ROUNDING_CENTS


def _settle_handicap(bet: LedgerBet, home_score: int, away_score: int) -> tuple[str, float]:
    """``(status, payout)`` for a handicap bet: whole/half line, or a quarter line.

    A quarter line is two half-stakes on the two adjacent half-lines; when one half
    pushes and the other wins/loses the bet is ``half_won``/``half_lost``.
    """
    halves = quarter_halves(bet.line) if bet.line is not None else None
    if halves is None:
        if bet.line is None:
            return "push", bet.stake
        cover = handicap_label(home_score, away_score, bet.line)
        if cover is None:
            return "push", bet.stake
        if cover == bet.outcome:
            return "won", _round_dividend(bet.stake * bet.odds)
        return "lost", 0.0

    half_stake = bet.stake / 2.0
    half_results: list[str] = []
    payout = 0.0
    for half_line in halves:
        cover = handicap_label(home_score, away_score, half_line)
        if cover is None:
            half_results.append("push")
            payout += half_stake
        elif cover == bet.outcome:
            half_results.append("won")
            payout += half_stake * bet.odds
        else:
            half_results.append("lost")
    settled_half = set(half_results)
    if settled_half == {"won"}:
        status = "won"
    elif settled_half == {"lost"}:
        status = "lost"
    elif settled_half == {"push"}:
        status = "push"
    elif "won" in settled_half:
        status = "half_won"
    else:
        status = "half_lost"
    return status, _round_dividend(payout)


async def settle_bets(session: AsyncSession) -> int:
    """Settle pending bets whose match has a confirmed result (A-layer authority).

    Only ``Result`` rows with ``confirmed = True`` settle a bet. Whole/half
    handicap lines settle via ``handicap_label`` (a whole-line push returns the
    stake); quarter lines settle via ``_settle_handicap``, splitting the stake
    across the two half-lines into ``won``/``half_won``/``half_lost``/``lost``.
    Idempotent: settled bets are never touched again. Returns the number of bets
    settled.
    """
    stmt = (
        select(LedgerBet, Result)
        .join(Match, Match.id == LedgerBet.match_id)
        .join(Result, Result.match_id == Match.id)
        .where(LedgerBet.status == "pending")
        .where(Result.confirmed.is_(True))
    )
    rows = (await session.execute(stmt)).all()
    settled = 0
    for bet, result in rows:
        if bet.target == "handicap":
            if bet.line is None:
                logger.warning("handicap bet %s has no line; leaving it pending", bet.id)
                continue
            bet.status, bet.payout = _settle_handicap(bet, result.home_score, result.away_score)
        elif label_1x2(result.home_score, result.away_score) == bet.outcome:
            bet.status = "won"
            bet.payout = _round_dividend(bet.stake * bet.odds)
        else:
            bet.status = "lost"
            bet.payout = 0.0
        bet.profit = bet.payout - bet.stake
        bet.settled_at = datetime.now(UTC)
        bet.result_source = result.source
        settled += 1
    await session.flush()
    return settled


async def _bankroll_now(session: AsyncSession, settings: Settings) -> float:
    """Derived bankroll: initial + settled profit − open stakes. Never stored."""
    settled = select(func.coalesce(func.sum(LedgerBet.profit), 0.0)).where(
        LedgerBet.status != "pending"
    )
    open_stakes = select(func.coalesce(func.sum(LedgerBet.stake), 0.0)).where(
        LedgerBet.status == "pending"
    )
    realized = (await session.execute(settled)).scalar_one()
    open_total = (await session.execute(open_stakes)).scalar_one()
    return settings.ledger_initial_bankroll + float(realized) - float(open_total)


def _size_stake(
    bankroll_batch_start: float,
    recommended_fraction: float,
    settings: Settings,
) -> float | None:
    """Fractional-Kelly stake in whole HKD, capped downward only. None = below the
    minimum → skip.

    HKJC takes whole dollars (``ledger_min_stake`` is its bet unit), so the stake is
    floored — never rounded up, never raised to the minimum: the rule is uniform for
    every market (HAD today; any later market the same).
    """
    raw = math.floor(
        bankroll_batch_start * recommended_fraction * settings.ledger_kelly_multiplier
    )
    cap = math.floor(settings.ledger_max_stake_fraction * bankroll_batch_start)
    stake = float(min(raw, cap))
    if stake < settings.ledger_min_stake:
        return None
    return stake


async def place_bets(session: AsyncSession, settings: Settings) -> int:
    """Place fractional-Kelly bets on unbet champion value predictions.

    Selection: the prediction must belong to the current champion
    (``ModelVersion.status = champion``), carry ``recommended_fraction > 0``,
    and have no bet for the same ``(match_id, target, outcome)`` in any
    status. Matches must not have kicked off yet (kickoff strictly after now),
    so skipped predictions are never retro-actively bet on finished matches.
    One batch shares one ``bankroll_batch_start``. Handicap bets lock
    the champion's hdc_line recomputed via ``load_market_priors`` at placement
    time and are skipped when that line is unavailable. Returns bets placed.
    """
    bankroll_batch_start = await _bankroll_now(session, settings)
    candidates = (
        (
            await session.execute(
                select(Prediction)
                .join(ModelVersion, ModelVersion.id == Prediction.model_version_id)
                .join(Match, Match.id == Prediction.match_id)
                .where(ModelVersion.status == STATUS_CHAMPION)
                .where(Match.kickoff_time > datetime.now(UTC))
                .where(Prediction.recommended_fraction > 0)
                .order_by(Prediction.match_id, Prediction.target, Prediction.outcome)
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        return 0
    by_match: dict[int, list[Prediction]] = {}
    for prediction in candidates:
        by_match.setdefault(prediction.match_id, []).append(prediction)
    betted: set[tuple[int, str, str]] = set()
    existing_rows = (
        await session.execute(
            select(LedgerBet.match_id, LedgerBet.target, LedgerBet.outcome).where(
                LedgerBet.match_id.in_(list(by_match))
            )
        )
    ).all()
    betted = {(m, t, o) for m, t, o in existing_rows}
    lines: dict[int, float | None] = {}
    handicap_matches = [
        mid for mid, preds in by_match.items() if any(p.target == TARGET_HANDICAP for p in preds)
    ]
    if handicap_matches:
        fields = (
            await session.execute(
                select(Match, League.code, Season.label)
                .join(League, League.id == Match.league_id)
                .join(Season, Season.id == Match.season_id)
                .where(Match.id.in_(handicap_matches))
            )
        ).all()
        target_rows = [
            MatchRow(
                match_id=m.id,
                kickoff_time=m.kickoff_time,
                home_team_id=m.home_team_id,
                away_team_id=m.away_team_id,
                league_code=code,
                season_label=label,
            )
            for m, code, label in fields
        ]
        priors = await load_market_priors(session, target_rows, settings.ml_prior_lead_hours)
        lines = {match_id: prior.hdc_line for match_id, prior in priors.items()}
    placed = 0
    for prediction in candidates:
        key = (prediction.match_id, prediction.target, prediction.outcome)
        if key in betted:
            continue
        if prediction.target == TARGET_HANDICAP:
            line = lines.get(prediction.match_id)
            if line is None or not is_whole_or_half(line):
                logger.info(
                    "skipping handicap bet on match %s: no usable hdc line",
                    prediction.match_id,
                )
                continue
        else:
            line = None
        if prediction.market_odds is None:
            continue
        stake = _size_stake(bankroll_batch_start, prediction.recommended_fraction, settings)
        if stake is None:
            logger.info(
                "skipping bet on match %s %s/%s: below HKD %.2f minimum",
                prediction.match_id, prediction.target, prediction.outcome,
                settings.ledger_min_stake,
            )
            continue
        session.add(
            LedgerBet(
                match_id=prediction.match_id,
                target=prediction.target,
                outcome=prediction.outcome,
                model_version_id=prediction.model_version_id,
                line=line,
                odds=prediction.market_odds,
                stake=stake,
                bankroll_at_place=bankroll_batch_start,
                edge=prediction.edge,
                kelly_multiplier=settings.ledger_kelly_multiplier,
            )
        )
        betted.add(key)
        placed += 1
    await session.flush()
    return placed


async def ledger_update(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> int:
    """Scheduled entry point: settle confirmed results, then place new bets."""

    async def work(session: AsyncSession) -> int:
        settled = await settle_bets(session)
        placed = await place_bets(session, settings)
        return settled + placed

    return await track_run(session_factory, LEDGER_JOB_ID, work)


class LedgerSummary(NamedTuple):
    initial_bankroll: float
    bankroll: float
    n_bets: int
    n_settled: int
    n_open: int
    stakes_total: float
    open_stakes: float
    realized_profit: float
    roi: float
    yield_pct: float


async def summary(session: AsyncSession, settings: Settings) -> LedgerSummary:
    """Aggregate every summary value from the bets table (single source of truth)."""
    rows = (
        await session.execute(select(LedgerBet.status, LedgerBet.stake, LedgerBet.profit))
    ).all()
    settled = [
        (status, stake, profit) for status, stake, profit in rows if status != "pending"
    ]
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


class EquityPoint(NamedTuple):
    t: datetime | None
    bankroll: float


async def equity_curve(session: AsyncSession, settings: Settings) -> list[EquityPoint]:
    """Realized-wealth points: the initial bankroll, one point per settlement, final = now.

    At each settlement event the bankroll equals the initial bankroll plus
    settled profit so far, minus the stakes that are open as of that event
    (placed by then and settled strictly later, or never). Settlement events
    with the same timestamp are ordered by bet id (deterministic).
    """
    bets = (
        (
            await session.execute(select(LedgerBet).order_by(LedgerBet.placed_at, LedgerBet.id))
        )
        .scalars()
        .all()
    )
    settled = sorted(
        [bet for bet in bets if bet.status != "pending"],
        key=lambda bet: (bet.settled_at, bet.id),
    )
    points = [EquityPoint(t=None, bankroll=settings.ledger_initial_bankroll)]
    realized = 0.0
    for bet in settled:
        realized += bet.profit if bet.profit is not None else 0.0
        t_i = bet.settled_at
        open_at = sum(
            other.stake
            for other in bets
            if other.placed_at <= t_i and (other.settled_at is None or other.settled_at > t_i)
        )
        points.append(
            EquityPoint(t=t_i, bankroll=settings.ledger_initial_bankroll + realized - open_at)
        )
    points.append(
        EquityPoint(t=datetime.now(UTC), bankroll=await _bankroll_now(session, settings))
    )
    return points
