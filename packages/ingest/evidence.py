from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from packages.adapters.base import (
    AdapterError,
    AdapterSchemaError,
    MinIntervalRateLimiter,
)
from packages.adapters.fotmob import FotMobAdapter
from packages.db.models import Competition, EvidenceRecord, Match, Team
from packages.ingest.pipeline import AdapterBundle
from packages.ingest.venues import venue_for_team
from packages.shared.config import Settings
from packages.shared.time import ensure_utc, utc_now

NEWS_FILTER_TERMS = 3
_XG_ATTEMPTS = 2
_XG_RETRY_SECONDS = 1.0
_FOTMOB_XG_LIMITER_SECONDS = 5.0

logger = logging.getLogger(__name__)

PendingRecord = tuple[str, str, str | None, dict[str, Any]]


def _hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _store(
    session: Session,
    *,
    match_id: uuid.UUID,
    kind: str,
    source_name: str,
    source_url: str | None,
    payload: dict[str, Any],
    now: datetime,
    notes: str | None = None,
) -> None:
    digest = _hash(payload)
    exists = session.query(EvidenceRecord).filter_by(
        match_id=match_id,
        kind=kind,
        source_name=source_name,
        payload_hash=digest,
    ).first()
    if exists is not None:
        return
    session.add(
        EvidenceRecord(
            match_id=match_id,
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
                terms.update(
                    part.lower()
                    for part in value.split()
                    if len(part) >= NEWS_FILTER_TERMS
                )
    return terms


def _matches_team(text: str, terms: set[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _fotmob_xg_fallback(
    *,
    match_id: uuid.UUID,
    competition_code: str,
    season_year: int,
    terms: set[str],
    now: datetime,
    pending: list[PendingRecord],
) -> str:
    adapter = FotMobAdapter(
        limiter=MinIntervalRateLimiter(_FOTMOB_XG_LIMITER_SECONDS)
    )
    try:
        fetched = adapter.fetch_league_fixtures(competition_code, season_year)
        rows = FotMobAdapter.parse_team_xg(fetched.payload)
        relevant = [
            {
                "team": row.team_name,
                "matches": row.matches,
                "xg": str(row.xg),
                "xga": str(row.xga),
                "npxg": None,
                "ppda": None,
                "deep": None,
                "source": "fotmob",
            }
            for row in rows
            if _matches_team(row.team_name, terms)
        ]
        if not relevant:
            return "missing:fotmob_no_team_rows"
        pending.append(
            ("xg", "fotmob", fetched.source_url, {"teams": relevant})
        )
        return "present:fotmob"
    except (AdapterError, ValueError) as exc:
        logger.warning("fotmob xG fallback failed for %s: %s", match_id, exc)
        return f"error:fotmob:{exc}"
    finally:
        adapter.close()


def collect_match_evidence(
    session: Session,
    match: Match,
    adapters: AdapterBundle,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """Best-effort enrichment; missing sources remain absent, never invented.

    External calls are made before any evidence rows are written. The session
    transaction is closed up front so a slow RSS/Understat request cannot hold
    row locks and block lineup or decision jobs.
    """
    current = ensure_utc(now or utc_now())
    competition = session.get(Competition, match.competition_id)
    home = session.get(Team, match.home_team_id)
    away = session.get(Team, match.away_team_id)
    if competition is None or home is None or away is None:
        return {}

    match_id = match.id
    competition_code = competition.code
    season_year = int(match.season[:4])
    kickoff_at = ensure_utc(match.kickoff_at)
    home_slug = home.slug
    terms = _team_terms(home, away)
    status: dict[str, str] = {}
    pending: list[PendingRecord] = []
    session.commit()

    if adapters.news is not None and settings.news_feed_urls.strip():
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
                        "published_at": item.published_at.isoformat()
                        if item.published_at
                        else None,
                    }
                    for item in items
                    if _matches_team(f"{item.title} {item.summary}", terms)
                ]
                if selected:
                    pending.append(
                        ("news", "rss", feed_url, {"items": selected})
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
                competition_code, season_year
            )
            rows = football_data.parse_standings(fetched.payload)
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
                pending.append(
                    (
                        "standings",
                        "football-data.org",
                        fetched.source_url,
                        {"rows": relevant},
                    )
                )
            status["standings"] = "present" if relevant else "missing"
        except (AdapterError, ValueError) as exc:
            status["standings"] = f"error:{exc}"
    else:
        status["standings"] = "missing"

    if adapters.understat is not None and competition_code in {
        "EPL",
        "LALIGA",
        "BUNDESLIGA",
        "SERIEA",
        "LIGUE1",
    }:
        last_error: Exception | None = None
        for attempt in range(1, _XG_ATTEMPTS + 1):
            try:
                fetched = adapters.understat.fetch_league(
                    competition_code, season_year
                )
                rows = adapters.understat.parse_team_seasons(fetched.raw_text)
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
                    pending.append(
                        ("xg", "understat", fetched.source_url, {"teams": relevant})
                    )
                status["xg"] = "present" if relevant else "missing"
                last_error = None
                break
            except (AdapterError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "understat xG attempt %s/%s failed for %s: %s",
                    attempt,
                    _XG_ATTEMPTS,
                    competition_code,
                    exc,
                )
                if isinstance(exc, AdapterSchemaError):
                    break
                if attempt < _XG_ATTEMPTS:
                    time.sleep(_XG_RETRY_SECONDS)
        if last_error is not None:
            fallback = _fotmob_xg_fallback(
                match_id=match_id,
                competition_code=competition_code,
                season_year=season_year,
                terms=terms,
                now=current,
                pending=pending,
            )
            if fallback.startswith("present"):
                status["xg"] = fallback
            else:
                status["xg"] = f"error:{last_error} (fotmob:{fallback})"
        elif status.get("xg") != "present":
            fallback = _fotmob_xg_fallback(
                match_id=match_id,
                competition_code=competition_code,
                season_year=season_year,
                terms=terms,
                now=current,
                pending=pending,
            )
            if fallback.startswith("present"):
                status["xg"] = fallback
    else:
        status["xg"] = "missing"

    weather = getattr(adapters, "weather", None)
    venue = venue_for_team(home_slug)
    if weather is None:
        status["weather"] = "missing:adapter_not_configured"
    elif venue is None:
        status["weather"] = "missing:venue_not_curated"
    else:
        latitude, longitude, city = venue
        try:
            fetched = weather.fetch_hourly(
                latitude,
                longitude,
                kickoff_at.date(),
                kickoff_at.date(),
            )
            points = weather.parse_hourly(fetched.payload)
            summary = weather.nearest_to_kickoff(points, kickoff_at)
            if summary is None:
                status["weather"] = "missing:no_forecast_point"
            else:
                pending.append(
                    (
                        "weather",
                        "open-meteo",
                        fetched.source_url,
                        {
                            "venue": {
                                "city": city,
                                "latitude": latitude,
                                "longitude": longitude,
                            },
                            "time_utc": ensure_utc(
                                summary.point.time_utc
                            ).isoformat(),
                            "delta_hours": summary.delta_hours,
                            "temperature_c": str(summary.point.temperature_c),
                            "precipitation_mm": str(
                                summary.point.precipitation_mm
                            ),
                            "wind_speed_kmh": str(summary.point.wind_speed_kmh),
                        },
                    )
                )
                status["weather"] = "present"
        except AdapterError as exc:
            status["weather"] = f"error:{exc}"
            logger.warning("weather fetch failed for %s: %s", match_id, exc)

    for kind, source_name, source_url, payload in pending:
        _store(
            session,
            match_id=match_id,
            kind=kind,
            source_name=source_name,
            source_url=source_url,
            payload=payload,
            now=current,
        )
    session.flush()
    return status
