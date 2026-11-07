from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import ClassVar, cast

import httpx

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    CoverageGapError,
    FetchResult,
    MinIntervalRateLimiter,
)
from packages.domain.enums import AvailabilityStatus, LineupType
from packages.shared.time import parse_iso_utc

COMPETITION_CODES = frozenset(
    {"EPL", "LALIGA", "BUNDESLIGA", "SERIEA", "LIGUE1", "UCL"}
)

FOTMOB_LEAGUE_IDS = {
    "EPL": 47,
    "LALIGA": 87,
    "BUNDESLIGA": 54,
    "SERIEA": 55,
    "LIGUE1": 53,
    "UCL": 42,
}

_UNAVAILABLE_STATUS = {
    "injury": AvailabilityStatus.INJURY,
    "suspension": AvailabilityStatus.SUSPENSION,
    "doubtful": AvailabilityStatus.DOUBTFUL,
    "available": AvailabilityStatus.AVAILABLE,
}

_DEFAULT_LIMITER = MinIntervalRateLimiter(600.0)


@dataclass(frozen=True)
class LineupPlayer:
    source_player_id: int
    name: str
    position: str | None


@dataclass(frozen=True)
class LineupDTO:
    team_side: str
    lineup_type: LineupType
    formation: str | None
    starters: tuple[LineupPlayer, ...]
    subs: tuple[LineupPlayer, ...]
    inferred: bool


@dataclass(frozen=True)
class FotMobFixture:
    fixture_id: int
    kickoff_at: datetime
    home_name: str
    away_name: str


@dataclass(frozen=True)
class FotMobTeamXG:
    team_id: int | None
    team_name: str
    matches: int | None
    xg: Decimal
    xga: Decimal


@dataclass(frozen=True)
class UnavailableDTO:
    team_side: str
    source_player_id: int | None
    name: str
    status: AvailabilityStatus
    reason: str | None
    expected_return: date | None


def _as_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AdapterSchemaError(f"{label} must be an object")
    return cast("dict[str, object]", value)


def _as_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise AdapterSchemaError(f"{label} must be a list")
    return cast("list[object]", value)


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterSchemaError(f"{label} must be a string")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise AdapterSchemaError(f"{label} must be a positive integer")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise AdapterSchemaError(f"{label} must be a positive integer") from exc
    if parsed <= 0:
        raise AdapterSchemaError(f"{label} must be a positive integer")
    return parsed


def _lineup_type(value: object) -> LineupType:
    if not isinstance(value, LineupType):
        raise AdapterSchemaError(
            f"lineup_type must be a LineupType, got {type(value).__name__}"
        )
    return value


