from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
)
from packages.domain.enums import MatchStatus
from packages.shared.time import parse_iso_utc

COMPETITION_CODE_MAP = {
    "EPL": "PL",
    "LALIGA": "PD",
    "BUNDESLIGA": "BL1",
    "SERIEA": "SA",
    "LIGUE1": "FL1",
    "UCL": "CL",
}

_STATUS_MAP = {
    "SCHEDULED": MatchStatus.SCHEDULED,
    "TIMED": MatchStatus.SCHEDULED,
    "IN_PLAY": MatchStatus.LIVE,
    "PAUSED": MatchStatus.LIVE,
    "FINISHED": MatchStatus.FINISHED,
    "POSTPONED": MatchStatus.POSTPONED,
    "CANCELLED": MatchStatus.CANCELLED,
}

_DEFAULT_LIMITER = MinIntervalRateLimiter(6.5)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FootballDataMatch:
    source_match_id: int
    competition_code: str
    season_start_year: int
    kickoff_at: datetime
    status: MatchStatus
    matchday: int | None
    home_team_source_id: int
    home_team_name: str
    away_team_source_id: int
    away_team_name: str
    home_goals_90: int | None
    away_goals_90: int | None
    home_goals_final: int | None
    away_goals_final: int | None


@dataclass(frozen=True)
class StandingRow:
    position: int
    team_source_id: int
    team_name: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points: int


