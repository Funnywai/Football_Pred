from datetime import date, time, timedelta
from decimal import Decimal

import httpx
import pytest
import respx

from packages.adapters.base import (
    AdapterHTTPError,
    AdapterSchemaError,
    BaseAdapter,
    CoverageGapError,
    MinIntervalRateLimiter,
    hash_text,
)
from packages.adapters.football_data_co_uk import (
    LEAGUE_FILE_CODES,
    FootballDataCoUkAdapter,
    season_path,
)

CSV_TEXT = """Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,PSH,PSD,PSA
15/08/2026,14:00,Arsenal,Chelsea,2,1,H,2.05,3.40,3.80,2.10,3.50,3.90
16/08/2026,,Liverpool,Everton,0,0,D,2.20,3.30,3.50,,,
"""

NO_LIMIT = MinIntervalRateLimiter(0.0)


def _csv_with(first_row: str) -> str:
    header = (
        "Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,"
        "B365H,B365D,B365A,PSH,PSD,PSA"
    )
    return f"{header}\n{first_row}\n"


def test_season_path_uses_two_digit_years():
    assert season_path(2025) == "2526"


def test_league_file_codes_cover_the_five_domestic_leagues_only():
    assert LEAGUE_FILE_CODES == {
        "EPL": "E0",
        "LALIGA": "SP1",
        "BUNDESLIGA": "D1",
        "SERIEA": "I1",
        "LIGUE1": "F1",
    }
    assert "UCL" not in LEAGUE_FILE_CODES


def test_parse_csv_reads_scores_and_odds_as_decimal():
    rows = FootballDataCoUkAdapter.parse_csv(CSV_TEXT, "EPL", 2025)
    assert len(rows) == 2
    first = rows[0]
    assert first.played_on == date(2026, 8, 15)
    assert first.kickoff_time == time(14, 0)
    assert first.home_goals_90 == 2
    assert first.away_goals_90 == 1
    assert first.result == "H"
    assert first.b365_home == Decimal("2.05")
    assert first.ps_away == Decimal("3.90")
    assert rows[1].kickoff_time is None
    assert rows[1].ps_home is None
    assert rows[1].ps_draw is None
    assert rows[1].ps_away is None


def test_parse_csv_accepts_two_digit_year():
    text = _csv_with("15/08/26,14:00,Arsenal,Chelsea,2,1,H,2.05,3.40,3.80,2.10,3.50,3.90")

    rows = FootballDataCoUkAdapter.parse_csv(text, "EPL", 2025)

    assert rows[0].played_on == date(2026, 8, 15)


def test_football_data_co_uk_is_marked_historical():
    assert FootballDataCoUkAdapter.data_kind == "historical"
    assert FootballDataCoUkAdapter.is_live is False
    assert BaseAdapter.data_kind == "live"
    assert BaseAdapter.is_live is True


def test_parse_csv_keeps_competition_and_season_on_every_row():
    rows = FootballDataCoUkAdapter.parse_csv(CSV_TEXT, "EPL", 2025)

    assert {row.competition_code for row in rows} == {"EPL"}
    assert {row.season_start_year for row in rows} == {2025}


def test_parse_csv_handles_utf8_bom_and_padded_headers():
    text = (
        "\ufeff Date , Time , HomeTeam , AwayTeam , FTHG , FTAG , FTR , "
        "B365H , B365D , B365A , PSH , PSD , PSA \n"
        "15/08/2026,14:00,Arsenal,Chelsea,2,1,H,2.05,3.40,3.80,2.10,3.50,3.90\n"
    )

    rows = FootballDataCoUkAdapter.parse_csv(text, "EPL", 2025)

    assert len(rows) == 1
    assert rows[0].home_team == "Arsenal"
    assert rows[0].b365_home == Decimal("2.05")


def test_parse_csv_skips_blank_rows():
    rows = FootballDataCoUkAdapter.parse_csv(f"{CSV_TEXT}\n\n", "EPL", 2025)

    assert len(rows) == 2


