"""Paper ledger read-API tests: /bets, /bets/summary, /bets/equity-curve."""

from datetime import UTC, datetime

import httpx
import pytest
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team

from app.api.main import create_app
from app.config import Settings
from app.db.models import LedgerBet, ModelVersion
from app.services.ledger import settle_bets


async def _client(db):
    app = create_app(Settings(_env_file=None), db=db)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _seed_pending_bet(tmp_path):
    """Seed one pending HKD-15 bet (outcome H) on a finished 2:1 match + champion."""
    db = await make_db(tmp_path)
    async with db.session_factory() as session:
        league, season = await seed_context(session)
        home = await seed_team(session, "Home")
        away = await seed_team(session, "Away")
        match = await seed_finished_match(
            session, league, season, home, away,
            match_id_label="M1", kickoff=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
            home_score=2, away_score=1,
        )
        version = ModelVersion(
            target="1x2", algorithm="lightgbm", params={}, metrics={},
            artifact_path="/tmp/m1.joblib", status="champion",
        )
        session.add(version)
        await session.flush()
        session.add(
            LedgerBet(
                match_id=match.id, target="1x2", outcome="H",
                model_version_id=version.id, odds=2.1, stake=15.0,
                bankroll_at_place=1000.0, kelly_multiplier=0.5,
            )
        )
        await session.commit()
    return db, match.id


async def test_bets_endpoints_empty(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with await _client(db) as client:
            response = await client.get("/bets")
            assert response.status_code == 200
            assert response.json() == []
            summary_response = await client.get("/bets/summary")
            assert summary_response.status_code == 200
            assert summary_response.json() == {
                "initial_bankroll": 1000.0, "bankroll": 1000.0, "n_bets": 0,
                "n_settled": 0, "n_open": 0, "stakes_total": 0.0,
                "open_stakes": 0.0, "realized_profit": 0.0, "roi": 0.0, "yield_pct": 0.0,
            }
            curve_response = await client.get("/bets/equity-curve")
            assert curve_response.status_code == 200
            points = curve_response.json()
            assert len(points) == 2
            assert points[0]["bankroll"] == 1000.0
            assert points[-1]["bankroll"] == 1000.0
    finally:
        await db.dispose()


async def test_bets_listing_and_summary_math(tmp_path) -> None:
    db, _match_id = await _seed_pending_bet(tmp_path)
    try:
        async with db.session_factory() as session:
            assert await settle_bets(session) == 1  # 2:1 vs outcome H → won
            await session.commit()
        async with await _client(db) as client:
            bets = (await client.get("/bets")).json()
            assert len(bets) == 1
            bet = bets[0]
            assert bet["status"] == "won"
            assert bet["stake"] == 15.0
            assert bet["payout"] == pytest.approx(31.5)
            assert bet["profit"] == pytest.approx(16.5)
            assert bet["odds"] == pytest.approx(2.1)
            assert bet["home_team"] == "Home"
            assert bet["away_team"] == "Away"
            assert bet["kelly_multiplier"] == 0.5
            assert bet["bankroll_at_place"] == 1000.0

            summary = (await client.get("/bets/summary")).json()
            assert summary["initial_bankroll"] == 1000.0
            assert summary["n_bets"] == 1 and summary["n_settled"] == 1 and summary["n_open"] == 0
            assert summary["stakes_total"] == pytest.approx(15.0)
            assert summary["open_stakes"] == 0.0
            assert summary["realized_profit"] == pytest.approx(16.5)
            assert summary["bankroll"] == pytest.approx(1016.5)
            assert summary["roi"] == pytest.approx(16.5 / 15.0)
            assert summary["yield_pct"] == pytest.approx(16.5 / 15.0)

            curve = (await client.get("/bets/equity-curve")).json()
            assert len(curve) == 3  # initial + one settlement + current
            assert curve[0]["bankroll"] == 1000.0
            assert curve[-1]["bankroll"] == pytest.approx(1016.5)

            status_filtered = (
                await client.get("/bets", params={"status": "lost"})
            ).json()
            assert status_filtered == []
    finally:
        await db.dispose()
