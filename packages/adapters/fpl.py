from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, cast

import httpx

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
)
from packages.domain.enums import AvailabilityStatus

COMPETITION_CODES = frozenset({"EPL"})

_FPL_STATUS = {
    "a": AvailabilityStatus.AVAILABLE,
    "d": AvailabilityStatus.DOUBTFUL,
    "i": AvailabilityStatus.INJURY,
    "s": AvailabilityStatus.SUSPENSION,
    "u": AvailabilityStatus.DOUBTFUL,
}

_DEFAULT_LIMITER = MinIntervalRateLimiter(10.0)


@dataclass(frozen=True)
class FplPlayerStatus:
    fpl_id: int
    web_name: str
    team_name: str
    status: AvailabilityStatus
    provider_status: str
    news: str | None
    chance_of_playing: int | None


def _as_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AdapterSchemaError(f"{label} must be an object")
    return cast("dict[str, object]", value)


def _as_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise AdapterSchemaError(f"{label} must be a list")
    return cast("list[object]", value)


def _required_list(obj: dict[str, object], key: str) -> list[object]:
    if key not in obj:
        raise AdapterSchemaError(f"{key} must be present as a list")
    return _as_list(obj[key], key)


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise AdapterSchemaError(f"{label} id must be a positive integer")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise AdapterSchemaError(f"{label} id must be a positive integer") from exc
    if parsed <= 0:
        raise AdapterSchemaError(f"{label} id must be a positive integer")
    return parsed


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterSchemaError(f"{label} must be a non-empty string")
    return value.strip()


def _news(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterSchemaError(f"{label}.news must be a string")
    return value if value.strip() else None


def _chance_of_playing(value: object, fpl_id: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise AdapterSchemaError(
            f"invalid chance_of_playing_next_round {value!r} for element {fpl_id}"
        )
    return value


class FplAdapter(BaseAdapter):
    name: ClassVar[str] = "fpl"
    tos_risk: ClassVar[str] = "low"
    schema_version: ClassVar[str] = "v1"
    competition_codes: ClassVar[frozenset[str]] = COMPETITION_CODES

    def __init__(
        self,
        base_url: str = "https://fantasy.premierleague.com/api",
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

    def fetch_bootstrap(self) -> FetchResult:
        return self._get_json(f"{self._base_url}/bootstrap-static/")

    @staticmethod
    def parse_availability(payload: object) -> list[FplPlayerStatus]:
        root = _as_object(payload, "payload")
        teams: dict[int, str] = {}
        for index, raw in enumerate(_required_list(root, "teams")):
            label = f"teams[{index}]"
            team = _as_object(raw, label)
            team_id = _positive_int(team.get("id"), f"{label}.id")
            if team_id in teams:
                raise AdapterSchemaError(f"duplicate FPL team id {team_id}")
            teams[team_id] = _required_string(team.get("name"), f"{label}.name")
        rows: list[FplPlayerStatus] = []
        for index, raw in enumerate(_required_list(root, "elements")):
            label = f"elements[{index}]"
            element = _as_object(raw, label)
            fpl_id = _positive_int(element.get("id"), f"{label}.id")
            raw_status = element.get("status")
            if not isinstance(raw_status, str) or not raw_status.strip():
                raise AdapterSchemaError(f"{label}.status must be a non-empty string")
            status = _FPL_STATUS.get(raw_status.lower())
            if status is None:
                raise AdapterSchemaError(f"unknown FPL status {raw_status!r}")
            team_id = _positive_int(element.get("team"), f"{label}.team")
            if team_id not in teams:
                raise AdapterSchemaError(
                    f"unknown FPL team {team_id} for element {fpl_id}"
                )
            rows.append(
                FplPlayerStatus(
                    fpl_id=fpl_id,
                    web_name=_required_string(element.get("web_name"), f"{label}.web_name"),
                    team_name=teams[team_id],
                    status=status,
                    provider_status=raw_status,
                    news=_news(element.get("news"), label),
                    chance_of_playing=_chance_of_playing(
                        element.get("chance_of_playing_next_round"), fpl_id
                    ),
                )
            )
        return rows
