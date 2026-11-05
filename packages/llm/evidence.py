from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.db.models import (
    Availability,
    Competition,
    EvidenceRecord,
    Lineup,
    MarketLine,
    Match,
    OddsSnapshot,
    Team,
)
from packages.domain.enums import MarketType, MatchStatus, Side
from packages.shared.time import ensure_utc


def _iso(value: datetime | None) -> str | None:
    return None if value is None else ensure_utc(value).isoformat()


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _recent_matches(
    session: Session,
    match: Match,
    team_id: uuid.UUID,
    as_of: datetime,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(Match)
        .where(
            Match.competition_id == match.competition_id,
            Match.status == MatchStatus.FINISHED,
            Match.home_goals_90.is_not(None),
            Match.away_goals_90.is_not(None),
            Match.kickoff_at < as_of,
            or_(Match.home_team_id == team_id, Match.away_team_id == team_id),
        )
        .order_by(Match.kickoff_at.desc())
        .limit(limit)
    ).all()
    output: list[dict[str, Any]] = []
    for row in rows:
        is_home = row.home_team_id == team_id
        goals_for = row.home_goals_90 if is_home else row.away_goals_90
        goals_against = row.away_goals_90 if is_home else row.home_goals_90
        opponent_id = row.away_team_id if is_home else row.home_team_id
        opponent = session.get(Team, opponent_id)
        if goals_for > goals_against:
            result = "W"
        elif goals_for < goals_against:
            result = "L"
        else:
            result = "D"
        output.append(
            {
                "match_id": str(row.id),
                "kickoff_at": _iso(row.kickoff_at),
                "opponent": opponent.name if opponent is not None else None,
                "venue": "home" if is_home else "away",
                "goals_for": goals_for,
                "goals_against": goals_against,
                "result": result,
            }
        )
    return output


