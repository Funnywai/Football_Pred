import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.ml.features import hkjc_had_odds, hkjc_hdc_main
from app.ml.labels import parse_handicap_line
from app.providers.hkjc.provider import HkjcProvider

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _FakeClient:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, query: str, variables: dict) -> dict:
        self.calls.append((query, variables))
        return self._responses.pop(0)


async def test_fetch_fixtures_omits_window_and_filters_client_side():
    client = _FakeClient([_load("hkjc_football_matches.json")["data"]])
    provider = HkjcProvider(client, tourn_ids=["50066251"])
    fixtures = await provider.fetch_fixtures(date(2026, 10, 13), date(2026, 10, 13))
    _, variables = client.calls[0]
    assert variables["startDate"] is None
    assert variables["endDate"] is None
    assert variables["startIndex"] is None
    assert variables["endIndex"] is None
    assert variables["tournIds"] == ["50066251"]
    assert [fixture.hkjc_match_id for fixture in fixtures] == [
        "50077704",
        "50077247",
        "50077248",
        "50076784",
        "50076783",
    ]


async def test_fetch_fixtures_parses_real_matches():
    client = _FakeClient([_load("hkjc_football_matches.json")["data"]])
    provider = HkjcProvider(client)
    fixtures = await provider.fetch_fixtures(date(2026, 10, 12), date(2026, 10, 13))
    assert len(fixtures) == 6
    first = fixtures[0]
    assert first.hkjc_match_id == "50077246"
    assert first.league_name == "Finnish Division 1"
    assert first.hkjc_tourn_id == "50066265"
    assert first.home_team_name_en == "VPS Vaasa"
    assert first.home_team_name_ch == "VPS華沙"
    assert first.away_team_name_en == "Gnistan"
    assert first.status == "live"
    assert first.kickoff_time == datetime(2026, 10, 12, 15, 0, tzinfo=UTC)
    assert fixtures[3].status == "scheduled"


async def test_fetch_odds_uses_two_batches_and_parses_pools():
    client = _FakeClient(
        [
            _load("hkjc_football_matches.json")["data"],
            _load("hkjc_match_details.json")["data"],
            {"matches": []},
        ]
    )
    provider = HkjcProvider(client)
    fixtures = await provider.fetch_fixtures(date(2026, 10, 12), date(2026, 10, 13))
    client.calls.clear()
    records = await provider.fetch_odds(fixtures)
    assert client.calls[0][1]["fbOddsTypes"] == ["HAD", "HDC", "HIL", "CRS"]
    assert client.calls[1][1]["fbOddsTypes"] == ["HHA", "CHD", "CHL"]
    assert client.calls[0][1]["fbOddsTypesM"] == ["HAD", "HDC", "HIL", "CRS"]
    assert {record.odds_type for record in records} == {"HAD", "HDC", "HIL", "CRS"}
    assert all(record.captured_at.tzinfo is not None for record in records)
    assert records[0].match_hkjc_id == "50077246"


async def test_fetch_results_ingests_only_settled_matches():
    client = _FakeClient([_load("hkjc_historic_matches.json")["data"], {"matches": []}])
    provider = HkjcProvider(client)
    records = await provider.fetch_results(date(2026, 10, 2), date(2026, 10, 2))
    assert len(records) == 1
    record = records[0]
    assert record.match_hkjc_id == "50076326"
    assert (record.home_score, record.away_score) == (3, 5)
    assert record.confirmed is True
    assert record.ttl_corner is None
    _, variables = client.calls[0]
    assert variables["startDate"] == "2026-10-02"
    assert variables["endDate"] == "2026-10-02"
    assert variables["startIndex"] == 0
    assert variables["endIndex"] == 20


async def test_real_pools_and_quarter_line_main_line():
    matches = _load("hkjc_match_details.json")["data"]["matches"]
    pools = {pool["oddsType"]: pool for pool in matches[0]["foPools"]}
    had = hkjc_had_odds(pools["HAD"])
    assert had is not None
    assert set(had) == {"H", "D", "A"}
    main_conditions = [
        line["condition"] for line in pools["HDC"]["lines"] if line.get("main")
    ]
    assert main_conditions == ["-0.5/-1.0"]
    assert parse_handicap_line(main_conditions[0]) is None
    assert hkjc_hdc_main(pools["HDC"]) is None


@pytest.mark.live
async def test_live_hkjc_smoke():
    from app.config import get_settings
    from app.providers.hkjc.client import HkjcGraphQLClient

    settings = get_settings()
    client = HkjcGraphQLClient(
        url=settings.hkjc_graphql_url,
        referer=settings.hkjc_referer,
        origin=settings.hkjc_origin,
        user_agent=settings.hkjc_user_agent,
        throttle_seconds=settings.hkjc_throttle_seconds,
    )
    try:
        provider = HkjcProvider(client)
        today = datetime.now(UTC).date()
        fixtures = await provider.fetch_fixtures(today, today)
        assert fixtures, "HKJC returned no fixtures at all"
    finally:
        await client.aclose()
