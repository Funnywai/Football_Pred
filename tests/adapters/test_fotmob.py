import copy
from datetime import date

import httpx
import pytest
import respx

from packages.adapters.base import (
    AdapterHTTPError,
    AdapterSchemaError,
    MinIntervalRateLimiter,
    hash_text,
)
from packages.adapters.fotmob import FotMobAdapter
from packages.domain.enums import AvailabilityStatus, LineupType

FOTMOB_PAYLOAD = {
    "content": {
        "lineup": {
            "homeTeam": {
                "formation": "4-3-3",
                "starters": [{"id": 1, "name": "Home GK", "position": "GK"}],
                "subs": [{"id": 2, "name": "Home Sub", "position": "DF"}],
            },
            "awayTeam": {
                "formation": "4-2-3-1",
                "starters": [{"id": 3, "name": "Away GK", "position": "GK"}],
                "subs": [],
            },
        },
        "unavailable": {
            "homeTeam": [
                {
                    "id": 9,
                    "name": "Injured Player",
                    "type": "injury",
                    "reason": "Hamstring",
                    "expectedReturn": "2026-09-01",
                }
            ],
            "awayTeam": [
                {
                    "id": 10,
                    "name": "Banned Player",
                    "type": "suspension",
                    "reason": "Red card",
                }
            ],
        },
    }
}

NO_LIMIT = MinIntervalRateLimiter(0.0)
MATCH_DETAILS_URL = "https://www.fotmob.com/api/data/matchDetails"


def _payload() -> dict:
    return copy.deepcopy(FOTMOB_PAYLOAD)


def test_parse_predicted_lineup_marks_inferred():
    rows = FotMobAdapter.parse_lineups(FOTMOB_PAYLOAD, LineupType.PREDICTED)
    assert len(rows) == 2
    home = rows[0]
    assert home.team_side == "home"
    assert home.formation == "4-3-3"
    assert home.inferred is True
    assert home.starters[0].name == "Home GK"
    assert home.subs[0].source_player_id == 2


def test_parse_standard_lineup_is_not_inferred():
    rows = FotMobAdapter.parse_lineups(FOTMOB_PAYLOAD, LineupType.STANDARD)
    assert all(row.inferred is False for row in rows)
    assert all(row.lineup_type is LineupType.STANDARD for row in rows)


def test_parse_unavailable_maps_injury_and_suspension():
    rows = FotMobAdapter.parse_unavailable(FOTMOB_PAYLOAD)
    assert rows[0].status is AvailabilityStatus.INJURY
    assert rows[0].expected_return == date(2026, 9, 1)
    assert rows[1].status is AvailabilityStatus.SUSPENSION


def test_parse_lineup_rejects_missing_payload():
    with pytest.raises(AdapterSchemaError):
        FotMobAdapter.parse_lineups({"content": {}}, LineupType.STANDARD)


def test_adapter_metadata_is_high_tos_risk():
    adapter = FotMobAdapter(limiter=NO_LIMIT)
    try:
        assert adapter.tos_risk == "high"
        assert adapter.name == "fotmob"
    finally:
        adapter.close()


def test_default_adapters_share_process_rate_limiter():
    first = FotMobAdapter()
    second = FotMobAdapter()
    try:
        assert first._limiter is second._limiter
    finally:
        first.close()
        second.close()


def test_competition_metadata_covers_five_leagues_and_ucl():
    assert FotMobAdapter.competition_codes == frozenset(
        {"EPL", "LALIGA", "BUNDESLIGA", "SERIEA", "LIGUE1", "UCL"}
    )
    assert FotMobAdapter.supports_competition("UCL") is True
    assert FotMobAdapter.supports_competition("epl") is True
    assert FotMobAdapter.supports_competition("WORLD_CUP") is False


@pytest.mark.parametrize("payload", [None, [], "payload", {"content": None}, {"content": []}])
def test_parse_lineups_rejects_non_object_container(payload):
    with pytest.raises(AdapterSchemaError):
        FotMobAdapter.parse_lineups(payload, LineupType.STANDARD)


def test_parse_lineups_rejects_missing_side():
    payload = _payload()
    del payload["content"]["lineup"]["awayTeam"]

    with pytest.raises(AdapterSchemaError, match="awayTeam"):
        FotMobAdapter.parse_lineups(payload, LineupType.STANDARD)


def test_parse_lineups_rejects_empty_starters():
    payload = _payload()
    payload["content"]["lineup"]["awayTeam"]["starters"] = []

    with pytest.raises(AdapterSchemaError, match="starters"):
        FotMobAdapter.parse_lineups(payload, LineupType.STANDARD)


