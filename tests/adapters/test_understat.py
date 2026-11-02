import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from packages.adapters.base import (
    AdapterSchemaError,
    CoverageGapError,
    MinIntervalRateLimiter,
    hash_text,
)
from packages.adapters.understat import UnderstatAdapter

TEAMS_PAYLOAD = {
    "1": {
        "id": "1",
        "title": "Arsenal",
        "history": [
            {
                "xG": "2.10",
                "xGA": "0.80",
                "npxG": "1.90",
                "scored": 2,
                "deep": 12,
                "ppda": {"att": 8.5, "def": 13.2},
            },
            {
                "xG": "1.40",
                "xGA": "1.20",
                "npxG": "1.30",
                "scored": 1,
                "deep": 9,
                "ppda": {"att": 9.5, "def": 12.0},
            },
        ],
    }
}

NO_LIMIT = MinIntervalRateLimiter(0.0)


def _encode_understat(payload: dict[str, Any]) -> str:
    return json.dumps(payload).replace('"', "\\x22")


def _league_html(payload: dict[str, Any]) -> str:
    return (
        "<html><script>"
        f"var teamsData = JSON.parse('{_encode_understat(payload)}');"
        "</script></html>"
    )


def test_parse_team_seasons_aggregates_history():
    rows = UnderstatAdapter.parse_team_seasons(_league_html(TEAMS_PAYLOAD))
    assert len(rows) == 1
    row = rows[0]
    assert row.team_name == "Arsenal"
    assert row.matches == 2
    assert row.goals == 3
    assert row.xg == Decimal("3.50")
    assert row.xga == Decimal("2.00")
    assert row.npxg == Decimal("3.20")
    # PPDA is passes allowed per defensive action: sum(att) / sum(def).
    assert row.ppda == Decimal(18) / Decimal("25.2")
    assert row.deep == 21


def test_ppda_ignores_entry_missing_def():
    payload = {
        "1": {
            "id": "1",
            "title": "Arsenal",
            "history": [
                {
                    "xG": "1.0",
                    "xGA": "1.0",
                    "npxG": "1.0",
                    "scored": 1,
                    "deep": 1,
                    "ppda": {"att": 4.0},
                },
                {
                    "xG": "1.0",
                    "xGA": "1.0",
                    "npxG": "1.0",
                    "scored": 1,
                    "deep": 1,
                    "ppda": {"att": 9.0, "def": 18.0},
                },
                {
                    "xG": "1.0",
                    "xGA": "1.0",
                    "npxG": "1.0",
                    "scored": 1,
                    "deep": 1,
                    "ppda": {},
                },
                {
                    "xG": "1.0",
                    "xGA": "1.0",
                    "npxG": "1.0",
                    "scored": 1,
                    "deep": 1,
                },
            ],
        }
    }

    rows = UnderstatAdapter.parse_team_seasons(_league_html(payload))

    assert len(rows) == 1
    assert rows[0].ppda == Decimal(9) / Decimal(18)


def test_ppda_is_zero_when_no_complete_entry():
    payload = {
        "1": {
            "id": "1",
            "title": "Arsenal",
            "history": [
                {"ppda": {"att": 4.0}},
                {"ppda": {"def": 8.0}},
                {"ppda": {}},
            ],
        }
    }

    rows = UnderstatAdapter.parse_team_seasons(_league_html(payload))

    assert rows[0].ppda == Decimal(0)


def test_ucl_is_a_coverage_gap_without_http_call():
    adapter = UnderstatAdapter(limiter=NO_LIMIT)
    try:
        with pytest.raises(CoverageGapError):
            adapter.fetch_league("UCL", 2025)
    finally:
        adapter.close()


@respx.mock
def test_fetch_league_uses_competition_slug():
    route = respx.get("https://understat.com/league/La_liga/2025").mock(
        return_value=httpx.Response(200, text=_league_html(TEAMS_PAYLOAD))
    )
    adapter = UnderstatAdapter(limiter=NO_LIMIT)
    try:
        result = adapter.fetch_league("LALIGA", 2025)
    finally:
        adapter.close()
    assert route.called
    assert result.source_name == "understat"
    assert "teamsData" in result.raw_text


@pytest.mark.parametrize(
    ("competition_code", "slug"),
    [
        ("EPL", "EPL"),
        ("LALIGA", "La_liga"),
        ("BUNDESLIGA", "Bundesliga"),
        ("SERIEA", "Serie_A"),
        ("LIGUE1", "Ligue_1"),
    ],
)
@respx.mock
def test_fetch_league_supports_only_the_five_free_leagues(
    competition_code: str, slug: str
) -> None:
    route = respx.get(f"https://understat.com/league/{slug}/2025").mock(
        return_value=httpx.Response(200, text=_league_html(TEAMS_PAYLOAD))
    )
    adapter = UnderstatAdapter(limiter=NO_LIMIT)
    try:
        result = adapter.fetch_league(competition_code, 2025)
    finally:
        adapter.close()
    assert route.called
    assert result.source_url == f"https://understat.com/league/{slug}/2025"


def test_missing_teamsdata_raises_schema_error():
    with pytest.raises(AdapterSchemaError):
        UnderstatAdapter.parse_team_seasons("<html><body>no data</body></html>")


def test_teams_without_history_are_skipped():
    payload = {
        "1": {"id": "1", "title": "Arsenal", "history": []},
        "2": {"id": "2", "title": "Chelsea", "history": TEAMS_PAYLOAD["1"]["history"]},
    }
    rows = UnderstatAdapter.parse_team_seasons(_league_html(payload))
    assert [row.team_name for row in rows] == ["Chelsea"]


@respx.mock
def test_fetch_result_keeps_provenance_and_is_not_verified():
    respx.get("https://understat.com/league/EPL/2025").mock(
        return_value=httpx.Response(200, text=_league_html(TEAMS_PAYLOAD))
    )
    adapter = UnderstatAdapter(limiter=NO_LIMIT)
    try:
        result = adapter.fetch_league("EPL", 2025)
    finally:
        adapter.close()
    assert result.schema_version == "html-v1"
    assert result.http_status == 200
    assert result.payload == result.raw_text
    assert result.payload_hash == hash_text(result.raw_text)
    assert not hasattr(result, "verified")


@respx.mock
def test_unknown_competition_is_a_coverage_gap_without_http_call():
    adapter = UnderstatAdapter(limiter=NO_LIMIT)
    try:
        with pytest.raises(CoverageGapError):
            adapter.fetch_league("WORLD_CUP", 2025)
    finally:
        adapter.close()
    assert not respx.calls