class FootballDataOrgAdapter(BaseAdapter):
    name = "football-data.org"
    tos_risk = "low"
    schema_version = "v4"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.football-data.org/v4",
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else _DEFAULT_LIMITER,
        )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"X-Auth-Token": self._api_key}

    def fetch_matches(
        self,
        competition_code: str,
        season_start_year: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> FetchResult:
        code = COMPETITION_CODE_MAP.get(competition_code)
        if code is None:
            raise AdapterSchemaError(f"unknown competition code {competition_code}")
        params = {"season": str(season_start_year)}
        if date_from is not None:
            params["dateFrom"] = date_from
        if date_to is not None:
            params["dateTo"] = date_to
        return self._get_json(
            f"{self._base_url}/competitions/{code}/matches",
            params=params,
            headers=self._headers(),
        )

    def fetch_standings(self, competition_code: str, season_start_year: int) -> FetchResult:
        code = COMPETITION_CODE_MAP.get(competition_code)
        if code is None:
            raise AdapterSchemaError(f"unknown competition code {competition_code}")
        return self._get_json(
            f"{self._base_url}/competitions/{code}/standings",
            params={"season": str(season_start_year)},
            headers=self._headers(),
        )

    @staticmethod
    def parse_matches(payload: object) -> list[FootballDataMatch]:
        if not isinstance(payload, dict):
            raise AdapterSchemaError(
                f"payload must be an object, got {type(payload).__name__}"
            )
        competition_obj = payload.get("competition", {})
        if not isinstance(competition_obj, dict):
            raise AdapterSchemaError(
                f"competition must be an object, got {type(competition_obj).__name__}"
            )
        if "code" not in competition_obj:
            raise AdapterSchemaError("missing competition.code")
        competition = competition_obj["code"]
        if not isinstance(competition, str) or not competition.strip():
            raise AdapterSchemaError(f"invalid competition.code {competition!r}")
        filters = payload.get("filters", {})
        if not isinstance(filters, dict):
            raise AdapterSchemaError(
                f"filters must be an object, got {type(filters).__name__}"
            )
        if "season" not in filters:
            raise AdapterSchemaError("missing filters.season")
        season = filters["season"]
        if season is None:
            raise AdapterSchemaError("filters.season must not be null")
        try:
            season_start = int(season)
        except (TypeError, ValueError) as exc:
            raise AdapterSchemaError(f"invalid filters.season {season!r}") from exc
        matches = payload.get("matches", [])
        if not isinstance(matches, list):
            raise AdapterSchemaError(
                f"matches must be a list, got {type(matches).__name__}"
            )
        parsed: list[FootballDataMatch] = []
        for index, row in enumerate(matches):
            try:
                if not isinstance(row, dict):
                    raise TypeError(
                        f"match row must be an object, got {type(row).__name__}"
                    )
                source_match_id = int(row["id"])
                score = row.get("score", {})
                if not isinstance(score, dict):
                    raise TypeError(
                        f"score must be an object, got {type(score).__name__}"
                    )
                duration = score.get("duration")
                full_time = score.get("fullTime", {})
                if not isinstance(full_time, dict):
                    raise TypeError(
                        f"fullTime must be an object, got {type(full_time).__name__}"
                    )
                home_final = full_time.get("home")
                away_final = full_time.get("away")
                if duration == "REGULAR":
                    home_90 = home_final
                    away_90 = away_final
                elif duration is None or duration in {"EXTRA_TIME", "PENALTY_SHOOTOUT"}:
                    home_90 = None
                    away_90 = None
                else:
                    raise AdapterSchemaError(
                        f"unsupported score.duration {duration!r} for match {source_match_id}"
                    )
                if "utcDate" not in row:
                    raise AdapterSchemaError(f"missing utcDate for match {source_match_id}")
                utc_date = row["utcDate"]
                if not isinstance(utc_date, str):
                    raise TypeError(
                        f"utcDate must be a string, got {type(utc_date).__name__}"
                    )
                kickoff = parse_iso_utc(utc_date)
                if kickoff is None:
                    raise AdapterSchemaError(f"missing utcDate for match {source_match_id}")
                if "status" not in row:
                    raise AdapterSchemaError(f"missing status for match {source_match_id}")
                raw_status = row["status"]
                if not isinstance(raw_status, str):
                    raise TypeError(
                        f"status must be a string, got {type(raw_status).__name__}"
                    )
                status = _STATUS_MAP.get(raw_status.upper())
                if status is None:
                    logger.warning(
                        "skipping match %s: unsupported provider status %r",
                        source_match_id,
                        raw_status,
                    )
                    continue
                home_team = row["homeTeam"]
                away_team = row["awayTeam"]
                if not isinstance(home_team, dict):
                    raise TypeError(
                        f"homeTeam must be an object, got {type(home_team).__name__}"
                    )
                if not isinstance(away_team, dict):
                    raise TypeError(
                        f"awayTeam must be an object, got {type(away_team).__name__}"
                    )
                parsed.append(
                    FootballDataMatch(
                        source_match_id=source_match_id,
                        competition_code=competition,
                        season_start_year=season_start,
                        kickoff_at=kickoff,
                        status=status,
                        matchday=row.get("matchday"),
                        home_team_source_id=int(home_team["id"]),
                        home_team_name=str(home_team["name"]),
                        away_team_source_id=int(away_team["id"]),
                        away_team_name=str(away_team["name"]),
                        home_goals_90=home_90,
                        away_goals_90=away_90,
                        home_goals_final=home_final,
                        away_goals_final=away_final,
                    )
                )
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                match_id = row.get("id") if isinstance(row, dict) else None
                raise AdapterSchemaError(
                    f"invalid match row at index {index} (id={match_id}): {exc}"
                ) from exc
        return parsed

    @staticmethod
    def parse_standings(payload: object) -> list[StandingRow]:
        if not isinstance(payload, dict):
            raise AdapterSchemaError(
                f"payload must be an object, got {type(payload).__name__}"
            )
        if "standings" not in payload:
            raise AdapterSchemaError("missing standings")
        standings = payload["standings"]
        if not isinstance(standings, list):
            raise AdapterSchemaError(
                f"standings must be a list, got {type(standings).__name__}"
            )
        if not standings:
            raise AdapterSchemaError("missing standings")
        first_group = standings[0]
        if not isinstance(first_group, dict):
            raise AdapterSchemaError(
                f"standings[0] must be an object, got {type(first_group).__name__}"
            )
        table = first_group.get("table", [])
        if not isinstance(table, list):
            raise AdapterSchemaError(
                f"standings[0].table must be a list, got {type(table).__name__}"
            )
        rows: list[StandingRow] = []
        for index, entry in enumerate(table):
            try:
                if not isinstance(entry, dict):
                    raise TypeError(
                        f"standings row must be an object, got {type(entry).__name__}"
                    )
                team = entry.get("team", {})
                if not isinstance(team, dict):
                    raise TypeError(
                        f"team must be an object, got {type(team).__name__}"
                    )
                rows.append(
                    StandingRow(
                        position=int(entry["position"]),
                        team_source_id=int(team["id"]),
                        team_name=str(team["name"]),
                        played=int(entry.get("playedGames") or 0),
                        won=int(entry.get("won") or 0),
                        drawn=int(entry.get("draw") or 0),
                        lost=int(entry.get("lost") or 0),
                        goals_for=int(entry.get("goalsFor") or 0),
                        goals_against=int(entry.get("goalsAgainst") or 0),
                        points=int(entry.get("points") or 0),
                    )
                )
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                raise AdapterSchemaError(
                    f"invalid standings row at index {index}: {exc}"
                ) from exc
        return rows
