from __future__ import annotations

from typing import ClassVar, cast

import httpx

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
)
from packages.adapters.fotmob import LineupDTO, LineupPlayer
from packages.domain.enums import LineupType

COMPETITION_CODES = frozenset({"EPL"})

_DEFAULT_LIMITER = MinIntervalRateLimiter(10.0)


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


def _player(raw: object, label: str) -> LineupPlayer:
    row = _as_object(raw, f"{label} player")
    name = row.get("name")
    if not isinstance(name, str) or not name.strip():
        raise AdapterSchemaError(f"{label} name must be a non-empty string")
    return LineupPlayer(
        source_player_id=_positive_int(row.get("id"), f"{label} id"),
        name=name,
        position=_optional_string(row.get("position"), f"{label} position"),
    )


def _players(value: object, label: str, *, allow_empty: bool) -> tuple[LineupPlayer, ...]:
    raw_players = _as_list(value, label)
    if not raw_players and not allow_empty:
        raise AdapterSchemaError(f"{label} must not be empty")
    return tuple(_player(raw, label) for raw in raw_players)


class PlPulseliveAdapter(BaseAdapter):
    name: ClassVar[str] = "pl-pulselive"
    tos_risk: ClassVar[str] = "low"
    schema_version: ClassVar[str] = "v1"
    competition_codes: ClassVar[frozenset[str]] = COMPETITION_CODES

    def __init__(
        self,
        base_url: str = "https://footballapi.pulselive.com/football",
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

    def fetch_lineups(self, fixture_id: int) -> FetchResult:
        validated_id = _positive_int(fixture_id, "fixture_id")
        headers = {
            "Origin": "https://www.premierleague.com",
            "Referer": "https://www.premierleague.com/",
        }
        return self._get_json(
            f"{self._base_url}/fixtures/{validated_id}/lineups",
            headers=headers,
        )

    @staticmethod
    def parse_lineups(payload: object) -> list[LineupDTO]:
        root = _as_object(payload, "payload")
        rows: list[LineupDTO] = []
        for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
            if key not in root:
                raise AdapterSchemaError(f"missing {key}")
            team = _as_object(root[key], key)
            rows.append(
                LineupDTO(
                    team_side=side,
                    lineup_type=LineupType.STANDARD,
                    formation=_optional_string(team.get("formation"), f"{key}.formation"),
                    starters=_players(
                        team.get("startingXI"), f"{key}.startingXI", allow_empty=False
                    ),
                    subs=_players(
                        team.get("substitutes", []), f"{key}.substitutes", allow_empty=True
                    ),
                    inferred=False,
                )
            )
        return rows
