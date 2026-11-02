from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    CoverageGapError,
    FetchResult,
    MinIntervalRateLimiter,
)

LEAGUE_FILE_CODES = {
    "EPL": "E0",
    "LALIGA": "SP1",
    "BUNDESLIGA": "D1",
    "SERIEA": "I1",
    "LIGUE1": "F1",
}

BASE_URL = "https://www.football-data.co.uk/mmz4281"

_REQUIRED_COLUMNS = ("Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR")
_RESULT_CODES = frozenset({"H", "D", "A"})


def season_path(season_start_year: int) -> str:
    return f"{str(season_start_year)[2:]}{str(season_start_year + 1)[2:]}"


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _decimal_or_none(value: object, field: str, row_ref: str) -> Decimal | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise AdapterSchemaError(f"invalid {field} value {text!r} at {row_ref}") from exc
    if not parsed.is_finite():
        raise AdapterSchemaError(f"non-finite {field} value {text!r} at {row_ref}")
    return parsed


def _time_or_none(value: object, row_ref: str) -> time | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError as exc:
        raise AdapterSchemaError(f"invalid kickoff time {text!r} at {row_ref}") from exc


def _required_text(value: object, field: str, row_ref: str) -> str:
    text = _clean(value)
    if not text:
        raise AdapterSchemaError(f"missing {field} at {row_ref}")
    return text


def _parse_match_date(value: str, index: int) -> date:
    # football-data.co.uk has used both dd/mm/yy and dd/mm/yyyy over time.
    for date_format in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    raise AdapterSchemaError(f"invalid date {value!r} at CSV row {index}")


def _required_goals(value: object, field: str, row_ref: str) -> int:
    text = _clean(value)
    if not text:
        raise AdapterSchemaError(f"missing {field} at {row_ref}")
    try:
        goals = int(text)
    except ValueError as exc:
        raise AdapterSchemaError(f"invalid {field} value {text!r} at {row_ref}") from exc
    if goals < 0:
        raise AdapterSchemaError(f"invalid {field} value {text!r} at {row_ref}")
    return goals


@dataclass(frozen=True)
class HistoricalMatchRow:
    competition_code: str
    season_start_year: int
    played_on: date
    kickoff_time: time | None
    home_team: str
    away_team: str
    home_goals_90: int
    away_goals_90: int
    result: str
    b365_home: Decimal | None
    b365_draw: Decimal | None
    b365_away: Decimal | None
    ps_home: Decimal | None
    ps_draw: Decimal | None
    ps_away: Decimal | None


class FootballDataCoUkAdapter(BaseAdapter):
    """Historical results and closing odds for backtesting, never a live signal."""

    name = "football-data.co.uk"
    tos_risk = "medium"
    schema_version = "csv-v1"
    data_kind = "historical"
    is_live = False

    def __init__(
        self,
        base_url: str = BASE_URL,
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else MinIntervalRateLimiter(10.0),
        )
        self._base_url = base_url.rstrip("/")

    def fetch_league_csv(
        self,
        competition_code: str,
        season_start_year: int,
    ) -> FetchResult:
        file_code = LEAGUE_FILE_CODES.get(competition_code)
        if file_code is None:
            raise CoverageGapError(
                f"football-data.co.uk has no file mapping for {competition_code}"
            )
        url = f"{self._base_url}/{season_path(season_start_year)}/{file_code}.csv"
        return self._get_text(url, headers={"Accept": "text/csv"})

    @staticmethod
    def parse_csv(
        text: str,
        competition_code: str,
        season_start_year: int,
    ) -> list[HistoricalMatchRow]:
        if not isinstance(text, str):
            raise AdapterSchemaError(
                f"CSV payload must be text, got {type(text).__name__}"
            )
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        if reader.fieldnames is None:
            raise AdapterSchemaError("CSV has no header row")
        reader.fieldnames = [_clean(name) for name in reader.fieldnames]
        missing = [name for name in _REQUIRED_COLUMNS if name not in reader.fieldnames]
        if missing:
            raise AdapterSchemaError(
                f"CSV is missing required column(s): {', '.join(missing)}"
            )

        rows: list[HistoricalMatchRow] = []
        for index, raw in enumerate(reader, start=2):
            if None in raw:
                raise AdapterSchemaError(
                    f"CSV row {index} has more fields than the header"
                )
            played = _clean(raw.get("Date"))
            if not played:
                if any(_clean(value) for value in raw.values()):
                    raise AdapterSchemaError(f"missing Date at CSV row {index}")
                continue
            row_ref = f"CSV row {index} ({played})"
            played_on = _parse_match_date(played, index)
            result = _required_text(raw.get("FTR"), "FTR", row_ref).upper()
            if result not in _RESULT_CODES:
                raise AdapterSchemaError(f"invalid result {result!r} at {row_ref}")
            rows.append(
                HistoricalMatchRow(
                    competition_code=competition_code,
                    season_start_year=season_start_year,
                    played_on=played_on,
                    kickoff_time=_time_or_none(raw.get("Time"), row_ref),
                    home_team=_required_text(raw.get("HomeTeam"), "HomeTeam", row_ref),
                    away_team=_required_text(raw.get("AwayTeam"), "AwayTeam", row_ref),
                    home_goals_90=_required_goals(raw.get("FTHG"), "FTHG", row_ref),
                    away_goals_90=_required_goals(raw.get("FTAG"), "FTAG", row_ref),
                    result=result,
                    b365_home=_decimal_or_none(raw.get("B365H"), "B365H", row_ref),
                    b365_draw=_decimal_or_none(raw.get("B365D"), "B365D", row_ref),
                    b365_away=_decimal_or_none(raw.get("B365A"), "B365A", row_ref),
                    ps_home=_decimal_or_none(raw.get("PSH"), "PSH", row_ref),
                    ps_draw=_decimal_or_none(raw.get("PSD"), "PSD", row_ref),
                    ps_away=_decimal_or_none(raw.get("PSA"), "PSA", row_ref),
                )
            )
        return rows
