from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import (
    Competition,
    MarketLine,
    Match,
    ModelPrediction,
    OddsSnapshot,
    PaperBet,
    Team,
)
from packages.decision.service import decide_match
from packages.domain.enums import (
    BetStatus,
    MarketType,
    MatchStatus,
    Side,
    SnapshotKind,
)
from packages.ingest.normalize import seed_competitions
from packages.ledger.service import INITIAL_BANKROLL, LedgerService

BATCH_SIZE = 30
BATCH_HOME_ODDS = Decimal("2.00")
BATCH_DRAW_ODDS = Decimal("3.40")
BATCH_AWAY_ODDS = Decimal("3.80")
BATCH_BASE_KICKOFF = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class BatchDryRunResult:
    matches: int
    bets: int
    predictions: int
    settled: int
    bankroll: Decimal
    roi: Decimal


def _ensure_batch_teams(session: Session) -> tuple[Team, Team]:
    seeded = {
        "batch-home": ("Batch Home", "BTH", "England"),
        "batch-away": ("Batch Away", "BTA", "England"),
    }
    existing = {
        team.slug: team
        for team in session.scalars(
            select(Team).where(Team.slug.in_(seeded))
        ).all()
    }
    for slug, (name, short_name, country) in seeded.items():
        if slug not in existing:
            team = Team(
                slug=slug,
                name=name,
                short_name=short_name,
                country=country,
            )
            session.add(team)
            existing[slug] = team
    session.flush()
    return existing["batch-home"], existing["batch-away"]


def _add_market_lines(
    session: Session,
    snapshot: OddsSnapshot,
) -> None:
    for index, (side, odds) in enumerate(
        (
            (Side.H, BATCH_HOME_ODDS),
            (Side.D, BATCH_DRAW_ODDS),
            (Side.A, BATCH_AWAY_ODDS),
        )
    ):
        session.add(
            MarketLine(
                snapshot_id=snapshot.id,
                odds_type=MarketType.HAD,
                condition_raw="0.0",
                line_index=index,
                side=side,
                odds_decimal=odds,
                pool_status="SELLINGSTARTED",
                line_status="AVAILABLE",
                is_main=True,
                offer_early_settlement=False,
            )
        )
    session.flush()


def _settlement_goals(index: int) -> tuple[int, int]:
    if index < 10:
        return 0, 1
    if index < 20:
        return 1, 1
    return 1, 0


def run_30_match_dry_run(
    session: Session,
    *,
    count: int = BATCH_SIZE,
    initial_bankroll: Decimal = INITIAL_BANKROLL,
) -> BatchDryRunResult:
    """Engineering-only batch for duplicate, bankroll and settlement wiring.

    It uses synthetic fixtures and odds; it is not predictive evidence.
    """
    if count <= 0:
        raise ValueError("count must be positive")
    seed_competitions(session)
    competition = session.execute(
        select(Competition).where(Competition.code == "EPL")
    ).scalar_one()
    home, away = _ensure_batch_teams(session)

    matches: list[Match] = []
    for index in range(count):
        kickoff_at = BATCH_BASE_KICKOFF + timedelta(days=index)
        decision_at = kickoff_at - timedelta(minutes=30)
        match = Match(
            competition_id=competition.id,
            season="2026/27",
            kickoff_at=kickoff_at,
            first_seen_at=decision_at - timedelta(hours=1),
            home_team_id=home.id,
            away_team_id=away.id,
            status=MatchStatus.SCHEDULED,
            source_match_ids={"batch": str(index)},
            coverage_flags=[],
        )
        session.add(match)
        session.flush()
        snapshot = OddsSnapshot(
            match_id=match.id,
            market=MarketType.HAD,
            snapshot_kind=SnapshotKind.T30M,
            snapshot_at=decision_at,
            query_version="batch-v1",
            payload_hash=f"batch-{index}-{uuid.uuid4().hex}",
            run_id=f"batch-{index}",
        )
        session.add(snapshot)
        session.flush()
        _add_market_lines(session, snapshot)
        _ = decide_match(session, match, snapshot, now=decision_at)
        matches.append(match)

    bets = list(
        session.execute(
            select(PaperBet).where(PaperBet.status == BetStatus.PENDING)
        ).scalars()
    )
    bets_by_match: dict[uuid.UUID, list[PaperBet]] = {}
    for bet in bets:
        bets_by_match.setdefault(bet.match_id, []).append(bet)

    ledger = LedgerService(session, initial_bankroll=initial_bankroll)
    settled = 0
    for index, match in enumerate(matches):
        home_goals, away_goals = _settlement_goals(index)
        for bet in bets_by_match.get(match.id, []):
            probability = session.execute(
                select(ModelPrediction.probability)
                .where(
                    ModelPrediction.match_id == bet.match_id,
                    ModelPrediction.market == bet.market,
                    ModelPrediction.line_key == bet.line_key,
                    ModelPrediction.outcome == bet.selection,
                )
                .order_by(ModelPrediction.decision_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            _ = ledger.settle_paper_bet(
                bet.id,
                home_goals_90=home_goals,
                away_goals_90=away_goals,
                refunded_markets=frozenset(),
                payout_confirmed=True,
                hk_result_ref=f"batch-{index}",
                closing_odds=bet.odds_decimal,
                final_probability=(
                    Decimal(str(probability)) if probability is not None else None
                ),
                settled_at=BATCH_BASE_KICKOFF + timedelta(days=index, hours=3),
            )
            settled += 1

    summary = ledger.summary()
    predictions = session.query(ModelPrediction).count()
    return BatchDryRunResult(
        matches=len(matches),
        bets=len(bets),
        predictions=predictions,
        settled=settled,
        bankroll=summary.bankroll,
        roi=summary.roi,
    )
