import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

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


async def test_fetch_fixtures_parses_matches():
    client = _FakeClient([_load("hkjc_football_matches.json")["data"]])
    provider = HkjcProvider(client)
    fixtures = await provider.fetch_fixtures(date(2026, 10, 12), date(2026, 10, 15))
    assert len(fixtures) == 2
    first = fixtures[0]
    assert first.hkjc_match_id == "M-1001"
    assert first.league_name == "English Premier League"
    assert first.hkjc_tourn_id == "TOURN-EPL"
    assert first.kickoff_time == datetime(2026, 10, 12, 11, 30, tzinfo=UTC)
    assert first.status == "scheduled"
    assert first.home_team_name_en == "Manchester United"
    assert first.home_team_name_ch == "曼聯"
    assert first.away_team_hkjc_id == "T-2"
    assert first.venue == "Old Trafford"
    assert fixtures[1].status == "live"


async def test_fetch_fixtures_passes_date_range_and_tourn_ids():
    client = _FakeClient([_load("hkjc_football_matches.json")["data"]])
    provider = HkjcProvider(client, tourn_ids=["TOURN-EPL"])
    await provider.fetch_fixtures(date(2026, 10, 12), date(2026, 10, 15))
    _, variables = client.calls[0]
    assert variables["startDate"] == "2026-10-12"
    assert variables["endDate"] == "2026-10-15"
    assert variables["tournIds"] == ["TOURN-EPL"]
    assert variables["showAllMatch"] is False


async def test_fetch_odds_uses_two_batches_and_parses_pools():
    # 3 responses: fetch_fixtures, then one per odds batch (batch 1 carries the pools).
    client = _FakeClient(
        [
            _load("hkjc_football_matches.json")["data"],
            _load("hkjc_football_matches.json")["data"],
            {"matches": []},
        ]
    )
    provider = HkjcProvider(client)
    fixtures = await provider.fetch_fixtures(date(2026, 10, 12), date(2026, 10, 15))
    client.calls.clear()
    records = await provider.fetch_odds(fixtures)
    assert len(records) == 3
    assert client.calls[0][1]["fbOddsTypes"] == ["HAD", "HDC", "HIL", "CRS"]
    assert client.calls[1][1]["fbOddsTypes"] == ["HHA", "CHD", "CHL"]
    assert client.calls[0][1]["fbOddsTypesM"] == ["HAD", "HDC", "HIL", "CRS"]
    assert {r.odds_type for r in records} == {"HAD", "HDC"}
    assert all(r.captured_at.tzinfo is not None for r in records)
    assert records[0].payload["oddsType"] in {"HAD", "HDC"}


async def test_fetch_results_parses_finished_matches_with_pagination():
    client = _FakeClient([_load("hkjc_historic_matches.json")["data"]])
    provider = HkjcProvider(client)
    records = await provider.fetch_results(date(2026, 10, 10), date(2026, 10, 12))
    assert len(records) == 2
    first = records[0]
    assert first.match_hkjc_id == "M-1001"
    assert first.home_score == 0
    assert first.away_score == 0
    assert first.ttl_corner == 9
    assert first.confirmed is True
    assert first.payout_confirmed is True
    _, variables = client.calls[0]
    assert variables["startIndex"] == 0
    assert variables["endIndex"] == 500


async def test_fetch_result_details_returns_payout_pools():
    client = _FakeClient([_load("hkjc_match_details.json")["data"]])
    provider = HkjcProvider(client)
    details = await provider.fetch_result_details("M-1001")
    assert details["id"] == "M-1001"
    assert details["foPools"][0]["lines"][0]["combinations"][0]["winOrd"] == "H"


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
        assert isinstance(fixtures, list)
    finally:
        await client.aclose()
