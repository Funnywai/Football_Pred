import csv
import io
from datetime import UTC, date, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.providers.base import FixtureRecord, LeagueRecord, OddsRecord, ResultRecord

DIVISIONS: dict[str, str] = {
    "E0": "EPL",
    "SP1": "LALIGA",
    "I1": "SERIEA",
    "D1": "BUNDESLIGA",
    "F1": "LIGUE1",
}

# bookmaker -> (open_home, open_draw, open_away, close_home, close_draw, close_away)
BOOKMAKERS: dict[str, tuple[str, str, str, str, str, str]] = {
    "B365": ("B365H", "B365D", "B365A", "B365CH", "B365CD", "B365CA"),
    "PP": ("PPH", "PPD", "PPA", "PPCH", "PPCD", "PPCA"),
    "Max": ("MaxH", "MaxD", "MaxA", "MaxCH", "MaxCD", "MaxCA"),
    "Avg": ("AvgH", "AvgD", "AvgA", "AvgCH", "AvgCD", "AvgCA"),
}


class HistoricalMatchRecord(BaseModel):
    division: str
    league_code: str
    season_label: str
    match_date: date
    kickoff_time: datetime
    home_team_name: str
    away_team_name: str
    home_score: int
    away_score: int
    odds: dict[str, dict[str, list[float | None]]] = Field(default_factory=dict)


def season_code(year: int) -> str:
    return f"{year % 100:02d}{(year + 1) % 100:02d}"


def _season_start_year(value: date) -> int:
    return value.year if value.month >= 7 else value.year - 1


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    number = _to_float(value)
    return None if number is None else int(number)


def _parse_date(value: str) -> date:
    text = value.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised football-data date: {value!r}")


def _parse_kickoff(match_date: date, time_text: str | None) -> datetime:
    text = (time_text or "").strip()
    hour, minute = 12, 0
    if ":" in text:
        parts = text.split(":")
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            hour, minute = 12, 0
    return datetime(match_date.year, match_date.month, match_date.day, hour, minute, tzinfo=UTC)


def _parse_odds(row: dict[str, str]) -> dict[str, dict[str, list[float | None]]]:
    odds: dict[str, dict[str, list[float | None]]] = {}
    for bookmaker, (oh, od, oa, ch, cd, ca) in BOOKMAKERS.items():
        opening = [_to_float(row.get(oh)), _to_float(row.get(od)), _to_float(row.get(oa))]
        closing = [_to_float(row.get(ch)), _to_float(row.get(cd)), _to_float(row.get(ca))]
        if any(v is not None for v in opening) or any(v is not None for v in closing):
            odds[bookmaker] = {"open": opening, "close": closing}
    return odds


class FootballDataProvider:
    """Downloads football-data.co.uk season CSVs. Big-5 divisions only (UCL is absent)."""

    name = "football_data"

    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        divisions: list[str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._divisions = divisions or list(DIVISIONS)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_leagues(self) -> list[LeagueRecord]:
        return []

    async def fetch_fixtures(self, date_from: date, date_to: date) -> list[FixtureRecord]:
        return []

    async def fetch_odds(self, fixtures: list[FixtureRecord]) -> list[OddsRecord]:
        return []

    async def fetch_results(self, date_from: date, date_to: date) -> list[ResultRecord]:
        season = season_code(_season_start_year(date_from))
        records: list[ResultRecord] = []
        for division in self._divisions:
            for row in await self._download(season, division):
                match_date = _parse_date(row["Date"])
                if not (date_from <= match_date <= date_to):
                    continue
                home_score = _to_int(row.get("FTHG"))
                away_score = _to_int(row.get("FTAG"))
                if home_score is None or away_score is None:
                    continue
                records.append(
                    ResultRecord(
                        match_date=match_date,
                        home_team_name=row["HomeTeam"].strip(),
                        away_team_name=row["AwayTeam"].strip(),
                        home_score=home_score,
                        away_score=away_score,
                        ttl_corner=None,
                        source=self.name,
                        confirmed=False,
                        payout_confirmed=False,
                        raw=row,
                    )
                )
        return records

    async def fetch_historical(
        self, season_start_year: int, divisions: list[str] | None = None
    ) -> list[HistoricalMatchRecord]:
        season = season_code(season_start_year)
        label = f"{season_start_year}/{(season_start_year + 1) % 100:02d}"
        records: list[HistoricalMatchRecord] = []
        for division in divisions or self._divisions:
            for row in await self._download(season, division):
                home_score = _to_int(row.get("FTHG"))
                away_score = _to_int(row.get("FTAG"))
                if home_score is None or away_score is None:
                    continue
                match_date = _parse_date(row["Date"])
                records.append(
                    HistoricalMatchRecord(
                        division=division,
                        league_code=DIVISIONS.get(division, division),
                        season_label=label,
                        match_date=match_date,
                        kickoff_time=_parse_kickoff(match_date, row.get("Time")),
                        home_team_name=row["HomeTeam"].strip(),
                        away_team_name=row["AwayTeam"].strip(),
                        home_score=home_score,
                        away_score=away_score,
                        odds=_parse_odds(row),
                    )
                )
        return records

    async def _download(self, season: str, division: str) -> list[dict[str, Any]]:
        url = f"{self._base_url}/mmz4281/{season}/{division}.csv"
        response = await self._client.get(url)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        text = response.content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))
