from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.providers.base import FixtureRecord, LeagueRecord, OddsRecord, ResultRecord
from app.providers.hkjc.client import HkjcGraphQLClient
from app.providers.hkjc.queries import (
    FOOTBALL_MATCHES_QUERY,
    HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY,
    HISTORIC_FOOTBALL_MATCHES_QUERY,
    ODDS_TYPE_BATCHES,
)

DATE_FORMAT = "%Y-%m-%d"
FIXTURE_ODDS_TYPES = ["HAD"]
RESULT_PAGE_SPAN = 20
MAX_RESULT_PAGES = 25
GOAL_STAGE_RESULT_TYPE = 1

_STATUS_MAP = {
    "SCHEDULED": "scheduled",
    "PREEVENT": "scheduled",
    "LIVE": "live",
    "FIRSTHALF": "live",
    "SECONDHALF": "live",
    "MATCHENDED": "finished",
    "INPLAYMATCHENDED": "finished",
    "FINISHED": "finished",
    "POSTPONED": "postponed",
    "ABANDONED": "abandoned",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
}


def _parse_datetime(value: str) -> datetime:
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Unrecognised HKJC datetime: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _map_status(value: str | None) -> str:
    if not value:
        return "scheduled"
    return _STATUS_MAP.get(value.upper(), "scheduled")


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


