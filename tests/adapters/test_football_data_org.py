import copy
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx

from packages.adapters.base import (
    AdapterHTTPError,
    AdapterRateLimitedError,
    AdapterSchemaError,
    MinIntervalRateLimiter,
    hash_text,
)
from packages.adapters.football_data_org import FootballDataOrgAdapter
from packages.domain.enums import MatchStatus

MATCHES_URL = "https://api.football-data.org/v4/competitions/PL/matches"

MATCHES_PAYLOAD = {
    "competition": {"code": "PL"},
    "filters": {"season": "2025"},
    "matches": [
        {
            "id": 1001,
            "utcDate": "2026-08-15T14:00:00Z",
            "status": "FINISHED",
            "matchday": 1,
            "homeTeam": {"id": 10, "name": "Arsenal"},
            "awayTeam": {"id": 20, "name": "Chelsea"},
            "score": {
                "duration": "REGULAR",
                "fullTime": {"home": 2, "away": 1},
                "halfTime": {"home": 1, "away": 0},
            },
        },
        {
            "id": 1002,
            "utcDate": "2026-08-19T19:00:00Z",
            "status": "FINISHED",
            "matchday": 2,
            "homeTeam": {"id": 30, "name": "Real Madrid"},
            "awayTeam": {"id": 40, "name": "Bayern Munich"},
            "score": {
                "duration": "EXTRA_TIME",
                "fullTime": {"home": 3, "away": 2},
                "halfTime": {"home": 1, "away": 1},
            },
        },
    ],
}

STANDINGS_PAYLOAD = {
    "standings": [
        {
            "table": [
                {
                    "position": 1,
                    "team": {"id": 10, "name": "Arsenal"},
                    "playedGames": 1,
                    "won": 1,
                    "draw": 0,
                    "lost": 0,
                    "goalsFor": 2,
                    "goalsAgainst": 1,
                    "points": 3,
                }
            ]
        }
    ]
}

NO_LIMIT = MinIntervalRateLimiter(0.0)


def _single_match_payload() -> dict[str, Any]:
    return {
        "competition": {"code": "PL"},
        "filters": {"season": "2025"},
        "matches": [
            {
                "id": 1001,
                "utcDate": "2026-08-15T14:00:00Z",
                "status": "FINISHED",
                "matchday": 1,
                "homeTeam": {"id": 10, "name": "Arsenal"},
                "awayTeam": {"id": 20, "name": "Chelsea"},
                "score": {
                    "duration": "REGULAR",
                    "fullTime": {"home": 2, "away": 1},
                    "halfTime": {"home": 1, "away": 0},
                },
            }
        ],
    }


@respx.mock
def test_fetch_matches_sends_api_key_and_returns_provenance():
    route = respx.get(MATCHES_URL).mock(return_value=httpx.Response(200, json=MATCHES_PAYLOAD))
    adapter = FootballDataOrgAdapter(api_key="secret", limiter=NO_LIMIT)
    try:
        result = adapter.fetch_matches("EPL", 2025)
    finally:
        adapter.close()
    assert result.payload_hash == hash_text(result.raw_text)
    assert route.calls[0].request.headers["X-Auth-Token"] == "secret"
    assert route.calls[0].request.url.params["season"] == "2025"
    assert result.source_name == "football-data.org"
    assert result.source_url == f"{MATCHES_URL}?season=2025"
    assert result.fetched_at.utcoffset() == timedelta(0)
    assert result.schema_version == "v4"


@respx.mock
def test_fetch_matches_records_adapter_schema_version():
    respx.get(MATCHES_URL).mock(return_value=httpx.Response(200, json=MATCHES_PAYLOAD))
    with FootballDataOrgAdapter(api_key="secret", limiter=NO_LIMIT) as adapter:
        result = adapter.fetch_matches("EPL", 2025)
    assert result.schema_version == "v4"


