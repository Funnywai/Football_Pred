"""B analyst: fetch lineups-only facts and persist one auditable brief per match."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.agents.striker import (
    LineupFetch,
    LineupSide,
    StrikerError,
    StrikerLineupsClient,
    classify_lineups,
)
from app.config import Settings
from app.db.models import AnalystBrief, League, Match, Team

BRIEF_SOURCE = "striker"
STANDARD_STARTERS = 11


class BriefError(RuntimeError):
    """The brief cannot be built because its match does not exist."""


class LineupSource(Protocol):
    async def fetch_lineups(
        self,
        *,
        league_code: str,
        kickoff: datetime,
        home_name: str,
        away_name: str,
    ) -> LineupFetch: ...


def _add_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _trust_score(home: LineupSide | None, away: LineupSide | None) -> float:
    if home is None or away is None or not home.starters or not away.starters:
        return 0.0
    if (
        len(home.starters) == STANDARD_STARTERS
        and len(away.starters) == STANDARD_STARTERS
    ):
        return 1.0
    return round(0.5 * min(len(home.starters), len(away.starters)) / STANDARD_STARTERS, 4)


def _gaps(fetch: LineupFetch, api_error: str | None) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    uncertainties: list[str] = []
    if api_error is not None:
        _add_once(missing, "striker_api_error")
        _add_once(uncertainties, f"StrikerAPI request failed: {api_error}")
        return missing, uncertainties
    if fetch.game_id is None:
        _add_once(missing, "striker_game")
        _add_once(uncertainties, "team mapping failure")
    else:
        derived_missing, derived_uncertainties = classify_lineups(fetch.home, fetch.away)
        for value in derived_missing:
            _add_once(missing, value)
        for value in derived_uncertainties:
            _add_once(uncertainties, value)
    for value in fetch.missing:
        _add_once(missing, value)
    for value in fetch.uncertainties:
        _add_once(uncertainties, value)
    return missing, uncertainties


async def _match_context(
    session: AsyncSession, match_id: int
) -> tuple[Match, str, str, str]:
    home = aliased(Team)
    away = aliased(Team)
    row = (
        await session.execute(
            select(Match, League.code, home.name_en, away.name_en)
            .join(League, League.id == Match.league_id)
            .join(home, home.id == Match.home_team_id)
            .join(away, away.id == Match.away_team_id)
            .where(Match.id == match_id)
        )
    ).first()
    if row is None:
        raise BriefError(f"match {match_id} not found")
    match, league_code, home_name, away_name = row
    return match, league_code, home_name, away_name


async def build_brief(
    session: AsyncSession,
    settings: Settings,
    run_id: str,
    match_id: int,
    striker_client: LineupSource | None = None,
) -> AnalystBrief:
    existing = (
        await session.execute(
            select(AnalystBrief).where(
                AnalystBrief.run_id == run_id,
                AnalystBrief.match_id == match_id,
                AnalystBrief.source == BRIEF_SOURCE,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    match, league_code, home_name, away_name = await _match_context(session, match_id)
    owned_client = striker_client is None
    client = striker_client or StrikerLineupsClient(settings)
    api_error: str | None = None
    try:
        fetch = await client.fetch_lineups(
            league_code=league_code,
            kickoff=match.kickoff_time,
            home_name=home_name,
            away_name=away_name,
        )
    except StrikerError as exc:
        api_error = str(exc)
        fetch = LineupFetch(None, None, None)
    finally:
        if owned_client and isinstance(client, StrikerLineupsClient):
            await client.aclose()

    captured_at = datetime.now(UTC)
    missing, uncertainties = _gaps(fetch, api_error)
    home, away = fetch.home, fetch.away
    facts: dict[str, object] = {
        "lineups_available": bool(
            home is not None
            and away is not None
            and home.starters
            and away.starters
        ),
        "home_abbreviation": home.abbreviation if home is not None else None,
        "away_abbreviation": away.abbreviation if away is not None else None,
        "home_formation": home.formation if home is not None else None,
        "away_formation": away.formation if away is not None else None,
        "home_starters": len(home.starters) if home is not None else 0,
        "away_starters": len(away.starters) if away is not None else 0,
        "game_id": fetch.game_id,
        "source": BRIEF_SOURCE,
        "captured_at": captured_at.isoformat(),
        "home_team": home_name,
        "away_team": away_name,
        "striker_home": fetch.home_name,
        "striker_away": fetch.away_name,
    }
    brief = AnalystBrief(
        run_id=run_id,
        match_id=match_id,
        source=BRIEF_SOURCE,
        captured_at=captured_at,
        facts=facts,
        uncertainties=uncertainties,
        missing=missing,
        trust_score=_trust_score(home, away),
        raw_snapshot=fetch.raw,
    )
    session.add(brief)
    await session.flush()
    return brief