def test_parse_csv_rejects_missing_required_column():
    text = "Date,Time,HomeTeam,AwayTeam,FTAG,FTR\n15/08/2026,14:00,Arsenal,Chelsea,1,H\n"

    with pytest.raises(AdapterSchemaError, match="FTHG"):
        FootballDataCoUkAdapter.parse_csv(text, "EPL", 2025)


def test_parse_csv_rejects_malformed_date():
    text = _csv_with("15-08-2026,14:00,Arsenal,Chelsea,2,1,H,2.05,3.40,3.80,2.10,3.50,3.90")

    with pytest.raises(AdapterSchemaError, match="invalid date"):
        FootballDataCoUkAdapter.parse_csv(text, "EPL", 2025)


def test_parse_csv_rejects_rows_with_data_but_no_date():
    text = _csv_with(",14:00,Arsenal,Chelsea,2,1,H,2.05,3.40,3.80,2.10,3.50,3.90")

    with pytest.raises(AdapterSchemaError, match="Date"):
        FootballDataCoUkAdapter.parse_csv(text, "EPL", 2025)


def test_parse_csv_rejects_malformed_kickoff_time():
    text = _csv_with("15/08/2026,2pm,Arsenal,Chelsea,2,1,H,2.05,3.40,3.80,2.10,3.50,3.90")

    with pytest.raises(AdapterSchemaError, match="kickoff time"):
        FootballDataCoUkAdapter.parse_csv(text, "EPL", 2025)


def test_parse_csv_rejects_missing_goals():
    text = _csv_with("15/08/2026,14:00,Arsenal,Chelsea,,1,H,2.05,3.40,3.80,2.10,3.50,3.90")

    with pytest.raises(AdapterSchemaError, match="FTHG"):
        FootballDataCoUkAdapter.parse_csv(text, "EPL", 2025)


def test_parse_csv_rejects_non_integer_goals():
    text = _csv_with("15/08/2026,14:00,Arsenal,Chelsea,two,1,H,2.05,3.40,3.80,2.10,3.50,3.90")

    with pytest.raises(AdapterSchemaError, match="FTHG"):
        FootballDataCoUkAdapter.parse_csv(text, "EPL", 2025)


def test_parse_csv_rejects_negative_goals():
    text = _csv_with("15/08/2026,14:00,Arsenal,Chelsea,-1,1,H,2.05,3.40,3.80,2.10,3.50,3.90")

    with pytest.raises(AdapterSchemaError, match="FTHG"):
        FootballDataCoUkAdapter.parse_csv(text, "EPL", 2025)


def test_parse_csv_rejects_unknown_result_code():
    text = _csv_with("15/08/2026,14:00,Arsenal,Chelsea,2,1,Z,2.05,3.40,3.80,2.10,3.50,3.90")

    with pytest.raises(AdapterSchemaError, match="result"):
        FootballDataCoUkAdapter.parse_csv(text, "EPL", 2025)


def test_parse_csv_rejects_non_numeric_odds():
    text = _csv_with("15/08/2026,14:00,Arsenal,Chelsea,2,1,H,abc,3.40,3.80,2.10,3.50,3.90")

    with pytest.raises(AdapterSchemaError, match="B365H"):
        FootballDataCoUkAdapter.parse_csv(text, "EPL", 2025)


def test_parse_csv_rejects_non_finite_odds():
    text = _csv_with("15/08/2026,14:00,Arsenal,Chelsea,2,1,H,NaN,3.40,3.80,2.10,3.50,3.90")

    with pytest.raises(AdapterSchemaError, match="B365H"):
        FootballDataCoUkAdapter.parse_csv(text, "EPL", 2025)