def test_parse_matches_keeps_regulation_and_final_scores_separate():
    matches = FootballDataOrgAdapter.parse_matches(MATCHES_PAYLOAD)
    regular = matches[0]
    extra_time = matches[1]
    assert regular.home_goals_90 == 2
    assert regular.away_goals_90 == 1
    assert regular.home_goals_final == 2
    assert regular.status is MatchStatus.FINISHED
    assert extra_time.home_goals_90 is None
    assert extra_time.away_goals_90 is None
    assert extra_time.home_goals_final == 3
    assert extra_time.away_goals_final == 2


def test_parse_matches_missing_duration_leaves_90_minute_goals_unknown():
    payload = _single_match_payload()
    del payload["matches"][0]["score"]["duration"]

    match = FootballDataOrgAdapter.parse_matches(payload)[0]

    assert match.status is MatchStatus.FINISHED
    assert match.home_goals_90 is None
    assert match.away_goals_90 is None
    assert match.home_goals_final == 2
    assert match.away_goals_final == 1


def test_parse_matches_penalty_shootout_leaves_90_minute_goals_unknown():
    payload = _single_match_payload()
    payload["matches"][0]["score"]["duration"] = "PENALTY_SHOOTOUT"

    match = FootballDataOrgAdapter.parse_matches(payload)[0]

    assert match.home_goals_90 is None
    assert match.away_goals_90 is None
    assert match.home_goals_final == 2
    assert match.away_goals_final == 1


