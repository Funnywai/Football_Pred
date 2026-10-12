"""Paper ledger (sub-system C): automated staking of champion value bets.

All amounts are HKD. Bankroll is derived from the bets table, never stored.
The scheduled entry point is ``ledger_update`` (settle confirmed results,
then place new bets); both passes are idempotent.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

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
from app.ml.labels import handicap_label, label_1x2
from app.ml.models import TARGET_HANDICAP
from app.ml.registry import STATUS_CHAMPION
from app.services.runs import track_run

logger = logging.getLogger(__name__)

LEDGER_JOB_ID = "ledger_update"


async def settle_bets(session: AsyncSession) -> int:
    """Settle pending bets whose match has a confirmed result (A-layer authority).

    Only ``Result`` rows with ``confirmed = True`` settle a bet. Handicap bets
    settle via ``handicap_label``: the bet's direction wins; a whole-line push
    (``None``) returns the stake. Idempotent: settled bets are never touched
    again. Returns the number of bets settled.
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
                logger.warning(
                    "handicap bet %s has no line; leaving it pending", bet.id
                )
                continue
            cover = handicap_label(result.home_score, result.away_score, bet.line)
            if cover is None:
                bet.status = "push"
                bet.payout = bet.stake
            elif cover == bet.outcome:
                bet.status = "won"
                bet.payout = bet.stake * bet.odds
            else:
                bet.status = "lost"
                bet.payout = 0.0
        elif label_1x2(result.home_score, result.away_score) == bet.outcome:
            bet.status = "won"
            bet.payout = bet.stake * bet.odds
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
    """Fractional-Kelly stake, capped downward only. None = below HKD 10 → skip.

    Never raises a stake up to the minimum; the rule is uniform for every
    market (HAD today; any later market the same).
    """
    raw = round(
        bankroll_batch_start * recommended_fraction * settings.ledger_kelly_multiplier,
        2,
    )
    cap = settings.ledger_max_stake_fraction * bankroll_batch_start
    stake = min(raw, cap)
    if stake < settings.ledger_min_stake:
        return None
    return stake


async def place_bets(session: AsyncSession, settings: Settings) -> int:
    """Place fractional-Kelly bets on unbet champion value predictions.

    Selection: the prediction must belong to the current champion
    (``ModelVersion.status = champion``), carry ``recommended_fraction > 0``,
    and have no bet for the same ``(match_id, target, outcome)`` in any
    status. One batch shares one ``bankroll_batch_start``. Handicap bets lock
    the champion's hdc_line recomputed via ``load_market_priors`` at placement
    time and are skipped when that line is unavailable. Returns bets placed.
    """
    bankroll_batch_start = await _bankroll_now(session, settings)
    candidates = (
        (
            await session.execute(
                select(Prediction)
                .join(ModelVersion, ModelVersion.id == Prediction.model_version_id)
                .where(ModelVersion.status == STATUS_CHAMPION)
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
        priors = await load_market_priors(session, target_rows)
        lines = {match_id: prior.hdc_line for match_id, prior in priors.items()}
    placed = 0
    for prediction in candidates:
        key = (prediction.match_id, prediction.target, prediction.outcome)
        if key in betted:
            continue
        if prediction.target == TARGET_HANDICAP:
            line = lines.get(prediction.match_id)
            if line is None:
                logger.info(
                    "skipping handicap bet on match %s: no hdc line", prediction.match_id
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