def test_parse_lineups_rejects_malformed_player():
    payload = _payload()
    payload["content"]["lineup"]["homeTeam"]["starters"] = [{"name": "No Id"}]

    with pytest.raises(AdapterSchemaError, match="id"):
        FotMobAdapter.parse_lineups(payload, LineupType.PREDICTED)


def test_parse_lineups_rejects_unknown_lineup_type():
    with pytest.raises(AdapterSchemaError, match="lineup_type"):
        FotMobAdapter.parse_lineups(FOTMOB_PAYLOAD, "standard")


def test_parse_lineups_preserves_predicted_lineup_type():
    rows = FotMobAdapter.parse_lineups(FOTMOB_PAYLOAD, LineupType.PREDICTED)

    assert all(row.lineup_type is LineupType.PREDICTED for row in rows)
    assert all(row.inferred is True for row in rows)


def test_parse_unavailable_rejects_unknown_type():
    payload = _payload()
    payload["content"]["unavailable"]["homeTeam"][0]["type"] = "illness"

    with pytest.raises(AdapterSchemaError, match="unknown unavailable type"):
        FotMobAdapter.parse_unavailable(payload)


def test_parse_unavailable_rejects_invalid_expected_return():
    payload = _payload()
    payload["content"]["unavailable"]["homeTeam"][0]["expectedReturn"] = "next month"

    with pytest.raises(AdapterSchemaError, match="expectedReturn"):
        FotMobAdapter.parse_unavailable(payload)


def test_parse_unavailable_rejects_non_list_team_entries():
    payload = _payload()
    payload["content"]["unavailable"]["homeTeam"] = {"id": 9}

    with pytest.raises(AdapterSchemaError, match="homeTeam"):
        FotMobAdapter.parse_unavailable(payload)


def test_parse_unavailable_allows_absent_block():
    assert FotMobAdapter.parse_unavailable({"content": {}}) == []


@respx.mock
def test_fetch_match_details_keeps_provenance_and_is_not_verified():
    route = respx.get(MATCH_DETAILS_URL).mock(
        return_value=httpx.Response(200, json=FOTMOB_PAYLOAD)
    )
    adapter = FotMobAdapter(limiter=NO_LIMIT)
    try:
        result = adapter.fetch_match_details(12345)
    finally:
        adapter.close()

    assert route.called
    assert route.calls[0].request.url.params["matchId"] == "12345"
    assert result.source_name == "fotmob"
    assert result.schema_version == "api-v1"
    assert result.http_status == 200
    assert result.payload == FOTMOB_PAYLOAD
    assert result.payload_hash == hash_text(result.raw_text)
    assert not hasattr(result, "verified")


@respx.mock
def test_fetch_match_details_rejects_non_positive_id_without_http_call():
    with (
        FotMobAdapter(limiter=NO_LIMIT) as adapter,
        pytest.raises(AdapterSchemaError, match="match_id"),
    ):
        adapter.fetch_match_details(0)

    assert not respx.calls


@respx.mock
def test_fetch_match_details_500_raises_http_error():
    respx.get(MATCH_DETAILS_URL).mock(return_value=httpx.Response(500))

    with (
        FotMobAdapter(limiter=NO_LIMIT) as adapter,
        pytest.raises(AdapterHTTPError),
    ):
        adapter.fetch_match_details(12345)


@respx.mock
def test_fetch_match_details_non_json_raises_schema_error():
    respx.get(MATCH_DETAILS_URL).mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )

    with (
        FotMobAdapter(limiter=NO_LIMIT) as adapter,
        pytest.raises(AdapterSchemaError, match="did not return JSON"),
    ):
        adapter.fetch_match_details(12345)


def test_parse_team_xg_reads_league_table_xg():
    from decimal import Decimal

    payload = {
        "table": [
            {
                "data": {
                    "table": {
                        "xg": [
                            {
                                "name": "Arsenal",
                                "teamId": 9825,
                                "played": 9,
                                "xg": 14.5,
                                "xgConceded": 7.2,
                            }
                        ]
                    }
                }
            }
        ]
    }

    rows = FotMobAdapter.parse_team_xg(payload)

    assert len(rows) == 1
    assert rows[0].team_name == "Arsenal"
    assert rows[0].team_id == 9825
    assert rows[0].matches == 9
    assert rows[0].xg == Decimal("14.5")
    assert rows[0].xga == Decimal("7.2")
