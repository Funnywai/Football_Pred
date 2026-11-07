from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.adapters.fotmob import FotMobFixture
from packages.adapters.hkjc import HkjcScheduledMatch
from packages.db.models import Match, Team
from packages.domain.errors import UnresolvedTeamError
from packages.ingest.aliases import canonical_team_slug, resolve_team_id
from packages.ingest.normalize import get_competition
from packages.shared.time import ensure_utc

logger = logging.getLogger(__name__)

LINK_KICKOFF_WINDOW = timedelta(days=1)
_CLUB_SUFFIXES = frozenset(
    {"fc", "afc", "cf", "sc", "ac", "as", "ssc", "vfl", "vfb", "fsv", "ogc", "rc", "ud", "rcd", "ca", "sv", "tsg", "club", "calcio"}
)
# Tokens that only describe the legal form of a club, never the club itself.
# They are removed before comparing provider names with stored team names.
_GENERIC_NAME_TOKENS = frozenset(
    {
        "ac", "acf", "afc", "aj", "as", "ca", "calcio", "cf", "club", "clube",
        "cs", "estac", "fc", "fk", "fsv", "kv", "losc", "ogc", "osc", "pae",
        "rc", "rcd", "sc", "sco", "sk", "ss", "ssc", "sv", "the", "tsg", "ud",
        "us", "vfb", "vfl", "and", "de", "del", "della", "a", "el", "la",
        "las", "los",
    }
)

# HKJC tournament ids captured from the legacy main-branch league registry.
HKJC_TOURNAMENT_IDS: dict[str, str] = {
    "EPL": "50071337",
    "LALIGA": "50072540",
    "BUNDESLIGA": "50072572",
    "SERIEA": "50072541",
    "LIGUE1": "50072542",
    "UCL": "50070797",
}


@dataclass(frozen=True)
class _ProviderFixture:
    source_id: str
    kickoff_at: datetime
    home_name: str
    away_name: str


def _relaxed_slug(name: str) -> str:
    parts = canonical_team_slug(name).split("-")
    while parts and parts[-1] in _CLUB_SUFFIXES:
        parts.pop()
    return "-".join(parts)


def _name_tokens(name: str) -> frozenset[str]:
    normalized = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    )
    normalized = normalized.casefold().replace("&", " and ")
    return frozenset(
        token
        for token in re.split(r"[^a-z0-9]+", normalized)
        if token and not token.isdigit() and token not in _GENERIC_NAME_TOKENS
    )


def _tournament_matches(candidate: HkjcScheduledMatch, competition_code: str) -> bool:
    expected_tournament_id = HKJC_TOURNAMENT_IDS.get(competition_code)
    if candidate.tournament_id is not None and expected_tournament_id is not None:
        return candidate.tournament_id == expected_tournament_id
    if candidate.tournament_code is None:
        return True
    return (
        candidate.tournament_code.strip().casefold()
        == competition_code.strip().casefold()
    )


class _TeamMatcher:
    """Resolve provider team names against the teams of one competition.

    Direct aliases win. Otherwise the provider name is tokenised and accepted
    when it is a subset of a stored team name (``Coventry`` -> ``Coventry City
    FC``). Subset matches can be ambiguous on their own, so the caller only
    links when the home/away pair selects exactly one stored fixture.
    """

    def __init__(self, session: Session, teams: Iterable[Team]) -> None:
        self._session = session
        self._teams = {team.id: team for team in teams}
        self._tokens = {team.id: _name_tokens(team.name) for team in teams}
        self._relaxed = {
            _relaxed_slug(team.name): team.id for team in self._teams.values()
        }
        self._resolved: dict[str, uuid.UUID | None] = {}

    @property
    def team_ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(self._teams)

    def team_name(self, team_id: uuid.UUID) -> str:
        team = self._teams.get(team_id)
        return team.name if team is not None else str(team_id)

    def resolve(self, name: str) -> uuid.UUID | None:
        if name not in self._resolved:
            try:
                resolved = resolve_team_id(self._session, name)
            except UnresolvedTeamError:
                resolved = self._relaxed.get(_relaxed_slug(name))
            self._resolved[name] = resolved
        return self._resolved[name]

    def matches(self, name: str, team_id: uuid.UUID) -> bool:
        resolved = self.resolve(name)
        if resolved is not None:
            return resolved == team_id
        tokens = _name_tokens(name)
        return bool(tokens) and tokens <= self._tokens.get(team_id, frozenset())

    def matches_any(self, name: str) -> bool:
        return any(self.matches(name, team_id) for team_id in self._teams)


