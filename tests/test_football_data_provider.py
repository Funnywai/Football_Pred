from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from app.providers.football_data.provider import FootballDataProvider, season_code

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://www.football-data.co.uk"


def _client() -> httpx.AsyncClient:
    csv_bytes = (FIXTURES / "football_data_E0_2627.csv").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/E0.csv"):
            return httpx.Response(200, content=csv_bytes)
        return httpx.Response(404, text="not found")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_season_code():
    assert season_code(2026) == "2627"
    assert season_code(2010) == "1011"
    assert season_code(1999) == "9900"


async def test_fetch_results_parses_and_filters_by_date():
    provider = FootballDataProvider(BASE_URL, client=_client(), divisions=["E0"])
    records = await provider.fetch_results(date(2026, 8, 21), date(2026, 8, 22))
    assert len(records) == 3
    first = records[0]
    assert first.match_date == date(2026, 8, 21)
    assert first.home_team_name == "Arsenal"
    assert first.away_team_name == "Coventry"
    assert first.home_score == 3
    assert first.away_score == 0
    assert first.source == "football_data"
    assert first.confirmed is False
    assert first.ttl_corner is None
    await provider.aclose()


async def test_fetch_results_skips_unplayed_rows():
    provider = FootballDataProvider(BASE_URL, client=_client(), divisions=["E0"])
    records = await provider.fetch_results(date(2026, 8, 22), date(2026, 8, 22))
    assert all(r.home_team_name != "Man City" for r in records)
    await provider.aclose()


async def test_fetch_results_uses_expected_url():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=(FIXTURES / "football_data_E0_2627.csv").read_bytes())

    provider = FootballDataProvider(
        BASE_URL, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), divisions=["E0"]
    )
    await provider.fetch_results(date(2026, 8, 21), date(2026, 8, 21))
    assert seen == ["https://www.football-data.co.uk/mmz4281/2627/E0.csv"]
    await provider.aclose()


async def test_fetch_historical_returns_odds():
    provider = FootballDataProvider(BASE_URL, client=_client(), divisions=["E0"])
    records = await provider.fetch_historical(2026)
    assert len(records) == 3
    first = records[0]
    assert first.league_code == "EPL"
    assert first.season_label == "2026/27"
    assert first.odds["B365"]["open"] == [1.2, 7.0, 13.0]
    assert first.odds["B365"]["close"] == [1.18, 7.5, 13.0]
    assert first.kickoff_time == datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
    await provider.aclose()


async def test_fetch_historical_parses_pinnacle():
    csv_text = (
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,"
        "PSH,PSD,PSA,PSCH,PSCD,PSCA\n"
        "E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H,2.1,3.5,3.9,2.15,3.4,4.0\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=csv_text.encode())

    provider = FootballDataProvider(
        BASE_URL, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), divisions=["E0"]
    )
    records = await provider.fetch_historical(2026)
    assert len(records) == 1
    assert "PS" in records[0].odds
    assert records[0].odds["PS"]["open"] == [2.1, 3.5, 3.9]
    assert records[0].odds["PS"]["close"] == [2.15, 3.4, 4.0]
    await provider.aclose()


async def test_fetch_historical_parses_shot_stats():
    csv_text = (
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,"
        "HS,AS,HST,AST,HC,AC,HxG,AxG\n"
        "E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H,18,7,8,2,9,3,2.45,0.62\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=csv_text.encode())

    provider = FootballDataProvider(
        BASE_URL, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), divisions=["E0"]
    )
    records = await provider.fetch_historical(2026)
    assert len(records) == 1
    record = records[0]
    assert record.home_shots == 18
    assert record.away_shots == 7
    assert record.home_sot == 8
    assert record.away_sot == 2
    assert record.home_corners == 9
    assert record.away_corners == 3
    assert record.home_xg == 2.45
    assert record.away_xg == 0.62
    await provider.aclose()


async def test_fetch_historical_missing_shot_stats_are_none():
    csv_text = (
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=csv_text.encode())

    provider = FootballDataProvider(
        BASE_URL, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), divisions=["E0"]
    )
    records = await provider.fetch_historical(2026)
    record = records[0]
    assert record.home_shots is None
    assert record.away_shots is None
    assert record.home_sot is None
    assert record.away_sot is None
    assert record.home_corners is None
    assert record.away_corners is None
    assert record.home_xg is None
    assert record.away_xg is None
    await provider.aclose()


async def test_fetch_historical_blank_shot_stats_are_none():
    csv_text = (
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,"
        "HS,AS,HST,AST,HC,AC,HxG,AxG\n"
        "E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H,,,,,,,\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=csv_text.encode())

    provider = FootballDataProvider(
        BASE_URL, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), divisions=["E0"]
    )
    records = await provider.fetch_historical(2026)
    record = records[0]
    assert record.home_shots is None
    assert record.away_shots is None
    assert record.home_sot is None
    assert record.away_sot is None
    assert record.home_corners is None
    assert record.away_corners is None
    assert record.home_xg is None
    assert record.away_xg is None
    await provider.aclose()


async def test_fetch_historical_returns_empty_for_missing_division():
    provider = FootballDataProvider(BASE_URL, client=_client(), divisions=["SP1"])
    assert await provider.fetch_historical(2026) == []
    await provider.aclose()


async def test_default_client_follows_upstream_redirect(monkeypatch):
    """Upstream now 302s www.football-data.co.uk -> football-data.co.uk; the default client must follow."""
    csv_bytes = (FIXTURES / "football_data_E0_2627.csv").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.football-data.co.uk":
            return httpx.Response(
                302, headers={"Location": f"https://football-data.co.uk{request.url.path}"}
            )
        return httpx.Response(200, content=csv_bytes)

    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    provider = FootballDataProvider(BASE_URL, divisions=["E0"])
    try:
        records = await provider.fetch_historical(2026)
    finally:
        await provider.aclose()
    assert len(records) == 3


@pytest.mark.live
async def test_live_football_data_smoke():
    provider = FootballDataProvider(BASE_URL, divisions=["E0"])
    try:
        records = await provider.fetch_results(date(2026, 8, 21), date(2026, 8, 22))
        assert isinstance(records, list)
    finally:
        await provider.aclose()
