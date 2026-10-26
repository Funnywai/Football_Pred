from datetime import UTC, date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.schemas import (
    BetOut,
    BetSummary,
    ClvSummaryOut,
    EquityPointOut,
    MatchOut,
    ModelOut,
    OddsOut,
    PredictionOut,
    ResultOut,
    TeamOut,
)
from app.db.models import (
    League,
    LedgerBet,
    Match,
    ModelVersion,
    OddsSnapshot,
    Prediction,
    Result,
    ShadowLedgerBet,
    Team,
)
from app.services.clv import summary as clv_summary
from app.services.ledger import equity_curve as ledger_equity_curve
from app.services.ledger import summary as ledger_summary

router = APIRouter()


async def get_session(request: Request):
    async with request.app.state.db.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]

BOOK_PATTERN = "^(production|shadow)$"


def _bet_model(book: str) -> type[LedgerBet] | type[ShadowLedgerBet]:
    return ShadowLedgerBet if book == "shadow" else LedgerBet


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


@router.get("/predictions", response_model=list[PredictionOut])
async def list_predictions(
    session: SessionDep,
    match_id: int | None = None,
    target: str | None = None,
    value_only: bool = False,
    champion_only: bool = True,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[PredictionOut]:
    home = aliased(Team)
    away = aliased(Team)
    stmt = (
        select(Prediction, Match.kickoff_time, League.code, home.name_en, away.name_en)
        .join(Match, Match.id == Prediction.match_id)
        .join(League, League.id == Match.league_id)
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .order_by(Match.kickoff_time, Prediction.target, Prediction.outcome)
        .offset(offset)
        .limit(limit)
    )
    if match_id is not None:
        stmt = stmt.where(Prediction.match_id == match_id)
    if target is not None:
        stmt = stmt.where(Prediction.target == target)
    if value_only:
        stmt = stmt.where(Prediction.recommended_fraction > 0)
    if champion_only:
        stmt = stmt.join(
            ModelVersion, ModelVersion.id == Prediction.model_version_id
        ).where(ModelVersion.status == "champion")
    rows = (await session.execute(stmt)).all()
    return [
        PredictionOut(
            id=prediction.id,
            match_id=prediction.match_id,
            target=prediction.target,
            outcome=prediction.outcome,
            model_version_id=prediction.model_version_id,
            prob=prediction.prob,
            implied_prob=prediction.implied_prob,
            edge=prediction.edge,
            fair_odds=prediction.fair_odds,
            market_odds=prediction.market_odds,
            recommended_fraction=prediction.recommended_fraction,
            kickoff_time=kickoff_time,
            league_code=league_code,
            home_team=home_name,
            away_team=away_name,
        )
        for prediction, kickoff_time, league_code, home_name, away_name in rows
    ]


@router.get("/models", response_model=list[ModelOut])
async def list_models(session: SessionDep) -> list[ModelOut]:
    stmt = select(ModelVersion).order_by(ModelVersion.target, ModelVersion.created_at.desc())
    return [
        ModelOut(
            id=version.id,
            target=version.target,
            algorithm=version.algorithm,
            status=version.status,
            metrics=version.metrics,
            artifact_path=version.artifact_path,
            created_at=version.created_at,
            promoted_at=version.promoted_at,
        )
        for version in (await session.execute(stmt)).scalars()
    ]


@router.get("/bets", response_model=list[BetOut])
async def list_bets(
    session: SessionDep,
    status: str | None = None,
    match_id: int | None = None,
    target: str | None = None,
    book: str = Query("production", pattern=BOOK_PATTERN),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[BetOut]:
    home = aliased(Team)
    away = aliased(Team)
    model = _bet_model(book)
    stmt = (
        select(model, Match.kickoff_time, League.code, home.name_en, away.name_en)
        .join(Match, Match.id == model.match_id)
        .join(League, League.id == Match.league_id)
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .order_by(model.placed_at, model.id)
        .offset(offset)
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(model.status == status)
    if match_id is not None:
        stmt = stmt.where(model.match_id == match_id)
    if target is not None:
        stmt = stmt.where(model.target == target)
    rows = (await session.execute(stmt)).all()
    return [
        BetOut(
            id=bet.id,
            match_id=bet.match_id,
            target=bet.target,
            outcome=bet.outcome,
            model_version_id=bet.model_version_id,
            line=bet.line,
            odds=bet.odds,
            stake=bet.stake,
            bankroll_at_place=bet.bankroll_at_place,
            edge=bet.edge,
            kelly_multiplier=bet.kelly_multiplier,
            status=bet.status,
            placed_at=bet.placed_at,
            settled_at=bet.settled_at,
            payout=bet.payout,
            profit=bet.profit,
            kickoff_time=kickoff_time,
            league_code=league_code,
            home_team=home_name,
            away_team=away_name,
        )
        for bet, kickoff_time, league_code, home_name, away_name in rows
    ]


@router.get("/bets/summary", response_model=BetSummary)
async def bets_summary(
    session: SessionDep,
    request: Request,
    book: str = Query("production", pattern=BOOK_PATTERN),
) -> BetSummary:
    values = await ledger_summary(
        session, request.app.state.settings, _bet_model(book)
    )
    return BetSummary(
        initial_bankroll=values.initial_bankroll,
        bankroll=values.bankroll,
        n_bets=values.n_bets,
        n_settled=values.n_settled,
        n_open=values.n_open,
        stakes_total=values.stakes_total,
        open_stakes=values.open_stakes,
        realized_profit=values.realized_profit,
        roi=values.roi,
        yield_pct=values.yield_pct,
    )


@router.get("/bets/equity-curve", response_model=list[EquityPointOut])
async def bets_equity_curve(
    session: SessionDep,
    request: Request,
    book: str = Query("production", pattern=BOOK_PATTERN),
) -> list[EquityPointOut]:
    points = await ledger_equity_curve(
        session, request.app.state.settings, _bet_model(book)
    )
    return [EquityPointOut(t=p.t, bankroll=p.bankroll) for p in points]


@router.get("/clv/summary", response_model=ClvSummaryOut)
async def clv_summary_endpoint(
    session: SessionDep,
    request: Request,
    source: str = Query("hkjc", pattern="^(hkjc|football_data|all)$"),
    model_version_id: int | None = None,
    target: str | None = None,
    value_only: bool = False,
    book: str = Query("production", pattern=BOOK_PATTERN),
) -> dict[str, object]:
    return await clv_summary(
        session,
        request.app.state.settings,
        source=source,
        model_version_id=model_version_id,
        target=target,
        value_only=value_only,
        book=book,
    )
