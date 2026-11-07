from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    CoverageGapError,
    FetchResult,
    MinIntervalRateLimiter,
)

LEAGUE_SLUGS = {
    "EPL": "EPL",
    "LALIGA": "La_liga",
    "BUNDESLIGA": "Bundesliga",
    "SERIEA": "Serie_A",
    "LIGUE1": "Ligue_1",
}

_JS_ESCAPE = re.compile(r"\\x[0-9a-fA-F]{2}|\\u[0-9a-fA-F]{4}|\\.", re.DOTALL)


def _decode_hex_escape(token: str) -> str:
    digits = token[2:]
    return chr(int(digits, 16))


def _decode_js_string(raw: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith(("\\x", "\\u")):
            return _decode_hex_escape(token)
        mapping = {"\\'": "'", '\\"': '"', "\\\\": "\\", "\\n": "\n", "\\t": "\t"}
        return mapping.get(token, token)

    return _JS_ESCAPE.sub(replace, raw)


def _extract_js_payload(html: str, variable: str) -> dict[str, object]:
    pattern = re.compile(
        rf"var\s+{re.escape(variable)}\s*=\s*JSON\.parse\('(.*?)'\);",
        re.DOTALL,
    )
    match = pattern.search(html)
    if match is None:
        raise AdapterSchemaError(f"missing {variable} payload")
    decoded = _decode_js_string(match.group(1))
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise AdapterSchemaError(f"invalid {variable} JSON") from exc
    if not isinstance(payload, dict):
        raise AdapterSchemaError(f"{variable} payload must be an object")
    return payload


@dataclass(frozen=True)
class UnderstatTeamSeason:
    understat_team_id: str
    team_name: str
    matches: int
    goals: int
    xg: Decimal
    xga: Decimal
    npxg: Decimal
    ppda: Decimal
    deep: int


class UnderstatAdapter(BaseAdapter):
    name = "understat"
    tos_risk = "medium"
    schema_version = "html-v1"

    def __init__(
        self,
        base_url: str = "https://understat.com",
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else MinIntervalRateLimiter(5.0),
        )
        self._base_url = base_url.rstrip("/")

    def fetch_league(self, competition_code: str, season_start_year: int) -> FetchResult:
        slug = LEAGUE_SLUGS.get(competition_code)
        if slug is None:
            raise CoverageGapError(f"understat has no coverage for {competition_code}")
        return self._get_text(f"{self._base_url}/league/{slug}/{season_start_year}")

    @staticmethod
    def parse_team_seasons(html: str) -> list[UnderstatTeamSeason]:
        teams = _extract_js_payload(html, "teamsData")
        rows: list[UnderstatTeamSeason] = []
        for team in teams.values():
            if not isinstance(team, dict):
                raise AdapterSchemaError("teamsData entry must be an object")
            history = team.get("history") or []
            if not isinstance(history, list):
                raise AdapterSchemaError(
                    f"teamsData history for team {team.get('id')} must be a list"
                )
            if not history:
                continue
            try:
                xg = sum(
                    (Decimal(str(entry.get("xG") or 0)) for entry in history),
                    Decimal(0),
                )
                xga = sum(
                    (Decimal(str(entry.get("xGA") or 0)) for entry in history),
                    Decimal(0),
                )
                npxg = sum(
                    (Decimal(str(entry.get("npxG") or 0)) for entry in history),
                    Decimal(0),
                )
                goals = sum(int(entry.get("scored") or 0) for entry in history)
                deep = sum(int(entry.get("deep") or 0) for entry in history)
                att_total = Decimal(0)
                def_total = Decimal(0)
                for entry in history:
                    ppda_entry = entry.get("ppda")
                    if not isinstance(ppda_entry, dict):
                        continue
                    att_value = ppda_entry.get("att")
                    def_value = ppda_entry.get("def")
                    if att_value is None or def_value is None:
                        continue
                    att_total += Decimal(str(att_value))
                    def_total += Decimal(str(def_value))
            except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
                raise AdapterSchemaError(
                    f"invalid teamsData history for team {team.get('id')}: {exc}"
                ) from exc
            ppda = att_total / def_total if def_total > 0 else Decimal(0)
            rows.append(
                UnderstatTeamSeason(
                    understat_team_id=str(team.get("id")),
                    team_name=str(team.get("title")),
                    matches=len(history),
                    goals=goals,
                    xg=xg,
                    xga=xga,
                    npxg=npxg,
                    ppda=ppda,
                    deep=deep,
                )
            )
        return rows
