from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import OddsSnapshot
from app.ml.dataset import load_market_priors
from app.ml.features import MatchRow
from app.services.odds import compact_odds_snapshots
from tests.ml_helpers import make_db, seed_context, seed_finished_match, seed_team

KICKOFF = datetime(2026, 10, 10, 15, 0, tzinfo=UTC)
LEAD_HOURS = 48


def _had(home_odds: float) -> dict:
    return {
        "lines": [
            {
                "combinations": [
                    {"str": "H", "currentOdds": home_odds},
                    {"str": "D", "currentOdds": 3.4},
                    {"str": "A", "currentOdds": 4.0},
                ]
            }
        ]
    }


def _hdc() -> dict:
    return {
        "lines": [
            {
                "main": True,
                "condition": "-1",
                "combinations": [
                    {"str": "H", "currentOdds": 1.9},
                    {"str": "A", "currentOdds": 2.1},
                ],
            }
        ]
    }


def _snapshot(match_id: int, odds_type: str, hours: float, payload: dict) -> OddsSnapshot:
    moment = KICKOFF + timedelta(hours=hours)
    return OddsSnapshot(
        match_id=match_id,
        captured_at=moment,
        snapshot_bucket=moment,
        source="hkjc",
        inplay=False,
        odds_type=odds_type,
        payload=payload,
    )


def _row(match_id: int, home_id: int, away_id: int) -> MatchRow:
    return MatchRow(
        match_id=match_id,
        kickoff_time=KICKOFF,
        home_team_id=home_id,
        away_team_id=away_id,
        league_code="EPL",
        season_label="2026/27",
    )


async def _seeded_match(db, *, had_offsets: tuple[float, ...], with_hdc: bool = True):
    async with db.session_factory() as session:
        league, season = await seed_context(session)
        home = await seed_team(session, "Home FC")
        away = await seed_team(session, "Away FC")
        match = await seed_finished_match(
            session,
            league,
            season,
            home,
            away,
            match_id_label="M-1",
            kickoff=KICKOFF,
            home_score=2,
            away_score=1,
            had_payload=_had(2.5),
            hdc_payload=_hdc() if with_hdc else None,
            snapshot_at_offset_hours=int(had_offsets[0]),
        )
        for offset in had_offsets[1:]:
            session.add(_snapshot(match.id, "HAD", offset, _had(2.0 + offset / 100.0)))
        await session.commit()
        return match.id, home.id, away.id


async def test_compaction_preserves_prior_and_close_lookups(tmp_path):
    db = await make_db(tmp_path)
    offsets = (-72, -60, -50, -48, -24, -1)
    try:
        match_id, home_id, away_id = await _seeded_match(db, had_offsets=offsets)
        row = _row(match_id, home_id, away_id)
        async with db.session_factory() as session:
            before_prior = await load_market_priors(session, [row], LEAD_HOURS)
            before_close = await load_market_priors(session, [row], 0)

        deleted = await compact_odds_snapshots(
            db.session_factory, LEAD_HOURS, now=KICKOFF + timedelta(hours=12)
        )
        assert deleted == 3

        async with db.session_factory() as session:
            after_prior = await load_market_priors(session, [row], LEAD_HOURS)
            after_close = await load_market_priors(session, [row], 0)
            kept = (await session.execute(select(OddsSnapshot))).scalars().all()

        assert after_prior == before_prior
        assert after_close == before_close
        assert sorted(s.captured_at for s in kept if s.odds_type == "HAD") == [
            KICKOFF + timedelta(hours=-72),
            KICKOFF + timedelta(hours=-50),
            KICKOFF + timedelta(hours=-1),
        ]
        assert sorted(s.odds_type for s in kept) == ["HAD", "HAD", "HAD", "HDC"]
    finally:
        await db.dispose()


async def test_compaction_is_idempotent(tmp_path):
    db = await make_db(tmp_path)
    offsets = (-72, -50, -24, -1)
    try:
        match_id, home_id, away_id = await _seeded_match(db, had_offsets=offsets)
        row = _row(match_id, home_id, away_id)
        now = KICKOFF + timedelta(hours=12)
        first = await compact_odds_snapshots(db.session_factory, LEAD_HOURS, now=now)
        second = await compact_odds_snapshots(db.session_factory, LEAD_HOURS, now=now)
        assert first == 1
        assert second == 0
        async with db.session_factory() as session:
            assert await load_market_priors(session, [row], 0) == await load_market_priors(
                session, [row], 0
            )
    finally:
        await db.dispose()


async def test_compaction_leaves_running_matches_alone(tmp_path):
    db = await make_db(tmp_path)
    offsets = (-72, -50, -24, -1)
    try:
        _match_id, _, _ = await _seeded_match(db, had_offsets=offsets)
        deleted = await compact_odds_snapshots(
            db.session_factory, LEAD_HOURS, now=KICKOFF - timedelta(hours=1)
        )
        assert deleted == 0
        async with db.session_factory() as session:
            assert len((await session.execute(select(OddsSnapshot))).scalars().all()) == 5
    finally:
        await db.dispose()
