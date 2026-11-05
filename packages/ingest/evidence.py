from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from packages.adapters.base import AdapterError
from packages.db.models import Competition, EvidenceRecord, Match, Team
from packages.ingest.pipeline import AdapterBundle
from packages.shared.config import Settings
from packages.shared.time import ensure_utc, utc_now

NEWS_FILTER_TERMS = 3


def _hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _store(
    session: Session,
    *,
    match: Match,
    kind: str,
    source_name: str,
    source_url: str | None,
    payload: dict[str, Any],
    now: datetime,
    notes: str | None = None,
) -> None:
    digest = _hash(payload)
    exists = session.query(EvidenceRecord).filter_by(
        match_id=match.id, kind=kind, source_name=source_name, payload_hash=digest
    ).first()
    if exists is not None:
        return
    session.add(
        EvidenceRecord(
            match_id=match.id,
            kind=kind,
            source_name=source_name,
            source_url=source_url,
            available_at=now,
            fetched_at=now,
            payload=payload,
            payload_hash=digest,
            notes=notes,
        )
    )


def _team_terms(*teams: Team) -> set[str]:
    terms: set[str] = set()
    for team in teams:
        for value in (team.name, team.short_name):
            if value:
                terms.update(part.lower() for part in value.split() if len(part) >= NEWS_FILTER_TERMS)
    return terms


def _matches_team(text: str, terms: set[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def collect_match_evidence(
    session: Session,
    match: Match,
    adapters: AdapterBundle,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """Best-effort enrichment; missing sources remain absent, never invented."""
    current = ensure_utc(now or utc_now())
    competition = session.get(Competition, match.competition_id)
    home = session.get(Team, match.home_team_id)
    away = session.get(Team, match.away_team_id)
    if competition is None or home is None or away is None:
        return {}
    status: dict[str, str] = {}

    if adapters.news is not None and settings.news_feed_urls.strip():
        terms = _team_terms(home, away)
        for feed_url in (part.strip() for part in settings.news_feed_urls.split(",")):
            if not feed_url:
                continue
            try:
                fetched = adapters.news.fetch_feed(feed_url, "rss")
                items = adapters.news.parse_feed(fetched.raw_text, "rss")
                selected = [
                    {
                        "title": item.title,
                        "summary": item.summary,
                        "link": item.link,
                        "published_at": item.published_at.isoformat() if item.published_at else None,
                    }
                    for item in items
                    if _matches_team(f"{item.title} {item.summary}", terms)
                ]
                if selected:
                    _store(
                        session,
                        match=match,
                        kind="news",
                        source_name="rss",
                        source_url=feed_url,
                        payload={"items": selected},
                        now=current,
                    )
                status["news"] = "present" if selected else "missing"
            except AdapterError as exc:
                status["news"] = f"error:{exc}"
    else:
        status["news"] = "missing"

    football_data = getattr(adapters, "football_data", None)
    if football_data is not None and hasattr(football_data, "fetch_standings"):
        try:
            fetched = football_data.fetch_standings(
                competition.code, int(match.season[:4])
            )
            rows = football_data.parse_standings(fetched.payload)
            terms = _team_terms(home, away)
            relevant = [
                {
                    "position": row.position,
                    "team": row.team_name,
                    "played": row.played,
                    "won": row.won,
                    "drawn": row.drawn,
                    "lost": row.lost,
                    "goals_for": row.goals_for,
                    "goals_against": row.goals_against,
                    "points": row.points,
                }
                for row in rows
                if _matches_team(row.team_name, terms)
            ]
            if relevant:
                _store(
                    session,
                    match=match,
                    kind="standings",
                    source_name="football-data.org",
                    source_url=fetched.source_url,
                    payload={"rows": relevant},
                    now=current,
                )
            status["standings"] = "present" if relevant else "missing"
        except (AdapterError, ValueError) as exc:
            status["standings"] = f"error:{exc}"
    else:
        status["standings"] = "missing"

    if adapters.understat is not None and competition.code in {
        "EPL",
        "LALIGA",
        "BUNDESLIGA",
        "SERIEA",
        "LIGUE1",
    }:
        try:
            fetched = adapters.understat.fetch_league(
                competition.code, int(match.season[:4])
            )
            rows = adapters.understat.parse_team_seasons(fetched.raw_text)
            terms = _team_terms(home, away)
            relevant = [
                {
                    "team": row.team_name,
                    "matches": row.matches,
                    "goals": row.goals,
                    "xg": str(row.xg),
                    "xga": str(row.xga),
                    "npxg": str(row.npxg),
                    "ppda": str(row.ppda),
                    "deep": row.deep,
                }
                for row in rows
                if _matches_team(row.team_name, terms)
            ]
            if relevant:
                _store(
                    session,
                    match=match,
                    kind="xg",
                    source_name="understat",
                    source_url=fetched.source_url,
                    payload={"teams": relevant},
                    now=current,
                )
            status["xg"] = "present" if relevant else "missing"
        except (AdapterError, ValueError) as exc:
            status["xg"] = f"error:{exc}"
    else:
        status["xg"] = "missing"

    # Weather needs a venue coordinate. Until team venue coordinates are curated,
    # the packet must explicitly report the source as missing rather than guess.
    status["weather"] = "missing"
    session.flush()
    return status
