from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.adapters.football_data_org import FootballDataMatch
from packages.adapters.hkjc import HkjcOddsPayload
from packages.db.models import (
    Competition,
    MarketLine,
    Match,
    OddsSnapshot,
)
from packages.domain.enums import MarketType, MatchStatus, SnapshotKind
from packages.domain.errors import DomainError
from packages.ingest.aliases import resolve_team_id
from packages.shared.time import ensure_utc, utc_now

COMPETITION_SEEDS = (
    ("EPL", "Premier League", "England", False, "EPL", "PL"),
    ("LALIGA", "La Liga", "Spain", False, "La_liga", "PD"),
    ("BUNDESLIGA", "Bundesliga", "Germany", False, "Bundesliga", "BL1"),
    ("SERIEA", "Serie A", "Italy", False, "Serie_A", "SA"),
    ("LIGUE1", "Ligue 1", "France", False, "Ligue_1", "FL1"),
    ("UCL", "UEFA Champions League", "Europe", True, None, "CL"),
)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def seed_competitions(session: Session) -> None:
    existing = {code for (code,) in session.execute(select(Competition.code)).all()}
    for code, name, country, is_cup, understat_slug, football_data_code in COMPETITION_SEEDS:
        if code in existing:
            continue
        session.add(
            Competition(
                code=code,
                name=name,
                country=country,
                is_cup=is_cup,
                understat_slug=understat_slug,
                football_data_code=football_data_code,
            )
        )
    session.flush()


def get_competition(session: Session, code: str) -> Competition:
    competition = session.execute(
        select(Competition).where(Competition.code == code)
    ).scalar_one_or_none()
    if competition is None:
        raise DomainError(f"unknown competition {code}")
    return competition


def season_label(season_start_year: int) -> str:
    return f"{season_start_year}/{str(season_start_year + 1)[2:]}"


@dataclass(frozen=True)
class NormalizedFixture:
    competition_id: uuid.UUID
    season: str
    kickoff_at: datetime
    home_team_id: uuid.UUID
    away_team_id: uuid.UUID
    status: MatchStatus
    matchday: int | None
    home_goals_90: int | None
    away_goals_90: int | None
    home_goals_final: int | None
    away_goals_final: int | None
    source_match_ids: dict[str, str]


def normalize_fixture(
    session: Session,
    dto: FootballDataMatch,
    competition_id: uuid.UUID,
) -> NormalizedFixture:
    return NormalizedFixture(
        competition_id=competition_id,
        season=season_label(dto.season_start_year),
        kickoff_at=ensure_utc(dto.kickoff_at),
        home_team_id=resolve_team_id(session, dto.home_team_name),
        away_team_id=resolve_team_id(session, dto.away_team_name),
        status=dto.status,
        matchday=dto.matchday,
        home_goals_90=dto.home_goals_90,
        away_goals_90=dto.away_goals_90,
        home_goals_final=dto.home_goals_final,
        away_goals_final=dto.away_goals_final,
        source_match_ids={"football-data.org": str(dto.source_match_id)},
    )


def upsert_match(session: Session, fixture: NormalizedFixture) -> Match:
    candidates = list(
        session.execute(
            select(Match).where(
                Match.competition_id == fixture.competition_id,
                Match.season == fixture.season,
                Match.home_team_id == fixture.home_team_id,
                Match.away_team_id == fixture.away_team_id,
            )
        ).scalars()
    )
    existing = (
        min(
            candidates,
            key=lambda match: abs(
                ensure_utc(match.kickoff_at) - fixture.kickoff_at
            ),
        )
        if candidates
        else None
    )
    if existing is None:
        existing = Match(
            competition_id=fixture.competition_id,
            season=fixture.season,
            kickoff_at=fixture.kickoff_at,
            first_seen_at=utc_now(),
            home_team_id=fixture.home_team_id,
            away_team_id=fixture.away_team_id,
            status=fixture.status,
            matchday=fixture.matchday,
            home_goals_90=fixture.home_goals_90,
            away_goals_90=fixture.away_goals_90,
            home_goals_final=fixture.home_goals_final,
            away_goals_final=fixture.away_goals_final,
            source_match_ids=dict(fixture.source_match_ids),
            coverage_flags=[],
        )
        session.add(existing)
        session.flush()
        return existing
    existing.kickoff_at = fixture.kickoff_at
    existing.status = fixture.status
    existing.matchday = fixture.matchday
    existing.home_goals_90 = fixture.home_goals_90
    existing.away_goals_90 = fixture.away_goals_90
    existing.home_goals_final = fixture.home_goals_final
    existing.away_goals_final = fixture.away_goals_final
    existing.source_match_ids = {
        **(existing.source_match_ids or {}),
        **fixture.source_match_ids,
    }
    session.flush()
    return existing


def normalize_hkjc_snapshot(
    session: Session,
    *,
    match_id: uuid.UUID,
    market: MarketType,
    payload: HkjcOddsPayload,
    snapshot_kind: SnapshotKind,
    snapshot_at: datetime,
    query_version: str,
    raw_payload_id: uuid.UUID | None,
    payload_hash: str,
    run_id: str,
) -> tuple[OddsSnapshot, list[MarketLine]]:
    """Persist one HKJC odds snapshot and its lines idempotently.

    ``available_at`` is deliberately not inferred from ``snapshot_at`` or
    ``fetched_at``: retrospective availability requires explicit primary
    evidence and must never be backfilled from a later observation.
    """
    _require_text(query_version, "query_version")
    _require_text(payload_hash, "payload_hash")
    _require_text(run_id, "run_id")
    snapshot_at = ensure_utc(snapshot_at)
    existing = session.execute(
        select(OddsSnapshot).where(
            OddsSnapshot.match_id == match_id,
            OddsSnapshot.market == market,
            OddsSnapshot.snapshot_kind == snapshot_kind,
            OddsSnapshot.snapshot_at == snapshot_at,
        )
    ).scalar_one_or_none()
    if existing is not None:
        lines = list(
            session.execute(
                select(MarketLine)
                .where(MarketLine.snapshot_id == existing.id)
                .order_by(MarketLine.line_index, MarketLine.side)
            ).scalars()
        )
        return existing, lines
    snapshot = OddsSnapshot(
        match_id=match_id,
        market=market,
        snapshot_kind=snapshot_kind,
        snapshot_at=snapshot_at,
        source_update_at=payload.source_update_at,
        query_version=query_version,
        payload_hash=payload_hash,
        raw_payload_id=raw_payload_id,
        run_id=run_id,
    )
    session.add(snapshot)
    session.flush()
    lines: list[MarketLine] = []
    for dto in payload.lines:
        line = MarketLine(
            snapshot_id=snapshot.id,
            odds_type=dto.odds_type,
            condition_raw=dto.condition_raw,
            line_index=dto.line_index,
            side=dto.side,
            odds_decimal=dto.odds_decimal,
            pool_status=dto.pool_status,
            line_status=dto.line_status,
            is_main=dto.is_main,
            offer_early_settlement=dto.offer_early_settlement,
            source_update_at=dto.source_update_at,
        )
        session.add(line)
        lines.append(line)
    session.flush()
    return snapshot, lines