def test_adapter_is_marked_historical_and_not_live():
    assert FootballDataCoUkAdapter.name == "football-data.co.uk"
    assert FootballDataCoUkAdapter.schema_version == "csv-v1"
    assert FootballDataCoUkAdapter.data_kind == "historical"
    assert FootballDataCoUkAdapter.is_live is False


@respx.mock
def test_fetch_league_csv_uses_expected_url_and_records_provenance():
    url = "https://www.football-data.co.uk/mmz4281/2526/E0.csv"
    route = respx.get(url).mock(return_value=httpx.Response(200, text=CSV_TEXT))
    adapter = FootballDataCoUkAdapter(limiter=NO_LIMIT)
    try:
        result = adapter.fetch_league_csv("EPL", 2025)
    finally:
        adapter.close()
    assert route.called
    assert result.source_name == "football-data.co.uk"
    assert result.source_url == url
    assert result.http_status == 200
    assert result.schema_version == "csv-v1"
    assert result.payload == CSV_TEXT
    assert result.payload_hash == hash_text(CSV_TEXT)
    assert result.raw_text == CSV_TEXT
    assert result.fetched_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("competition_code", "file_code"),
    [("EPL", "E0"), ("LALIGA", "SP1"), ("BUNDESLIGA", "D1"), ("SERIEA", "I1"), ("LIGUE1", "F1")],
)
@respx.mock
def test_fetch_league_csv_maps_each_league_to_its_file_code(competition_code, file_code):
    url = f"https://www.football-data.co.uk/mmz4281/2526/{file_code}.csv"
    route = respx.get(url).mock(return_value=httpx.Response(200, text=CSV_TEXT))

    with FootballDataCoUkAdapter(limiter=NO_LIMIT) as adapter:
        result = adapter.fetch_league_csv(competition_code, 2025)

    assert route.called
    assert result.source_url == url


@respx.mock
def test_ucl_raises_coverage_gap_before_http_call():
    route = respx.get(url__startswith="https://www.football-data.co.uk/").mock(
        return_value=httpx.Response(200, text=CSV_TEXT)
    )

    with (
        FootballDataCoUkAdapter(limiter=NO_LIMIT) as adapter,
        pytest.raises(CoverageGapError, match="UCL"),
    ):
        adapter.fetch_league_csv("UCL", 2025)

    assert not route.called


@respx.mock
def test_fetch_league_csv_500_raises_http_error():
    respx.get("https://www.football-data.co.uk/mmz4281/2526/E0.csv").mock(
        return_value=httpx.Response(500)
    )

    with (
        FootballDataCoUkAdapter(limiter=NO_LIMIT) as adapter,
        pytest.raises(AdapterHTTPError, match="returned 500"),
    ):
        adapter.fetch_league_csv("EPL", 2025)


@respx.mock
def test_fetch_league_csv_follows_redirect_to_final_csv():
    start = "https://www.football-data.co.uk/mmz4281/2526/E0.csv"
    final = "https://www.football-data.co.uk/mmz4281/2526/E0-final.csv"
    redirect = respx.get(start).mock(
        return_value=httpx.Response(302, headers={"Location": final})
    )
    target = respx.get(final).mock(
        return_value=httpx.Response(200, text=CSV_TEXT)
    )

    with FootballDataCoUkAdapter(limiter=NO_LIMIT) as adapter:
        result = adapter.fetch_league_csv("EPL", 2025)

    assert redirect.called
    assert target.called
    assert result.http_status == 200
    assert result.raw_text == CSV_TEXT
    assert result.payload == CSV_TEXT
    assert result.source_url == final


@respx.mock
def test_fetch_league_csv_raises_on_unfollowable_redirect():
    url = "https://www.football-data.co.uk/mmz4281/2526/E0.csv"
    respx.get(url).mock(return_value=httpx.Response(302))

    with (
        FootballDataCoUkAdapter(limiter=NO_LIMIT) as adapter,
        pytest.raises(AdapterHTTPError, match="returned 302"),
    ):
        adapter.fetch_league_csv("EPL", 2025)