def _competition_teams(session: Session, competition_id: uuid.UUID) -> list[Team]:
    team_ids = set(
        session.scalars(
            select(Match.home_team_id).where(Match.competition_id == competition_id)
        ).all()
    )
    team_ids.update(
        session.scalars(
            select(Match.away_team_id).where(Match.competition_id == competition_id)
        ).all()
    )
    if not team_ids:
        return []
    return list(session.scalars(select(Team).where(Team.id.in_(team_ids))).all())


def _link_provider_fixtures(
    session: Session,
    fixtures: Iterable[_ProviderFixture],
    *,
    competition_code: str,
    source_key: str,
) -> int:
    competition = get_competition(session, competition_code)
    candidates = list(fixtures)
    if not candidates:
        return 0

    matcher = _TeamMatcher(session, _competition_teams(session, competition.id))
    kickoffs = [ensure_utc(candidate.kickoff_at) for candidate in candidates]
    window_start = min(kickoffs) - LINK_KICKOFF_WINDOW
    window_end = max(kickoffs) + LINK_KICKOFF_WINDOW
    matches = list(
        session.scalars(
            select(Match).where(
                Match.competition_id == competition.id,
                Match.kickoff_at >= window_start,
                Match.kickoff_at <= window_end,
            )
        ).all()
    )

    linked = 0
    for candidate in candidates:
        kickoff_at = ensure_utc(candidate.kickoff_at)
        nearby = [
            match
            for match in matches
            if abs((ensure_utc(match.kickoff_at) - kickoff_at).total_seconds())
            <= LINK_KICKOFF_WINDOW.total_seconds()
        ]
        matched = [
            match
            for match in nearby
            if matcher.matches(candidate.home_name, match.home_team_id)
            and matcher.matches(candidate.away_name, match.away_team_id)
        ]
        if not matched:
            unresolved = [
                name
                for name in (candidate.home_name, candidate.away_name)
                if not matcher.matches_any(name)
            ]
            if unresolved:
                logger.warning(
                    "unresolved %s team name(s) %s in %s fixture %s (%s v %s)",
                    source_key,
                    ", ".join(repr(name) for name in unresolved),
                    competition_code,
                    candidate.source_id,
                    candidate.home_name,
                    candidate.away_name,
                )
            else:
                logger.warning(
                    "no stored %s fixture for %s match %s (%s v %s at %s)",
                    competition_code,
                    source_key,
                    candidate.source_id,
                    candidate.home_name,
                    candidate.away_name,
                    kickoff_at.isoformat(),
                )
            continue

        pairs = {(match.home_team_id, match.away_team_id) for match in matched}
        if len(pairs) > 1:
            labels = sorted(
                f"{matcher.team_name(home_id)} v {matcher.team_name(away_id)}"
                for home_id, away_id in pairs
            )
            logger.warning(
                "ambiguous %s fixture %s in %s (%s v %s): %s",
                source_key,
                candidate.source_id,
                competition_code,
                candidate.home_name,
                candidate.away_name,
                "; ".join(labels),
            )
            continue

        target = min(
            matched,
            key=lambda match: abs(
                (ensure_utc(match.kickoff_at) - kickoff_at).total_seconds()
            ),
        )
        source_match_ids = dict(target.source_match_ids or {})
        if source_match_ids.get(source_key) == candidate.source_id:
            continue
        source_match_ids[source_key] = candidate.source_id
        target.source_match_ids = source_match_ids
        session.flush()
        linked += 1
    return linked


def link_hkjc_matches(
    session: Session,
    scheduled: Iterable[HkjcScheduledMatch],
    *,
    competition_code: str = "EPL",
) -> int:
    fixtures = [
        _ProviderFixture(
            source_id=candidate.match_source_id,
            kickoff_at=candidate.kickoff_at,
            home_name=candidate.home_name,
            away_name=candidate.away_name,
        )
        for candidate in scheduled
        if _tournament_matches(candidate, competition_code)
    ]
    return _link_provider_fixtures(
        session,
        fixtures,
        competition_code=competition_code,
        source_key="hkjc",
    )


def link_fotmob_matches(
    session: Session,
    fixtures: Iterable[FotMobFixture],
    *,
    competition_code: str,
) -> int:
    candidates = [
        _ProviderFixture(
            source_id=str(fixture.fixture_id),
            kickoff_at=fixture.kickoff_at,
            home_name=fixture.home_name,
            away_name=fixture.away_name,
        )
        for fixture in fixtures
    ]
    return _link_provider_fixtures(
        session,
        candidates,
        competition_code=competition_code,
        source_key="fotmob",
    )
