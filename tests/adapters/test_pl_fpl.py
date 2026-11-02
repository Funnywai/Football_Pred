import copy

import httpx
import pytest
import respx

from packages.adapters.base import (
    AdapterHTTPError,
    AdapterSchemaError,
    MinIntervalRateLimiter,
    hash_text,
)
from packages.adapters.fpl import FplAdapter
from packages.adapters.pl_pulselive import PlPulseliveAdapter
from packages.domain.enums import AvailabilityStatus, LineupType

PL_PAYLOAD = {
    "homeTeam": {
        "formation": "4-3-3",
        "startingXI": [{"id": 11, "name": "Home GK", "position": "GK"}],
        "substitutes": [{"id": 12, "name": "Home Sub", "position": "DF"}],
    },
    "awayTeam": {
        "formation": "3-4-3",
        "startingXI": [{"id": 21, "name": "Away GK", "position": "GK"}],
        "substitutes": [],
    },
}

FPL_PAYLOAD = {
    "teams": [{"id": 1, "name": "Arsenal"}],
    "elements": [
        {
            "id": 101,
            "web_name": "Saka",
            "team": 1,
            "status": "a",
            "news": "",
            "chance_of_playing_next_round": None,
        },
        {
            "id": 102,
            "web_name": "Injured",
            "team": 1,
            "status": "i",
            "news": "Knee injury",
            "chance_of_playing_next_round": 0,
        },
        {
            "id": 103,
            "web_name": "Banned",
            "team": 1,
            "status": "s",
            "news": "Suspended",
            "chance_of_playing_next_round": 0,
        },
    ],
}

NO_LIMIT = MinIntervalRateLimiter(0.0)
PL_LINEUPS_URL = "https://footballapi.pulselive.com/football/fixtures/999/lineups"
FPL_BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"


def _pl_payload() -> dict:
    return copy.deepcopy(PL_PAYLOAD)


def _fpl_payload() -> dict:
    return copy.deepcopy(FPL_PAYLOAD)


def test_pulselive_lineups_map_to_standard_dto():
    rows = PlPulseliveAdapter.parse_lineups(PL_PAYLOAD)
    assert len(rows) == 2
    assert rows[0].lineup_type is LineupType.STANDARD
    assert rows[0].starters[0].source_player_id == 11
    assert rows[0].subs[0].source_player_id == 12
    assert rows[1].formation == "3-4-3"


def test_fpl_availability_maps_known_statuses():
    rows = FplAdapter.parse_availability(FPL_PAYLOAD)
    assert rows[0].status is AvailabilityStatus.AVAILABLE
    assert rows[0].provider_status == "a"
    assert rows[1].status is AvailabilityStatus.INJURY
    assert rows[1].provider_status == "i"
    assert rows[1].news == "Knee injury"
    assert rows[2].status is AvailabilityStatus.SUSPENSION
    assert rows[2].provider_status == "s"
    assert rows[1].team_name == "Arsenal"


def test_adapters_keep_low_tos_risk_metadata():
    pl = PlPulseliveAdapter(limiter=NO_LIMIT)
    fpl = FplAdapter(limiter=NO_LIMIT)
    try:
        assert pl.tos_risk == "low"
        assert fpl.tos_risk == "low"
    finally:
        pl.close()
        fpl.close()


def test_default_pl_and_fpl_adapters_share_process_rate_limiters():
    pl_first = PlPulseliveAdapter()
    pl_second = PlPulseliveAdapter()
    fpl_first = FplAdapter()
    fpl_second = FplAdapter()
    try:
        assert pl_first._limiter is pl_second._limiter
        assert fpl_first._limiter is fpl_second._limiter
    finally:
        pl_first.close()
        pl_second.close()
        fpl_first.close()
        fpl_second.close()


def test_pl_and_fpl_are_epl_only_cross_checks():
    assert PlPulseliveAdapter.competition_codes == frozenset({"EPL"})
    assert FplAdapter.competition_codes == frozenset({"EPL"})
    for adapter in (PlPulseliveAdapter, FplAdapter):
        assert adapter.supports_competition("EPL") is True
        assert adapter.supports_competition("UCL") is False
        assert adapter.supports_competition("LALIGA") is False


@pytest.mark.parametrize("payload", [None, [], "payload"])
def test_pulselive_rejects_non_object_payloads(payload):
    with pytest.raises(AdapterSchemaError, match="payload"):
        PlPulseliveAdapter.parse_lineups(payload)


@pytest.mark.parametrize("side", ["homeTeam", "awayTeam"])
def test_pulselive_rejects_missing_team(side):
    payload = _pl_payload()
    del payload[side]

    with pytest.raises(AdapterSchemaError, match=side):
        PlPulseliveAdapter.parse_lineups(payload)


def test_pulselive_rejects_empty_starters():
    payload = _pl_payload()
    payload["awayTeam"]["startingXI"] = []

    with pytest.raises(AdapterSchemaError, match="startingXI"):
        PlPulseliveAdapter.parse_lineups(payload)


def test_pulselive_rejects_malformed_player():
    payload = _pl_payload()
    payload["homeTeam"]["startingXI"] = [{"name": "No Id"}]

    with pytest.raises(AdapterSchemaError, match="id"):
        PlPulseliveAdapter.parse_lineups(payload)


