from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.adapters.hkjc import HkjcScheduledMatch
from packages.db.models import Match, Team
from packages.domain.errors import UnresolvedTeamError
from packages.ingest.aliases import canonical_team_slug, resolve_team_id
from packages.ingest.normalize import get_competition
from packages.shared.time import ensure_utc

LINK_KICKOFF_WINDOW = timedelta(days=1)
_CLUB_SUFFIXES = frozenset(
    {"fc", "afc", "cf", "sc", "ac", "as", "ssc", "vfl", "vfb", "fsv", "ogc", "rc", "ud", "rcd", "ca", "sv", "tsg", "club", "calcio"}
)


def _relaxed_slug(name: str) -> str:
    parts = canonical_team_slug(name).split("-")
    while parts and parts[-1] in _CLUB_SUFFIXES:
        parts.pop()
    return "-".join(parts)


def _resolve_linked_team_id(
    session: Session, name: str, relaxed: dict[str, uuid.UUID]
) -> uuid.UUID | None:
    try:
        return resolve_team_id(session, name)
    except UnresolvedTeamError:
        return relaxed.get(_relaxed_slug(name))

# HKJC tournament ids captured from the legacy main-branch league registry.
HKJC_TOURNAMENT_IDS: dict[str, str] = {
    "EPL": "50071337",
    "LALIGA": "50072540",
    "BUNDESLIGA": "50072572",
    "SERIEA": "50072541",
    "LIGUE1": "50072542",
    "UCL": "50070797",
}


def link_hkjc_matches(
    session: Session,
    scheduled: Iterable[HkjcScheduledMatch],
    *,
    competition_code: str = "EPL",
) -> int:
    competition = get_competition(session, competition_code)
    relaxed_teams: dict[str, uuid.UUID] = {
        _relaxed_slug(team.name): team.id
        for team in session.scalars(select(Team)).all()
    }
    linked = 0
    for candidate in scheduled:
        expected_tournament_id = HKJC_TOURNAMENT_IDS.get(competition_code)
        if candidate.tournament_id is not None and expected_tournament_id is not None:
            if candidate.tournament_id != expected_tournament_id:
                continue
        elif (
            candidate.tournament_code is not None
            and candidate.tournament_code.strip().casefold()
            != competition_code.strip().casefold()
        ):
            continue
        home_team_id = _resolve_linked_team_id(
            session, candidate.home_name, relaxed_teams
        )
        away_team_id = _resolve_linked_team_id(
            session, candidate.away_name, relaxed_teams
        )
        if home_team_id is None or away_team_id is None:
            continue
        kickoff_at = ensure_utc(candidate.kickoff_at)
        matches = list(
            session.execute(
                select(Match).where(
                    Match.competition_id == competition.id,
                    Match.home_team_id == home_team_id,
                    Match.away_team_id == away_team_id,
                    Match.kickoff_at >= kickoff_at - LINK_KICKOFF_WINDOW,
                    Match.kickoff_at <= kickoff_at + LINK_KICKOFF_WINDOW,
                )
            ).scalars()
        )
        if not matches:
            continue
        target = min(
            matches,
            key=lambda match: abs(
                (ensure_utc(match.kickoff_at) - kickoff_at).total_seconds()
            ),
        )
        source_match_ids = dict(target.source_match_ids or {})
        if source_match_ids.get("hkjc") == candidate.match_source_id:
            continue
        source_match_ids["hkjc"] = candidate.match_source_id
        target.source_match_ids = source_match_ids
        session.flush()
        linked += 1
    return linked