def test_parse_matches_rejects_unknown_duration():
    payload = _single_match_payload()
    payload["matches"][0]["score"]["duration"] = "UNKNOWN_DURATION"

    with pytest.raises(AdapterSchemaError, match="unsupported score.duration"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_missing_status():
    payload = _single_match_payload()
    del payload["matches"][0]["status"]

    with pytest.raises(AdapterSchemaError, match="missing status"):
        FootballDataOrgAdapter.parse_matches(payload)


@pytest.mark.parametrize(
    "status", ["WHATEVER", "AWARDED", "SUSPENDED", "2026-12-09 19:00:00Z"]
)
def test_parse_matches_skips_unmapped_provider_status(status):
    payload = _single_match_payload()
    payload["matches"][0]["status"] = status

    assert FootballDataOrgAdapter.parse_matches(payload) == []


def test_parse_matches_skips_unmapped_status_and_keeps_valid_rows(caplog):
    payload = _single_match_payload()
    skipped = copy.deepcopy(payload["matches"][0])
    skipped["id"] = 1002
    skipped["status"] = "2026-12-09 19:00:00Z"
    payload["matches"].append(skipped)

    with caplog.at_level("WARNING"):
        matches = FootballDataOrgAdapter.parse_matches(payload)

    assert [match.source_match_id for match in matches] == [1001]
    assert "1002" in caplog.text


def test_parse_matches_wraps_malformed_row_with_row_context():
    payload = _single_match_payload()
    del payload["matches"][0]["homeTeam"]

    with pytest.raises(AdapterSchemaError) as exc_info:
        FootballDataOrgAdapter.parse_matches(payload)

    message = str(exc_info.value)
    assert "invalid match row at index 0" in message
    assert "id=1001" in message


def test_parse_matches_rejects_missing_utc_date():
    payload = _single_match_payload()
    del payload["matches"][0]["utcDate"]

    with pytest.raises(AdapterSchemaError, match="missing utcDate"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_non_string_utc_date():
    payload = _single_match_payload()
    payload["matches"][0]["utcDate"] = 20260815

    with pytest.raises(AdapterSchemaError, match="utcDate must be a string"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_string_score():
    payload = _single_match_payload()
    payload["matches"][0]["score"] = "2-1"

    with pytest.raises(AdapterSchemaError, match="score must be an object"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_string_full_time():
    payload = _single_match_payload()
    payload["matches"][0]["score"]["fullTime"] = "2-1"

    with pytest.raises(AdapterSchemaError, match="fullTime must be an object"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_non_iterable_matches():
    payload = _single_match_payload()
    payload["matches"] = 1001

    with pytest.raises(AdapterSchemaError, match="matches must be a list"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_string_competition():
    payload = _single_match_payload()
    payload["competition"] = "PL"

    with pytest.raises(AdapterSchemaError, match="competition must be an object"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_string_filters():
    payload = _single_match_payload()
    payload["filters"] = "season=2025"

    with pytest.raises(AdapterSchemaError, match="filters must be an object"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_null_competition():
    payload = _single_match_payload()
    payload["competition"] = None

    with pytest.raises(AdapterSchemaError, match="competition must be an object"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_null_filters():
    payload = _single_match_payload()
    payload["filters"] = None

    with pytest.raises(AdapterSchemaError, match="filters must be an object"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_null_matches():
    payload = _single_match_payload()
    payload["matches"] = None

    with pytest.raises(AdapterSchemaError, match="matches must be a list"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_null_score():
    payload = _single_match_payload()
    payload["matches"][0]["score"] = None

    with pytest.raises(AdapterSchemaError, match="score must be an object"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_null_full_time():
    payload = _single_match_payload()
    payload["matches"][0]["score"]["fullTime"] = None

    with pytest.raises(AdapterSchemaError, match="fullTime must be an object"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_null_utc_date():
    payload = _single_match_payload()
    payload["matches"][0]["utcDate"] = None

    with pytest.raises(AdapterSchemaError, match="utcDate must be a string"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_rejects_null_status():
    payload = _single_match_payload()
    payload["matches"][0]["status"] = None

    with pytest.raises(AdapterSchemaError, match="status must be a string"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_allows_absent_matches():
    payload = _single_match_payload()
    del payload["matches"]

    assert FootballDataOrgAdapter.parse_matches(payload) == []


def test_parse_matches_allows_absent_score():
    payload = _single_match_payload()
    del payload["matches"][0]["score"]

    match = FootballDataOrgAdapter.parse_matches(payload)[0]

    assert match.home_goals_90 is None
    assert match.away_goals_90 is None
    assert match.home_goals_final is None
    assert match.away_goals_final is None


def test_parse_matches_rejects_string_row():
    payload = _single_match_payload()
    payload["matches"][0] = "not-a-match"

    with pytest.raises(AdapterSchemaError, match="match row must be an object"):
        FootballDataOrgAdapter.parse_matches(payload)


@pytest.mark.parametrize("side", ["homeTeam", "awayTeam"])
def test_parse_matches_rejects_non_object_team(side):
    payload = _single_match_payload()
    payload["matches"][0][side] = "Arsenal"

    with pytest.raises(AdapterSchemaError, match=f"{side} must be an object"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_matches_wraps_invalid_season():
    payload = _single_match_payload()
    payload["filters"]["season"] = "not-a-season"

    with pytest.raises(AdapterSchemaError, match="invalid filters.season"):
        FootballDataOrgAdapter.parse_matches(payload)


def test_parse_standings():
    rows = FootballDataOrgAdapter.parse_standings(STANDINGS_PAYLOAD)
    assert len(rows) == 1
    assert rows[0].team_name == "Arsenal"
    assert rows[0].points == 3


def test_parse_standings_wraps_malformed_row_with_row_context():
    payload = {"standings": [{"table": [{"team": {"id": 10, "name": "Arsenal"}}]}]}

    with pytest.raises(AdapterSchemaError) as exc_info:
        FootballDataOrgAdapter.parse_standings(payload)

    message = str(exc_info.value)
    assert "invalid standings row at index 0" in message
    assert "position" in message


def test_parse_standings_rejects_string_first_group():
    payload = {"standings": ["not-a-group"]}

    with pytest.raises(AdapterSchemaError, match=r"standings\[0\] must be an object"):
        FootballDataOrgAdapter.parse_standings(payload)


def test_parse_standings_rejects_non_iterable_table():
    payload = {"standings": [{"table": 1}]}

    with pytest.raises(AdapterSchemaError, match=r"standings\[0\]\.table must be a list"):
        FootballDataOrgAdapter.parse_standings(payload)


def test_parse_standings_rejects_string_table_entry():
    payload = {"standings": [{"table": ["not-a-row"]}]}

    with pytest.raises(AdapterSchemaError, match="invalid standings row at index 0"):
        FootballDataOrgAdapter.parse_standings(payload)


def test_parse_standings_rejects_non_list_standings():
    payload = {"standings": {"table": []}}

    with pytest.raises(AdapterSchemaError, match="standings must be a list"):
        FootballDataOrgAdapter.parse_standings(payload)


def test_parse_standings_rejects_null_standings():
    with pytest.raises(AdapterSchemaError, match="standings must be a list"):
        FootballDataOrgAdapter.parse_standings({"standings": None})


def test_parse_standings_rejects_null_table():
    with pytest.raises(
        AdapterSchemaError, match=r"standings\[0\]\.table must be a list"
    ):
        FootballDataOrgAdapter.parse_standings({"standings": [{"table": None}]})


def test_parse_standings_allows_absent_table():
    assert FootballDataOrgAdapter.parse_standings({"standings": [{}]}) == []


def test_parse_standings_rejects_string_team():
    payload = {
        "standings": [
            {
                "table": [
                    {
                        "position": 1,
                        "team": "Arsenal",
                        "playedGames": 1,
                        "won": 1,
                        "draw": 0,
                        "lost": 0,
                        "goalsFor": 2,
                        "goalsAgainst": 1,
                        "points": 3,
                    }
                ]
            }
        ]
    }

    with pytest.raises(AdapterSchemaError, match="team must be an object"):
        FootballDataOrgAdapter.parse_standings(payload)


@pytest.mark.parametrize(
    "parse",
    [FootballDataOrgAdapter.parse_matches, FootballDataOrgAdapter.parse_standings],
)
def test_parse_rejects_non_object_payload(parse):
    with pytest.raises(AdapterSchemaError, match="payload must be an object"):
        parse(["not-a-payload"])


@respx.mock
def test_fetch_matches_429_raises_rate_limited_error():
    respx.get(MATCHES_URL).mock(return_value=httpx.Response(429))

    with (
        FootballDataOrgAdapter(api_key="secret", limiter=NO_LIMIT) as adapter,
        pytest.raises(AdapterRateLimitedError),
    ):
        adapter.fetch_matches("EPL", 2025)


@respx.mock
def test_fetch_matches_500_raises_http_error():
    respx.get(MATCHES_URL).mock(return_value=httpx.Response(500))

    with (
        FootballDataOrgAdapter(api_key="secret", limiter=NO_LIMIT) as adapter,
        pytest.raises(AdapterHTTPError),
    ):
        adapter.fetch_matches("EPL", 2025)


@respx.mock
def test_fetch_matches_non_json_body_raises_schema_error():
    respx.get(MATCHES_URL).mock(return_value=httpx.Response(200, text="<html>not json</html>"))

    with (
        FootballDataOrgAdapter(api_key="secret", limiter=NO_LIMIT) as adapter,
        pytest.raises(AdapterSchemaError, match="did not return JSON"),
    ):
        adapter.fetch_matches("EPL", 2025)


@respx.mock
def test_unknown_competition_raises_before_http_call():
    route = respx.get(
        "https://api.football-data.org/v4/competitions/UNKNOWN/matches"
    ).mock(return_value=httpx.Response(200, json=MATCHES_PAYLOAD))

    with (
        FootballDataOrgAdapter(api_key="secret", limiter=NO_LIMIT) as adapter,
        pytest.raises(AdapterSchemaError, match="unknown competition code"),
    ):
        adapter.fetch_matches("UNKNOWN", 2025)

    assert not route.called


@respx.mock
def test_fetch_standings_uses_competition_code():
    route = respx.get("https://api.football-data.org/v4/competitions/CL/standings").mock(
        return_value=httpx.Response(200, json=STANDINGS_PAYLOAD)
    )
    adapter = FootballDataOrgAdapter(api_key="secret", limiter=NO_LIMIT)
    try:
        result = adapter.fetch_standings("UCL", 2025)
    finally:
        adapter.close()
    assert result.http_status == 200
    assert route.called


def test_default_adapters_share_process_rate_limiter():
    first = FootballDataOrgAdapter(api_key="secret")
    second = FootballDataOrgAdapter(api_key="secret")
    try:
        assert first._limiter is second._limiter
    finally:
        first.close()
        second.close()
