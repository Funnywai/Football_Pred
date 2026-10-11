import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.data.leagues import seed_leagues
from app.db.models import League, Match, OddsSnapshot, Season, Team
from app.db.session import Database
from app.providers.football_data.provider import FootballDataProvider, HistoricalMatchRecord
from app.services.alias import TeamMatcher
from app.services.fixtures import season_bounds
from app.services.runs import track_run

DEFAULT_DIVISIONS = ["E0", "SP1", "I1", "D1", "F1"]


async def backfill(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FootballDataProvider,
    year_from: int,
    year_to: int,
    divisions: list[str],
) -> int:
    total = 0
    for year in range(year_from, year_to + 1):
        records = await provider.fetch_historical(year, divisions=divisions)
        total += await track_run(
            session_factory,
            "backfill_history",
            lambda session, recs=records: _upsert_history(session, recs),
        )
    return total


async def _upsert_history(session: AsyncSession, records: list[HistoricalMatchRecord]) -> int:
    count = 0
    for record in records:
        league = (
            await session.execute(select(League).where(League.code == record.league_code))
        ).scalar_one_or_none()
        if league is None:
            continue
        season = (
            await session.execute(
                select(Season).where(
                    Season.league_id == league.id, Season.label == record.season_label
                )
            )
        ).scalar_one_or_none()
        if season is None:
            start, end = season_bounds(record.season_label)
            season = Season(
                league_id=league.id,
                label=record.season_label,
                start_date=start,
                end_date=end,
            )
            session.add(season)
            await session.flush()
        home = await _resolve_team(session, record.home_team_name)
        away = await _resolve_team(session, record.away_team_name)
        match = (
            await session.execute(
                select(Match).where(
                    Match.season_id == season.id,
                    Match.home_team_id == home.id,
                    Match.away_team_id == away.id,
                    Match.kickoff_time == record.kickoff_time,
                )
            )
        ).scalar_one_or_none()
        if match is None:
            match = Match(
                season_id=season.id,
                league_id=league.id,
                hkjc_match_id=None,
                kickoff_time=record.kickoff_time,
                status="finished",
                home_team_id=home.id,
                away_team_id=away.id,
            )
            session.add(match)
            await session.flush()
        existing = (
            await session.execute(
                select(OddsSnapshot).where(
                    OddsSnapshot.match_id == match.id,
                    OddsSnapshot.odds_type == "HAD",
                    OddsSnapshot.inplay.is_(False),
                    OddsSnapshot.snapshot_bucket == record.kickoff_time,
                )
            )
        ).scalar_one_or_none()
        payload = {"odds": record.odds}
        if existing is None:
            session.add(
                OddsSnapshot(
                    match_id=match.id,
                    captured_at=record.kickoff_time,
                    snapshot_bucket=record.kickoff_time,
                    source="football_data",
                    inplay=False,
                    odds_type="HAD",
                    payload=payload,
                )
            )
        else:
            existing.payload = payload
        count += 1
    return count


async def _resolve_team(session: AsyncSession, name: str) -> Team:
    teams = (await session.execute(select(Team))).scalars().all()
    matched = TeamMatcher(teams).match(name)
    if matched is not None:
        return matched
    team = Team(name_en=name, name_ch=None, hkjc_team_id=None, aliases=[], external_ids={})
    session.add(team)
    await session.flush()
    return team


async def _run_backfill(args: argparse.Namespace) -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    provider = FootballDataProvider(settings.football_data_base, divisions=args.divisions)
    try:
        async with db.session_factory() as session:
            await seed_leagues(session)
            await session.commit()
        total = await backfill(
            db.session_factory, provider, args.year_from, args.year_to, args.divisions
        )
        print(f"backfill complete: {total} matches upserted")
    finally:
        await provider.aclose()
        await db.dispose()


async def _run_seed_leagues() -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        async with db.session_factory() as session:
            inserted = await seed_leagues(session)
            await session.commit()
        print(f"seed-leagues complete: {inserted} leagues inserted")
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backfill_parser = subparsers.add_parser("backfill", help="Bulk-load football-data.co.uk history")
    backfill_parser.add_argument("--from", dest="year_from", type=int, required=True)
    backfill_parser.add_argument("--to", dest="year_to", type=int, default=datetime.now(UTC).year)
    backfill_parser.add_argument(
        "--divisions",
        type=lambda value: [part.strip() for part in value.split(",") if part.strip()],
        default=DEFAULT_DIVISIONS,
    )

    subparsers.add_parser("seed-leagues", help="Insert whitelisted leagues")

    args = parser.parse_args(argv)
    if args.command == "backfill":
        asyncio.run(_run_backfill(args))
    elif args.command == "seed-leagues":
        asyncio.run(_run_seed_leagues())


if __name__ == "__main__":
    main()
