from datetime import UTC, date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.schemas import MatchOut, OddsOut, ResultOut, TeamOut
from app.db.models import League, Match, OddsSnapshot, Result, Team

router = APIRouter()


async def get_session(request: Request):
    async with request.app.state.db.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/matches", response_model=list[MatchOut])
async def list_matches(
    session: SessionDep,
    date_from: date | None = None,
    date_to: date | None = None,
    league: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[MatchOut]:
    home = aliased(Team)
    away = aliased(Team)
    stmt = (
        select(Match, League, home, away)
        .join(League, League.id == Match.league_id)
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .order_by(Match.kickoff_time)
        .limit(limit)
        .offset(offset)
    )
    if date_from is not None:
        stmt = stmt.where(Match.kickoff_time >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to is not None:
        stmt = stmt.where(Match.kickoff_time <= datetime.combine(date_to, time.max, tzinfo=UTC))
    if league is not None:
        stmt = stmt.where(League.code == league)
    if status is not None:
        stmt = stmt.where(Match.status == status)
    rows = (await session.execute(stmt)).all()
    return [
        MatchOut(
            id=match.id,
            league_code=lg.code,
            league_name=lg.name_en,
            kickoff_time=match.kickoff_time,
            status=match.status,
            home_team=TeamOut.model_validate(home_team),
            away_team=TeamOut.model_validate(away_team),
            venue=match.venue,
            round=match.round,
            hkjc_match_id=match.hkjc_match_id,
        )
        for match, lg, home_team, away_team in rows
    ]


@router.get("/matches/{match_id}/odds", response_model=list[OddsOut])
async def match_odds(
    match_id: int,
    session: SessionDep,
    odds_type: str | None = None,
    inplay: bool | None = None,
    history: bool = False,
) -> list[OddsOut]:
    match = await session.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="match not found")
    stmt = select(OddsSnapshot).where(OddsSnapshot.match_id == match_id)
    if odds_type is not None:
        stmt = stmt.where(OddsSnapshot.odds_type == odds_type)
    if inplay is not None:
        stmt = stmt.where(OddsSnapshot.inplay == inplay)
    stmt = stmt.order_by(OddsSnapshot.captured_at.desc())
    snapshots = (await session.execute(stmt)).scalars().all()
    if history:
        return [OddsOut.model_validate(snapshot) for snapshot in snapshots]
    latest: dict[tuple[str, bool], OddsSnapshot] = {}
    for snapshot in snapshots:
        latest.setdefault((snapshot.odds_type, snapshot.inplay), snapshot)
    return [OddsOut.model_validate(snapshot) for snapshot in latest.values()]


@router.get("/results", response_model=list[ResultOut])
async def list_results(
    session: SessionDep,
    date_from: date | None = None,
    date_to: date | None = None,
    league: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ResultOut]:
    home = aliased(Team)
    away = aliased(Team)
    stmt = (
        select(Result, Match, League, home, away)
        .join(Match, Match.id == Result.match_id)
        .join(League, League.id == Match.league_id)
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .order_by(Match.kickoff_time.desc())
        .limit(limit)
        .offset(offset)
    )
    if date_from is not None:
        stmt = stmt.where(Match.kickoff_time >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to is not None:
        stmt = stmt.where(Match.kickoff_time <= datetime.combine(date_to, time.max, tzinfo=UTC))
    if league is not None:
        stmt = stmt.where(League.code == league)
    rows = (await session.execute(stmt)).all()
    return [
        ResultOut(
            match_id=result.match_id,
            home_score=result.home_score,
            away_score=result.away_score,
            ttl_corner=result.ttl_corner,
            source=result.source,
            confirmed=result.confirmed,
            payout_confirmed=result.payout_confirmed,
            confirmed_at=result.confirmed_at,
            kickoff_time=match.kickoff_time,
            league_code=lg.code,
            home_team=TeamOut.model_validate(home_team),
            away_team=TeamOut.model_validate(away_team),
        )
        for result, match, lg, home_team, away_team in rows
    ]