def _player_name(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterSchemaError(f"{label} name must be a non-empty string")
    return value


def _lineup_player(raw: object, label: str) -> LineupPlayer:
    row = _as_object(raw, f"{label} player")
    return LineupPlayer(
        source_player_id=_positive_int(row.get("id"), f"{label} id"),
        name=_player_name(row.get("name"), label),
        position=_optional_string(row.get("position"), f"{label} position"),
    )


def _lineup_players(
    value: object, label: str, *, allow_empty: bool
) -> tuple[LineupPlayer, ...]:
    raw_players = _as_list(value, label)
    if not raw_players and not allow_empty:
        raise AdapterSchemaError(f"{label} must not be empty")
    return tuple(_lineup_player(raw, label) for raw in raw_players)


def _decimal_required(value: object, label: str) -> Decimal:
    if value is None:
        raise AdapterSchemaError(f"{label} is missing")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AdapterSchemaError(f"{label} is not a decimal") from exc
    if not parsed.is_finite():
        raise AdapterSchemaError(f"{label} must be finite")
    return parsed


def _expected_return(value: object, label: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterSchemaError(f"{label}.expectedReturn must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AdapterSchemaError(f"invalid {label}.expectedReturn {value!r}") from exc


class FotMobAdapter(BaseAdapter):
    name: ClassVar[str] = "fotmob"
    tos_risk: ClassVar[str] = "high"
    schema_version: ClassVar[str] = "api-v1"
    competition_codes: ClassVar[frozenset[str]] = COMPETITION_CODES

    def __init__(
        self,
        base_url: str = "https://www.fotmob.com/api/data",
        client: httpx.Client | None = None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else _DEFAULT_LIMITER,
        )
        self._base_url: str = base_url.rstrip("/")

    @classmethod
    def supports_competition(cls, competition_code: str) -> bool:
        return competition_code.upper() in cls.competition_codes

    def fetch_league_fixtures(
        self,
        competition_code: str,
        season_start_year: int,
    ) -> FetchResult:
        league_id = FOTMOB_LEAGUE_IDS.get(competition_code.upper())
        if league_id is None:
            raise CoverageGapError(
                f"fotmob has no league mapping for {competition_code}"
            )
        season = f"{season_start_year}-{season_start_year + 1}"
        return self._get_json(
            f"{self._base_url}/leagues",
            params={"id": league_id, "season": season},
        )

    @staticmethod
    def parse_league_fixtures(payload: object) -> list[FotMobFixture]:
        root = _as_object(payload, "payload")
        fixtures = _as_object(root.get("fixtures"), "fixtures")
        raw_matches = _as_list(fixtures.get("allMatches"), "fixtures.allMatches")
        rows: list[FotMobFixture] = []
        for index, raw in enumerate(raw_matches):
            label = f"fixtures.allMatches[{index}]"
            row = _as_object(raw, label)
            fixture_id = _positive_int(row.get("id"), f"{label}.id")
            home = _as_object(row.get("home"), f"{label}.home")
            away = _as_object(row.get("away"), f"{label}.away")
            status = _as_object(row.get("status"), f"{label}.status")
            raw_kickoff = status.get("utcTime")
            if not isinstance(raw_kickoff, str):
                raise AdapterSchemaError(f"{label}.status.utcTime must be a string")
            kickoff_at = parse_iso_utc(raw_kickoff)
            if kickoff_at is None:
                raise AdapterSchemaError(f"{label}.status.utcTime is invalid")
            home_name = _optional_string(home.get("name"), f"{label}.home.name")
            away_name = _optional_string(away.get("name"), f"{label}.away.name")
            if not home_name or not away_name:
                raise AdapterSchemaError(f"{label} has an empty team name")
            rows.append(
                FotMobFixture(
                    fixture_id=fixture_id,
                    kickoff_at=kickoff_at,
                    home_name=home_name,
                    away_name=away_name,
                )
            )
        return rows

    def fetch_match_details(self, match_id: int) -> FetchResult:
        validated_id = _positive_int(match_id, "match_id")
        return self._get_json(
            f"{self._base_url}/matchDetails",
            params={"matchId": str(validated_id)},
        )

    @staticmethod
    def parse_team_xg(payload: object) -> list[FotMobTeamXG]:
        root = _as_object(payload, "payload")
        raw_tables = _as_list(root.get("table"), "table")
        rows: list[FotMobTeamXG] = []
        for table_index, raw_table in enumerate(raw_tables):
            table = _as_object(raw_table, f"table[{table_index}]")
            data = _as_object(table.get("data"), f"table[{table_index}].data")
            table_data = _as_object(
                data.get("table"), f"table[{table_index}].data.table"
            )
            raw_entries = table_data.get("xg")
            if raw_entries is None:
                continue
            entries = _as_list(
                raw_entries, f"table[{table_index}].data.table.xg"
            )
            for index, raw in enumerate(entries):
                label = f"table[{table_index}].data.table.xg[{index}]"
                entry = _as_object(raw, label)
                name = _optional_string(
                    entry.get("name") or entry.get("teamName"), f"{label}.name"
                )
                if not name:
                    raise AdapterSchemaError(f"{label}.name is empty")
                raw_team_id = entry.get("teamId") or entry.get("id")
                team_id = (
                    _positive_int(raw_team_id, f"{label}.teamId")
                    if raw_team_id is not None
                    else None
                )
                raw_played = entry.get("played")
                matches = (
                    int(raw_played)
                    if isinstance(raw_played, (int, float))
                    and not isinstance(raw_played, bool)
                    else None
                )
                rows.append(
                    FotMobTeamXG(
                        team_id=team_id,
                        team_name=name,
                        matches=matches,
                        xg=_decimal_required(entry.get("xg"), f"{label}.xg"),
                        xga=_decimal_required(
                            entry.get("xgConceded"), f"{label}.xgConceded"
                        ),
                    )
                )
        return rows

    @staticmethod
    def parse_lineups(payload: object, lineup_type: LineupType) -> list[LineupDTO]:
        parsed_type = _lineup_type(lineup_type)
        root = _as_object(payload, "payload")
        content = _as_object(root.get("content"), "content")
        if "lineup" not in content:
            raise AdapterSchemaError("missing content.lineup")
        lineup = _as_object(content["lineup"], "content.lineup")
        inferred = parsed_type is LineupType.PREDICTED
        rows: list[LineupDTO] = []
        for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
            if key not in lineup:
                raise AdapterSchemaError(f"missing content.lineup.{key}")
            label = f"content.lineup.{key}"
            team = _as_object(lineup[key], label)
            rows.append(
                LineupDTO(
                    team_side=side,
                    lineup_type=parsed_type,
                    formation=_optional_string(team.get("formation"), f"{label}.formation"),
                    starters=_lineup_players(
                        team.get("starters"), f"{label}.starters", allow_empty=False
                    ),
                    subs=_lineup_players(team.get("subs", []), f"{label}.subs", allow_empty=True),
                    inferred=inferred,
                )
            )
        return rows

    @staticmethod
    def parse_unavailable(payload: object) -> list[UnavailableDTO]:
        root = _as_object(payload, "payload")
        content = _as_object(root.get("content"), "content")
        raw_unavailable: object = content.get("unavailable")
        if raw_unavailable is None:
            raw_unavailable = {}
        unavailable = _as_object(raw_unavailable, "content.unavailable")
        rows: list[UnavailableDTO] = []
        for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
            if key not in unavailable:
                continue
            label = f"content.unavailable.{key}"
            entries = _as_list(unavailable[key], label)
            for index, raw in enumerate(entries):
                row_label = f"{label}[{index}]"
                row = _as_object(raw, row_label)
                raw_status = _optional_string(row.get("type"), f"{row_label}.type")
                status_key = (raw_status or "").lower()
                status = _UNAVAILABLE_STATUS.get(status_key)
                if status is None:
                    raise AdapterSchemaError(f"unknown unavailable type {status_key!r}")
                player_id_value = row.get("id")
                player_id = (
                    None
                    if player_id_value is None
                    else _positive_int(player_id_value, f"{row_label} id")
                )
                name_value = row.get("name")
                if name_value is None:
                    name = ""
                elif isinstance(name_value, str):
                    name = name_value
                else:
                    raise AdapterSchemaError(f"{row_label}.name must be a string")
                if player_id is None and not name:
                    raise AdapterSchemaError(f"{row_label} must have an id or name")
                rows.append(
                    UnavailableDTO(
                        team_side=side,
                        source_player_id=player_id,
                        name=name,
                        status=status,
                        reason=_optional_string(row.get("reason"), f"{row_label}.reason"),
                        expected_return=_expected_return(
                            row.get("expectedReturn"), row_label
                        ),
                    )
                )
        return rows
