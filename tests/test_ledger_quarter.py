from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.models import LedgerBet, ModelVersion
from app.services.ledger import settle_bets
from tests.ml_helpers import make_db, seed_context, seed_finished_match, seed_team

KICKOFF = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
STAKE = 100.0
ODDS = 1.8


async def _seed_model_version(session) -> None:
    """A LedgerBet references a model version; seed one so FK enforcement (if enabled) holds."""
    session.add(
        ModelVersion(
            id=1,
            target="handicap",
            algorithm="lightgbm",
            params={},
            metrics={},
            artifact_path="artifacts/ml/test.joblib",
        )
    )
    await session.flush()


@pytest.mark.parametrize(
    ("line", "outcome", "home", "away", "expected_status", "expected_payout"),
    [
        (-0.75, "H", 2, 1, "half_won", STAKE * (ODDS + 1.0) / 2.0),
        (-0.75, "H", 3, 1, "won", STAKE * ODDS),
        (-0.75, "H", 1, 1, "lost", 0.0),
        (-0.75, "A", 2, 1, "half_lost", STAKE / 2.0),
        (-0.75, "A", 1, 1, "won", STAKE * ODDS),
        (-0.75, "A", 3, 1, "lost", 0.0),
        (0.25, "H", 0, 0, "half_won", STAKE * (ODDS + 1.0) / 2.0),
        (0.25, "H", 1, 0, "won", STAKE * ODDS),
        (-1.0, "H", 2, 1, "push", STAKE),
        (-1.0, "H", 3, 1, "won", STAKE * ODDS),
    ],
)
async def test_settle_quarter_and_whole_lines(
    tmp_path, line, outcome, home, away, expected_status, expected_payout
):
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home_team = await seed_team(session, "Home FC")
            away_team = await seed_team(session, "Away FC")
            match = await seed_finished_match(
                session,
                league,
                season,
                home_team,
                away_team,
                match_id_label="M-Q1",
                kickoff=KICKOFF,
                home_score=home,
                away_score=away,
            )
            session.add(
                LedgerBet(
                    match_id=match.id,
                    target="handicap",
                    outcome=outcome,
                    model_version_id=1,
                    line=line,
                    odds=ODDS,
                    stake=STAKE,
                    bankroll_at_place=1000.0,
                    edge=0.03,
                    kelly_multiplier=0.5,
                )
            )
            await _seed_model_version(session)
            await session.commit()
        async with db.session_factory() as session:
            assert await settle_bets(session) == 1
            await session.commit()
        async with db.session_factory() as session:
            bet = (await session.execute(select(LedgerBet))).scalar_one()
            assert bet.status == expected_status
            assert bet.payout == pytest.approx(expected_payout)
            assert bet.profit == pytest.approx(expected_payout - STAKE)
    finally:
        await db.dispose()


async def test_settle_is_idempotent_for_quarter_lines(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home_team = await seed_team(session, "Home FC")
            away_team = await seed_team(session, "Away FC")
            match = await seed_finished_match(
                session,
                league,
                season,
                home_team,
                away_team,
                match_id_label="M-Q2",
                kickoff=KICKOFF,
                home_score=2,
                away_score=1,
            )
            session.add(
                LedgerBet(
                    match_id=match.id,
                    target="handicap",
                    outcome="H",
                    model_version_id=1,
                    line=-0.75,
                    odds=ODDS,
                    stake=STAKE,
                    bankroll_at_place=1000.0,
                    edge=0.03,
                    kelly_multiplier=0.5,
                )
            )
            await _seed_model_version(session)
            await session.commit()
        async with db.session_factory() as session:
            assert await settle_bets(session) == 1
            await session.commit()
        async with db.session_factory() as session:
            assert await settle_bets(session) == 0
            await session.commit()
    finally:
        await db.dispose()