def build_evidence_packet(
    session: Session,
    match_id: uuid.UUID,
    *,
    as_of: datetime,
    stage: str,
) -> tuple[dict[str, Any], str]:
    cutoff = ensure_utc(as_of)
    match = session.get(Match, match_id)
    if match is None:
        raise ValueError(f"unknown match {match_id}")
    competition = session.get(Competition, match.competition_id)
    home = session.get(Team, match.home_team_id)
    away = session.get(Team, match.away_team_id)
    if competition is None or home is None or away is None:
        raise ValueError(f"incomplete match {match_id}")

    snapshot = session.scalar(
        select(OddsSnapshot)
        .where(
            OddsSnapshot.match_id == match.id,
            OddsSnapshot.market == MarketType.HAD,
            OddsSnapshot.snapshot_at <= cutoff,
        )
        .order_by(OddsSnapshot.snapshot_at.desc(), OddsSnapshot.id.desc())
        .limit(1)
    )
    odds: dict[str, str] = {}
    implied: dict[str, str] = {}
    line_rows: list[MarketLine] = []
    if snapshot is not None:
        line_rows = list(
            session.scalars(
                select(MarketLine).where(
                    MarketLine.snapshot_id == snapshot.id,
                    MarketLine.odds_type == MarketType.HAD,
                    MarketLine.condition_raw == "0.0",
                )
            ).all()
        )
        for line in line_rows:
            if isinstance(line.side, Side):
                key = line.side.value
            else:
                key = str(line.side)
            odds[key] = _decimal(line.odds_decimal)
            implied[key] = _decimal(Decimal(1) / line.odds_decimal)

    recent_home = _recent_matches(session, match, match.home_team_id, cutoff)
    recent_away = _recent_matches(session, match, match.away_team_id, cutoff)
    lineups = list(
        session.scalars(
            select(Lineup).where(
                Lineup.match_id == match.id,
                or_(Lineup.available_at.is_(None), Lineup.available_at <= cutoff),
                Lineup.fetched_at <= cutoff,
            )
        ).all()
    )
    availability = list(
        session.scalars(
            select(Availability).where(
                Availability.match_id == match.id,
                or_(
                    Availability.available_at.is_(None),
                    Availability.available_at <= cutoff,
                ),
                Availability.fetched_at <= cutoff,
            )
        ).all()
    )
    evidence_records = list(
        session.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.match_id == match.id,
                EvidenceRecord.available_at <= cutoff,
            )
            .order_by(EvidenceRecord.kind, EvidenceRecord.available_at.desc())
        ).all()
    )
    evidence: dict[str, list[dict[str, Any]]] = {}
    for record in evidence_records:
        evidence.setdefault(record.kind, []).append(
            {
                "evidence_ref": f"evidence:{record.id}",
                "source_name": record.source_name,
                "source_url": record.source_url,
                "available_at": _iso(record.available_at),
                "fetched_at": _iso(record.fetched_at),
                "payload": record.payload,
            }
        )

    packet: dict[str, Any] = {
        "match": {
            "match_id": str(match.id),
            "competition": competition.code,
            "season": match.season,
            "kickoff_at": _iso(match.kickoff_at),
            "status": match.status.value,
            "home_team": home.name,
            "away_team": away.name,
            "home_team_id": str(home.id),
            "away_team_id": str(away.id),
            "is_cup": competition.is_cup,
        },
        "as_of": cutoff.isoformat(),
        "stage": stage,
        "market": {
            "market": MarketType.HAD.value,
            "snapshot_id": str(snapshot.id) if snapshot is not None else None,
            "snapshot_at": _iso(snapshot.snapshot_at) if snapshot is not None else None,
            "odds": odds,
            "implied": implied,
            "line_count": len(line_rows),
            "line_status": {
                (line.side.value if isinstance(line.side, Side) else str(line.side)): line.line_status
                for line in line_rows
            },
            "pool_status": {
                (line.side.value if isinstance(line.side, Side) else str(line.side)): line.pool_status
                for line in line_rows
            },
        },
        "recent_matches": {
            "home": recent_home,
            "away": recent_away,
        },
        "lineups": [
            {
                "team_id": str(lineup.team_id),
                "lineup_type": lineup.lineup_type.value,
                "formation": lineup.formation,
                "starters": len(lineup.starters or []),
                "inferred": lineup.inferred,
                "source": lineup.source,
                "available_at": _iso(lineup.available_at),
            }
            for lineup in lineups
        ],
        "availability": [
            {
                "team_id": str(item.team_id),
                "status": item.status.value,
                "reason": item.reason,
                "source": item.source,
                "available_at": _iso(item.available_at),
            }
            for item in availability
        ],
        "quality": {
            "odds_available": snapshot is not None and len(odds) == 3,
            "odds_age_seconds": (
                int((cutoff - ensure_utc(snapshot.snapshot_at)).total_seconds())
                if snapshot is not None
                else None
            ),
            "lineup_confirmed": any(
                lineup.lineup_type.value == "standard" for lineup in lineups
            ),
            "lineup_count": len(lineups),
            "availability_count": len(availability),
            "missing_sources": [
                name
                for name, present in (
                    ("odds", snapshot is not None),
                    ("home_form", bool(recent_home)),
                    ("away_form", bool(recent_away)),
                    ("lineups", bool(lineups)),
                )
                if not present
            ],
        },
        "evidence": evidence,
        "source_audit": {
            "odds": {
                "status": "present" if snapshot is not None and len(odds) == 3 else "missing",
                "source": "hkjc",
                "ref": f"odds:{snapshot.id}" if snapshot is not None else None,
                "as_of": _iso(snapshot.snapshot_at) if snapshot is not None else None,
            },
            "recent_matches": {
                "status": "present" if recent_home and recent_away else "partial",
                "source": "football-data.org",
                "home_count": len(recent_home),
                "away_count": len(recent_away),
            },
            "lineups": {
                "status": "present" if lineups else "missing",
                "source": "fotmob",
                "count": len(lineups),
            },
            "availability": {
                "status": "present" if availability else "missing",
                "source": "football-data.org",
                "count": len(availability),
            },
            "weather": {
                "status": "present" if evidence.get("weather") else "missing",
                "source": "open-meteo",
                "count": len(evidence.get("weather", [])),
                "reason": None if evidence.get("weather") else "venue coordinates are not curated",
            },
            "news": {
                "status": "present" if evidence.get("news") else "missing",
                "source": "rss",
                "count": len(evidence.get("news", [])),
            },
            "standings": {
                "status": "present" if evidence.get("standings") else "missing",
                "source": "football-data.org",
                "count": len(evidence.get("standings", [])),
            },
            "xg": {
                "status": "present" if evidence.get("xg") else "missing",
                "source": "understat",
                "count": len(evidence.get("xg", [])),
            },
        },
        "source_refs": [
            f"match:{match.id}",
            *([f"odds:{snapshot.id}"] if snapshot is not None else []),
            *[f"match:{item['match_id']}" for item in recent_home],
            *[f"match:{item['match_id']}" for item in recent_away],
            *[f"lineup:{lineup.id}" for lineup in lineups],
            *[f"availability:{item.id}" for item in availability],
            *[f"evidence:{record.id}" for record in evidence_records],
        ],
    }
    encoded = json.dumps(packet, sort_keys=True, separators=(",", ":"), default=str)
    return packet, hashlib.sha256(encoded.encode("utf-8")).hexdigest()