@respx.mock
def test_pulselive_fetch_keeps_provenance_and_official_headers():
    route = respx.get(PL_LINEUPS_URL).mock(
        return_value=httpx.Response(200, json=PL_PAYLOAD)
    )
    adapter = PlPulseliveAdapter(limiter=NO_LIMIT)
    try:
        result = adapter.fetch_lineups(999)
    finally:
        adapter.close()

    request = route.calls[0].request
    assert request.headers["Origin"] == "https://www.premierleague.com"
    assert request.headers["Referer"] == "https://www.premierleague.com/"
    assert result.source_name == "pl-pulselive"
    assert result.schema_version == "v1"
    assert result.payload_hash == hash_text(result.raw_text)
    assert not hasattr(result, "verified")


@respx.mock
def test_pulselive_fetch_rejects_non_positive_fixture_without_http_call():
    with (
        PlPulseliveAdapter(limiter=NO_LIMIT) as adapter,
        pytest.raises(AdapterSchemaError, match="fixture_id"),
    ):
        adapter.fetch_lineups(0)

    assert not respx.calls


@respx.mock
def test_pulselive_fetch_500_raises_http_error():
    respx.get(PL_LINEUPS_URL).mock(return_value=httpx.Response(500))

    with (
        PlPulseliveAdapter(limiter=NO_LIMIT) as adapter,
        pytest.raises(AdapterHTTPError),
    ):
        adapter.fetch_lineups(999)


def test_fpl_availability_maps_doubtful_and_unavailable():
    payload = _fpl_payload()
    payload["elements"].extend(
        [
            {
                "id": 104,
                "web_name": "Doubt",
                "team": 1,
                "status": "d",
                "news": "Knock",
                "chance_of_playing_next_round": 50,
            },
            {
                "id": 105,
                "web_name": "Out",
                "team": 1,
                "status": "u",
                "news": "",
                "chance_of_playing_next_round": 0,
            },
        ]
    )

    rows = FplAdapter.parse_availability(payload)

    assert rows[3].status is AvailabilityStatus.DOUBTFUL
    assert rows[3].provider_status == "d"
    assert rows[4].status is AvailabilityStatus.DOUBTFUL
    assert rows[4].provider_status == "u"


def test_fpl_rejects_unknown_status():
    payload = _fpl_payload()
    payload["elements"][0]["status"] = "x"

    with pytest.raises(AdapterSchemaError, match="unknown FPL status"):
        FplAdapter.parse_availability(payload)


def test_fpl_rejects_missing_status():
    payload = _fpl_payload()
    del payload["elements"][0]["status"]

    with pytest.raises(AdapterSchemaError, match="status"):
        FplAdapter.parse_availability(payload)


def test_fpl_rejects_unknown_team_reference():
    payload = _fpl_payload()
    payload["elements"][0]["team"] = 999

    with pytest.raises(AdapterSchemaError, match="team"):
        FplAdapter.parse_availability(payload)


def test_fpl_rejects_invalid_chance_of_playing():
    payload = _fpl_payload()
    payload["elements"][0]["chance_of_playing_next_round"] = "high"

    with pytest.raises(AdapterSchemaError, match="chance_of_playing_next_round"):
        FplAdapter.parse_availability(payload)


def test_fpl_rejects_missing_web_name():
    payload = _fpl_payload()
    del payload["elements"][0]["web_name"]

    with pytest.raises(AdapterSchemaError, match="web_name"):
        FplAdapter.parse_availability(payload)


def test_fpl_allows_explicit_empty_squads():
    assert FplAdapter.parse_availability({"teams": [], "elements": []}) == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"teams": None, "elements": []},
        {"teams": [], "elements": None},
        {"elements": []},
        {"teams": []},
    ],
)
def test_fpl_rejects_missing_or_null_required_lists(payload):
    with pytest.raises(AdapterSchemaError, match="(teams|elements)"):
        FplAdapter.parse_availability(payload)


def test_fpl_normalizes_whitespace_news_to_none():
    payload = _fpl_payload()
    payload["elements"][0]["news"] = "   "

    rows = FplAdapter.parse_availability(payload)

    assert rows[0].news is None


def test_fpl_strips_player_and_team_names():
    payload = _fpl_payload()
    payload["teams"][0]["name"] = " Arsenal "
    payload["elements"][0]["web_name"] = " Saka "

    rows = FplAdapter.parse_availability(payload)

    assert rows[0].team_name == "Arsenal"
    assert rows[0].web_name == "Saka"


@pytest.mark.parametrize("payload", [None, [], "payload"])
def test_fpl_rejects_non_object_payloads(payload):
    with pytest.raises(AdapterSchemaError, match="payload"):
        FplAdapter.parse_availability(payload)


@respx.mock
def test_fpl_fetch_keeps_provenance_and_is_not_verified():
    route = respx.get(FPL_BOOTSTRAP_URL).mock(
        return_value=httpx.Response(200, json=FPL_PAYLOAD)
    )
    adapter = FplAdapter(limiter=NO_LIMIT)
    try:
        result = adapter.fetch_bootstrap()
    finally:
        adapter.close()

    assert route.called
    assert result.source_name == "fpl"
    assert result.schema_version == "v1"
    assert result.http_status == 200
    assert result.payload == FPL_PAYLOAD
    assert result.payload_hash == hash_text(result.raw_text)
    assert not hasattr(result, "verified")
