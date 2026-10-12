"""Paper ledger (sub-system C): automated staking of champion value bets.

All amounts are HKD. Bankroll is derived from the bets table, never stored.
The scheduled entry point is ``ledger_update`` (settle confirmed results,
then place new bets); both passes are idempotent.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LedgerBet, Match, Result
from app.ml.labels import handicap_label, label_1x2

logger = logging.getLogger(__name__)


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