class HkjcProvider:
    """HKJC GraphQL provider. All HKJC specifics live behind this class."""

    name = "hkjc"

    def __init__(self, client: HkjcGraphQLClient, tourn_ids: list[str] | None = None) -> None:
        self._client = client
        self._tourn_ids = tourn_ids

    async def fetch_leagues(self) -> list[LeagueRecord]:
        return []

    async def fetch_fixtures(self, date_from: date, date_to: date) -> list[FixtureRecord]:
        """Fetch the fixture list, then keep only ``date_from..date_to``.

        HKJC rejects a date window or pagination on this field (a date range or
        ``startIndex``/``endIndex`` yields an empty list or "Invalid queration
        arguments"), so the request omits both — like the frontend does — and the
        window is applied client-side on ``matchDate``.
        """
        variables = {
            "startDate": None,
            "endDate": None,
            "matchIds": None,
            "tournIds": self._tourn_ids,
            "fbOddsTypes": FIXTURE_ODDS_TYPES,
            "fbOddsTypesM": FIXTURE_ODDS_TYPES,
            "inplayOnly": False,
            "featuredMatchesOnly": False,
            "frontEndIds": None,
            "earlySettlementOnly": False,
            "showAllMatch": False,
            "startIndex": None,
            "endIndex": None,
        }
        data = await self._client.execute(FOOTBALL_MATCHES_QUERY, variables)
        lower, upper = date_from.isoformat(), date_to.isoformat()
        return [
            self._to_fixture(item)
            for item in data.get("matches") or []
            if lower <= str(item.get("matchDate"))[:10] <= upper
        ]

    def _to_fixture(self, item: dict[str, Any]) -> FixtureRecord:
        tournament = item.get("tournament") or {}
        home = item.get("homeTeam") or {}
        away = item.get("awayTeam") or {}
        venue = item.get("venue") or {}
        return FixtureRecord(
            source=self.name,
            league_name=tournament.get("name_en") or tournament.get("code") or "Unknown",
            hkjc_tourn_id=_optional_str(tournament.get("id")),
            hkjc_match_id=_optional_str(item.get("id")),
            kickoff_time=_parse_datetime(item["kickOffTime"]),
            status=_map_status(item.get("status")),
            home_team_name_en=home.get("name_en") or "",
            home_team_name_ch=home.get("name_ch"),
            home_team_hkjc_id=_optional_str(home.get("id")),
            away_team_name_en=away.get("name_en") or "",
            away_team_name_ch=away.get("name_ch"),
            away_team_hkjc_id=_optional_str(away.get("id")),
            venue=venue.get("name_en"),
            round=None,
            raw=item,
        )

    async def fetch_odds(self, fixtures: list[FixtureRecord]) -> list[OddsRecord]:
        match_ids = [f.hkjc_match_id for f in fixtures if f.hkjc_match_id]
        if not match_ids:
            return []
        captured_at = datetime.now(UTC)
        records: list[OddsRecord] = []
        for batch in ODDS_TYPE_BATCHES:
            variables = {
                "startDate": None,
                "endDate": None,
                "matchIds": match_ids,
                "tournIds": None,
                "fbOddsTypes": batch,
                "fbOddsTypesM": batch,
                "inplayOnly": False,
                "featuredMatchesOnly": False,
                "frontEndIds": None,
                "earlySettlementOnly": False,
                "showAllMatch": True,
            }
            data = await self._client.execute(FOOTBALL_MATCHES_QUERY, variables)
            for item in data.get("matches") or []:
                match_id = _optional_str(item.get("id"))
                if match_id is None:
                    continue
                for pool in item.get("foPools") or []:
                    records.append(
                        OddsRecord(
                            match_hkjc_id=match_id,
                            odds_type=pool["oddsType"],
                            inplay=bool(pool.get("inplay")),
                            captured_at=captured_at,
                            payload=pool,
                        )
                    )
        return records

    async def fetch_results(self, date_from: date, date_to: date) -> list[ResultRecord]:
        """One day per call: HKJC returns an empty list for a multi-day window."""
        records: list[ResultRecord] = []
        seen: set[str | None] = set()
        day = date_from
        while day <= date_to:
            for record in await self._fetch_results_for_day(day):
                if record.match_hkjc_id in seen:
                    continue
                seen.add(record.match_hkjc_id)
                records.append(record)
            day += timedelta(days=1)
        return records

    async def _fetch_results_for_day(self, day: date) -> list[ResultRecord]:
        """A page span wider than ``RESULT_PAGE_SPAN`` also comes back empty."""
        stamp = day.strftime(DATE_FORMAT)
        records: list[ResultRecord] = []
        start = 0
        for _ in range(MAX_RESULT_PAGES):
            data = await self._client.execute(
                HISTORIC_FOOTBALL_MATCHES_QUERY,
                {
                    "startDate": stamp,
                    "endDate": stamp,
                    "startIndex": start,
                    "endIndex": start + RESULT_PAGE_SPAN,
                    "teamId": None,
                },
            )
            items = data.get("matches") or []
            if not items:
                break
            for item in items:
                record = self._to_result(item)
                if record is not None:
                    records.append(record)
            start += RESULT_PAGE_SPAN
        return records

    def _to_result(self, item: dict[str, Any]) -> ResultRecord | None:
        """Settled full-time score, or None when HKJC has not settled the match.

        ``results`` is a per-stage/pool log, not a score: ``resultType`` 1 is the goal
        stage (its highest ``sequence`` entry IS the final score — cross-checked against
        football-data's FT score for two EPL matches), 2 is the corner progression and 4
        is another pool. A score is taken only from a match HKJC marks as ended
        (``MATCHENDED``/``INPLAYMATCHENDED``/``FINISHED`` — the latter two carry the true
        final score too); anything else is left to the football-data fallback rather than
        risking a wrong score.
        """
        if _map_status(item.get("status")) != "finished":
            return None
        entries = [
            entry
            for entry in item.get("results") or []
            if entry.get("resultType") == GOAL_STAGE_RESULT_TYPE
        ]
        if not entries:
            return None
        settled = max(entries, key=lambda entry: entry.get("sequence") or 0)
        ttl = settled.get("ttlCornerResult")
        corners = int(ttl) if ttl is not None else -1
        return ResultRecord(
            match_hkjc_id=_optional_str(item.get("id")),
            home_score=int(settled["homeResult"]),
            away_score=int(settled["awayResult"]),
            ttl_corner=corners if corners >= 0 else None,
            source=self.name,
            confirmed=True,
            payout_confirmed=bool(settled.get("payoutConfirmed")),
            raw=item,
        )

    async def fetch_result_details(self, match_id: str) -> dict[str, Any]:
        variables = {
            "matchId": match_id,
            "fbOddsTypes": ["HAD", "HDC", "HIL", "CRS", "HHA", "CHD", "CHL"],
        }
        data = await self._client.execute(HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY, variables)
        return data.get("matches") or {}
