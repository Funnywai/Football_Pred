"""Shared helpers for ML tests: a tiny seeded league/teams/matches/results/odds DB."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.models import League, Match, OddsSnapshot, Result, Season, Team
from app.db.session import Database


async def make_db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'ml.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return db


async def seed_context(session: AsyncSession, code: str = "EPL") -> tuple[League, Season]:
    league = League(code=code, name_en=code, name_ch=None, country=None, active=True)
    session.add(league)
    await session.flush()
    season = Season(
        league_id=league.id,
        label="2026/27",
        start_date=date(2026, 7, 1),
        end_date=date(2027, 6, 30),
    )
    session.add(season)
    await session.flush()
    return league, season


async def seed_team(session: AsyncSession, name: str) -> Team:
    team = Team(name_en=name, name_ch=None, hkjc_team_id=None, aliases=[], external_ids={})
    session.add(team)
    await session.flush()
    return team


async def seed_finished_match(
    session: AsyncSession,
    league: League,
    season: Season,
    home: Team,
    away: Team,
    *,
    match_id_label: str,
    kickoff: datetime,
    home_score: int,
    away_score: int,
    had_payload: dict | None = None,
    hdc_payload: dict | None = None,
    snapshot_source: str = "hkjc",
    snapshot_at_offset_hours: int = -49,
) -> Match:
    """Seed a finished match with result and optional odds snapshots.

    ``snapshot_at_offset_hours=-49`` mimics the serving-time lead
    (``ML_PRIOR_LEAD_HOURS=48`` + 1h margin) so priors survive the lead filter.
    """
    match = Match(
        season_id=season.id,
        league_id=league.id,
        hkjc_match_id=match_id_label,
        kickoff_time=kickoff,
        status="finished",
        home_team_id=home.id,
        away_team_id=away.id,
    )
    session.add(match)
    await session.flush()
    session.add(
        Result(
            match_id=match.id,
            home_score=home_score,
            away_score=away_score,
            ttl_corner=None,
            source="hkjc",
            confirmed=True,
            payout_confirmed=True,
        )
    )
    if had_payload is not None:
        session.add(
            OddsSnapshot(
                match_id=match.id,
                captured_at=kickoff.replace() + __import__("datetime").timedelta(hours=snapshot_at_offset_hours),
                snapshot_bucket=kickoff,
                source=snapshot_source,
                inplay=False,
                odds_type="HAD",
                payload=had_payload,
            )
        )
    if hdc_payload is not None:
        session.add(
            OddsSnapshot(
                match_id=match.id,
                captured_at=kickoff.replace() + __import__("datetime").timedelta(hours=snapshot_at_offset_hours),
                snapshot_bucket=kickoff,
                source=snapshot_source,
                inplay=False,
                odds_type="HDC",
                payload=hdc_payload,
            )
        )
    await session.flush()
    return match
