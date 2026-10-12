from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import League, Match, Season, Team
from app.providers.base import FixtureRecord, Provider
from app.services.alias import TeamMatcher, normalize_team_name
from app.services.runs import track_run


def season_label_for(kickoff: datetime) -> str:
    year = kickoff.year if kickoff.month >= 7 else kickoff.year - 1
    return f"{year}/{str(year + 1)[-2:]}"


def season_bounds(label: str) -> tuple[date, date]:
    start_year = int(label.split("/")[0])
    return date(start_year, 7, 1), date(start_year + 1, 6, 30)


class FixtureSync:
    """Upserts leagues, seasons, teams, and matches from provider fixtures."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: Provider,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._settings = settings

    async def run(self, date_from: date, date_to: date) -> int:
        fixtures = await self._provider.fetch_fixtures(date_from, date_to)
        return await self.upsert(fixtures)

    async def upsert(self, fixtures: list[FixtureRecord]) -> int:
        return await track_run(
            self._session_factory,
            "sync_fixtures",
            lambda session: self._upsert_all(session, fixtures),
        )

    async def _upsert_all(self, session: AsyncSession, fixtures: list[FixtureRecord]) -> int:
        count = 0
        for fixture in fixtures:
            league = await self._resolve_league(session, fixture)
            if league is None or league.code not in self._settings.league_whitelist:
                continue
            season = await self._resolve_season(session, league, fixture.kickoff_time)
            home = await self._resolve_team(
                session,
                fixture.home_team_name_en,
                fixture.home_team_name_ch,
                fixture.home_team_hkjc_id,
            )
            away = await self._resolve_team(
                session,
                fixture.away_team_name_en,
                fixture.away_team_name_ch,
                fixture.away_team_hkjc_id,
            )
            await self._upsert_match(session, fixture, league, season, home, away)
            count += 1
        return count

    async def _resolve_league(self, session: AsyncSession, fixture: FixtureRecord) -> League | None:
        if fixture.hkjc_tourn_id:
            league = (
                await session.execute(
                    select(League).where(League.hkjc_tourn_id == fixture.hkjc_tourn_id)
                )
            ).scalar_one_or_none()
            if league is not None:
                return league
        target = normalize_team_name(fixture.league_name)
        leagues = (await session.execute(select(League))).scalars().all()
        for league in leagues:
            names = [league.name_en, league.name_ch]
            if any(name and normalize_team_name(name) == target for name in names):
                if fixture.hkjc_tourn_id and league.hkjc_tourn_id is None:
                    league.hkjc_tourn_id = fixture.hkjc_tourn_id
                return league
        return None

    async def _resolve_season(
        self, session: AsyncSession, league: League, kickoff: datetime
    ) -> Season:
        label = season_label_for(kickoff)
        season = (
            await session.execute(
                select(Season).where(Season.league_id == league.id, Season.label == label)
            )
        ).scalar_one_or_none()
        if season is None:
            start, end = season_bounds(label)
            season = Season(league_id=league.id, label=label, start_date=start, end_date=end)
            session.add(season)
            await session.flush()
        return season

    async def _resolve_team(
        self,
        session: AsyncSession,
        name_en: str,
        name_ch: str | None,
        hkjc_team_id: str | None,
    ) -> Team:
        if hkjc_team_id:
            team = (
                await session.execute(select(Team).where(Team.hkjc_team_id == hkjc_team_id))
            ).scalar_one_or_none()
            if team is not None:
                return team
        teams = (await session.execute(select(Team))).scalars().all()
        matcher = TeamMatcher(teams)
        for candidate in (name_en, name_ch):
            if not candidate:
                continue
            matched = matcher.match(candidate)
            if matched is not None:
                if hkjc_team_id and matched.hkjc_team_id is None:
                    matched.hkjc_team_id = hkjc_team_id
                return matched
        team = Team(
            name_en=name_en,
            name_ch=name_ch,
            hkjc_team_id=hkjc_team_id,
            aliases=[],
            external_ids={},
        )
        session.add(team)
        await session.flush()
        return team

    async def _upsert_match(
        self,
        session: AsyncSession,
        fixture: FixtureRecord,
        league: League,
        season: Season,
        home: Team,
        away: Team,
    ) -> None:
        match: Match | None = None
        if fixture.hkjc_match_id:
            match = (
                await session.execute(
                    select(Match).where(Match.hkjc_match_id == fixture.hkjc_match_id)
                )
            ).scalar_one_or_none()
        if match is None:
            session.add(
                Match(
                    season_id=season.id,
                    league_id=league.id,
                    hkjc_match_id=fixture.hkjc_match_id,
                    kickoff_time=fixture.kickoff_time,
                    status=fixture.status,
                    home_team_id=home.id,
                    away_team_id=away.id,
                    venue=fixture.venue,
                    round=fixture.round,
                )
            )
            await session.flush()
            return
        match.season_id = season.id
        match.league_id = league.id
        match.kickoff_time = fixture.kickoff_time
        match.status = fixture.status
        match.home_team_id = home.id
        match.away_team_id = away.id
        match.venue = fixture.venue
        match.round = fixture.round
