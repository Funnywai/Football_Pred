import copy
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from packages.adapters.base import AdapterSchemaError, MinIntervalRateLimiter
from packages.adapters.hkjc import (
    HkjcAdapter,
    HkjcMatchResult,
    HkjcResultSemanticsUnverifiedError,
    HkjcWhitelistError,
)
from packages.adapters.hkjc_queries.loader import HkjcQueryMissingError, load_query
from packages.domain.enums import HkjcResultSemantics, MarketType, Side

GRAPHQL_URL = "https://info.cld.hkjc.com/graphql/base/"
REPO_ROOT = Path(__file__).resolve().parents[2]
QUERIES_DIR = REPO_ROOT / "packages" / "adapters" / "hkjc_queries"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "hkjc"
NO_LIMIT = MinIntervalRateLimiter(0.0)

HAD_PAYLOAD = json.loads((FIXTURES / "had.json").read_text(encoding="utf-8"))
HDC_PAYLOAD = json.loads((FIXTURES / "hdc.json").read_text(encoding="utf-8"))
HIL_PAYLOAD = json.loads((FIXTURES / "hil.json").read_text(encoding="utf-8"))
RESULTS_PAYLOAD = json.loads((FIXTURES / "results.json").read_text(encoding="utf-8"))

WHITELIST_PAYLOAD: dict[str, object] = {
    "errors": [{"message": "not allowed", "extensions": {"code": "WHITELIST_ERROR"}}]
}


def _write_query(tmp_path: Path, key: str, filename: str) -> None:
    (tmp_path / filename).write_text(
        f"query {key}($matchId: String!) {{ match(id: $matchId) {{ id }} }}",
        encoding="utf-8",
    )


def _odds_payload(match_id: str, lines: list[dict[str, object]]) -> dict[str, object]:
    return {
        "data": {
            "matches": [
                {
                    "id": match_id,
                    "matchDate": "2026-11-01+08:00",
                    "foPools": [
                        {
                            "oddsType": "HAD",
                            "status": "SELLINGSTARTED",
                            "updateAt": "2026-11-01T01:31:32.064+08:00",
                            "lines": lines,
                        }
                    ],
                }
            ]
        }
    }


def _line(
    condition: str,
    combos: list[dict[str, object]],
    *,
    status: str = "AVAILABLE",
    main: bool = False,
) -> dict[str, object]:
    return {
        "condition": condition,
        "status": status,
        "main": main,
        "combinations": combos,
    }


def _combo(
    side: str,
    odds: str,
    *,
    offer: object = "Offer",
    status: str = "AVAILABLE",
) -> dict[str, object]:
    return {
        "str": side,
        "status": status,
        "offerEarlySettlement": offer,
        "currentOdds": odds,
    }


def _ft_result(
    home: int,
    away: int,
    *,
    sequence: int,
    stage_id: int = 5,
    result_type: int = 1,
    payout_confirmed: bool = True,
) -> dict[str, object]:
    return {
        "homeResult": home,
        "awayResult": away,
        "ttlCornerResult": -1,
        "resultConfirmType": 5,
        "payoutConfirmed": payout_confirmed,
        "stageId": stage_id,
        "resultType": result_type,
        "sequence": sequence,
    }


def _results_payload(
    match_id: str,
    results: list[dict[str, object]],
    *,
    payout_refund_pools: list[object] | None = None,
    refund_pools: list[object] | None = None,
) -> dict[str, object]:
    return {
        "data": {
            "matchNumByDate": {"total": 1},
            "matches": [
                {
                    "id": match_id,
                    "matchDate": "2026-10-31+08:00",
                    "status": "MATCHENDED",
                    "results": results,
                    "poolInfo": {
                        "payoutRefundPools": payout_refund_pools or [],
                        "refundPools": refund_pools or [],
                    },
                }
            ],
        }
    }


# ---------------------------------------------------------------------------
# Query capture integrity
# ---------------------------------------------------------------------------


def test_official_query_files_load_and_match_live_capture():
    had = load_query(QUERIES_DIR, "HAD")
    hdc = load_query(QUERIES_DIR, "HDC")
    hil = load_query(QUERIES_DIR, "HIL")
    results = load_query(QUERIES_DIR, "matchResults")

    assert had.startswith("query matchList")
    assert "$fbOddsTypesM" in had
    assert "foPools(fbOddsTypes: $fbOddsTypes)" in had
    assert had == hdc == hil
    assert "match(id: $matchId)" not in had

    assert results.startswith("query matchResults")
    assert "matchNumByDate(startDate" in results
    assert "matchResult(startDate" in results
    assert "payoutRefundPools" in results


def test_query_loader_requires_captured_file(tmp_path):
    with pytest.raises(HkjcQueryMissingError):
        load_query(tmp_path, "HAD")
    _write_query(tmp_path, "HAD", "had.graphql")
    assert "query HAD" in load_query(tmp_path, "HAD")


def test_query_loader_rejects_empty_non_graphql_and_unknown_key(tmp_path):
    (tmp_path / "had.graphql").write_text("   \n", encoding="utf-8")
    with pytest.raises(HkjcQueryMissingError):
        load_query(tmp_path, "HAD")

    (tmp_path / "had.graphql").write_text('{"not": "graphql"}', encoding="utf-8")
    with pytest.raises(HkjcQueryMissingError):
        load_query(tmp_path, "HAD")

    with pytest.raises(KeyError):
        load_query(tmp_path, "NOT_A_MARKET")


# ---------------------------------------------------------------------------
# Live odds shape
# ---------------------------------------------------------------------------


def test_parse_live_had_odds():
    payload = HkjcAdapter.parse_market_odds(
        HAD_PAYLOAD, MarketType.HAD, match_source_id="50079081"
    )
    assert payload.match_source_id == "50079081"
    assert payload.pool_status == "SELLINGSTARTED"
    assert len(payload.lines) == 3
    by_side = {line.side: line for line in payload.lines}
    assert set(by_side) == {Side.H, Side.D, Side.A}
    assert by_side[Side.H].odds_decimal == Decimal("4.00")
    assert by_side[Side.A].odds_decimal == Decimal("2.09")
    assert by_side[Side.D].odds_decimal == Decimal("2.42")
    for line in payload.lines:
        assert line.odds_type is MarketType.HAD
        assert line.condition_raw == "0.0"
        assert line.line_status == "AVAILABLE"
        assert line.pool_status == "SELLINGSTARTED"
        assert line.is_main is True
        assert line.offer_early_settlement is True
        assert line.offer_early_settlement_raw == "Offer"
        assert line.source_update_at is not None


def test_parse_live_hdc_only_available_line():
    payload = HkjcAdapter.parse_market_odds(
        HDC_PAYLOAD, MarketType.HDC, match_source_id="50079081"
    )
    assert len(payload.lines) == 2
    assert {line.condition_raw for line in payload.lines} == {"0.0/+0.5"}
    assert {line.side for line in payload.lines} == {Side.H, Side.A}
    assert {line.odds_decimal for line in payload.lines} == {
        Decimal("1.92"),
        Decimal("1.80"),
    }
    assert all(line.line_status == "AVAILABLE" for line in payload.lines)


def test_parse_live_hil_keeps_mixed_and_split_conditions():
    payload = HkjcAdapter.parse_market_odds(
        HIL_PAYLOAD, MarketType.HIL, match_source_id="50079081"
    )
    assert len(payload.lines) == 6
    assert {line.condition_raw for line in payload.lines} == {
        "1.5",
        "1.0/1.5",
        "2.5",
    }
    assert {line.side for line in payload.lines} == {Side.H, Side.L}
    assert {Decimal("2.02"), Decimal("1.70"), Decimal("1.71"), Decimal("2.01")} <= {
        line.odds_decimal for line in payload.lines
    }
    assert all(line.line_status == "AVAILABLE" for line in payload.lines)


def test_parse_live_had_selects_match_id_when_payload_has_many_matches():
    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_market_odds(HAD_PAYLOAD, MarketType.HAD)
    stopped = HkjcAdapter.parse_market_odds(
        HAD_PAYLOAD, MarketType.HAD, match_source_id="50078674"
    )
    assert stopped.pool_status == "SELLINGSTOPPED"
    assert stopped.lines == ()


def test_parse_rejects_missing_pool_and_unknown_match():
    missing = HkjcAdapter.parse_market_odds(
        HAD_PAYLOAD, MarketType.HIL, match_source_id="50079081"
    )
    assert missing.match_source_id == "50079081"
    assert missing.pool_status == "NOT_OFFERED"
    assert missing.lines == ()
    assert missing.source_update_at is None
    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_market_odds(
            HAD_PAYLOAD, MarketType.HAD, match_source_id="99999999"
        )


# ---------------------------------------------------------------------------
# Live scheduled matches shape
# ---------------------------------------------------------------------------


def test_parse_scheduled_matches_from_live_fixture():
    scheduled = HkjcAdapter.parse_scheduled_matches(HAD_PAYLOAD)
    by_id = {match.match_source_id: match for match in scheduled}
    assert set(by_id) == {
        "50079081",
        "50078673",
        "50078674",
        "50078850",
        "50078697",
    }

    rpl = by_id["50079081"]
    assert rpl.home_name == "Rodina Moscow"
    assert rpl.away_name == "FK Krasnodar"
    assert rpl.kickoff_at == datetime(2026, 10, 31, 16, 45, tzinfo=UTC)
    assert rpl.tournament_code == "RPL"
    assert rpl.status == "FIRSTHALFCOMPLETED"

    epl = by_id["50078674"]
    assert epl.home_name == "Tottenham"
    assert epl.away_name == "Crystal Palace"
    assert epl.kickoff_at == datetime(2026, 10, 31, 17, 30, tzinfo=UTC)
    assert epl.tournament_code == "EPL"
    assert epl.status == "FIRSTHALF"


def test_parse_scheduled_matches_rejects_malformed_matches():
    missing_kickoff = copy.deepcopy(HAD_PAYLOAD)
    del missing_kickoff["data"]["matches"][0]["kickOffTime"]
    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_scheduled_matches(missing_kickoff)

    missing_home = copy.deepcopy(HAD_PAYLOAD)
    missing_home["data"]["matches"][0]["homeTeam"]["name_en"] = ""
    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_scheduled_matches(missing_home)

    missing_matches = {"data": {}}
    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_scheduled_matches(missing_matches)


def test_parse_rejects_invalid_side_for_market():
    payload = copy.deepcopy(HDC_PAYLOAD)
    payload["data"]["matches"][0]["foPools"][0]["lines"][0]["combinations"][0]["str"] = "D"
    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_market_odds(payload, MarketType.HDC, match_source_id="50079081")

    payload["data"]["matches"][0]["foPools"][0]["lines"][0]["combinations"][0]["str"] = "X"
    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_market_odds(payload, MarketType.HDC, match_source_id="50079081")


def test_parse_rejects_malformed_odds():
    payload = copy.deepcopy(HAD_PAYLOAD)
    payload["data"]["matches"][0]["foPools"][0]["lines"][0]["combinations"][0][
        "currentOdds"
    ] = "not-a-price"
    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_market_odds(payload, MarketType.HAD, match_source_id="50079081")


def test_parse_skips_suspended_combinations():
    payload = _odds_payload(
        "M-1",
        [
            _line(
                "0.0",
                [
                    _combo("H", "2.00", status="AVAILABLE"),
                    _combo("D", "3.30", status="SUSPENDED"),
                    _combo("A", "3.60", status="AVAILABLE"),
                ],
            )
        ],
    )
    parsed = HkjcAdapter.parse_market_odds(payload, MarketType.HAD, match_source_id="M-1")
    assert {line.side for line in parsed.lines} == {Side.H, Side.A}


def test_offer_early_settlement_accepts_live_strings_and_bools():
    payload = _odds_payload(
        "M-1",
        [
            _line("0.0", [_combo("H", "2.00", offer="Offer")]),
            _line("1.0", [_combo("H", "2.10", offer="NoOffer")]),
            _line("2.0", [_combo("H", "2.20", offer="TempNotOffer")]),
            _line("3.0", [_combo("H", "2.30", offer=True)]),
            _line("4.0", [_combo("H", "2.40", offer=False)]),
        ],
    )
    parsed = HkjcAdapter.parse_market_odds(payload, MarketType.HAD, match_source_id="M-1")
    offers = {line.condition_raw: line.offer_early_settlement for line in parsed.lines}
    assert offers == {
        "0.0": True,
        "1.0": False,
        "2.0": False,
        "3.0": True,
        "4.0": False,
    }
    raw_offers = {
        line.condition_raw: line.offer_early_settlement_raw for line in parsed.lines
    }
    assert raw_offers == {
        "0.0": "Offer",
        "1.0": "NoOffer",
        "2.0": "TempNotOffer",
        "3.0": None,
        "4.0": None,
    }


def test_unknown_offer_early_settlement_value_fails_closed():
    payload = _odds_payload(
        "M-1", [_line("0.0", [_combo("H", "2.00", offer="SomethingElse")])]
    )
    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_market_odds(payload, MarketType.HAD, match_source_id="M-1")


def test_pool_not_selling_returns_no_bettable_lines():
    payload = copy.deepcopy(HAD_PAYLOAD)
    payload["data"]["matches"][0]["foPools"][0]["status"] = "SUSPENDED"
    parsed = HkjcAdapter.parse_market_odds(
        payload, MarketType.HAD, match_source_id="50079081"
    )
    assert parsed.pool_status == "SUSPENDED"
    assert parsed.lines == ()


def test_whitelist_error_is_explicit():
    with pytest.raises(HkjcWhitelistError):
        HkjcAdapter.parse_market_odds(WHITELIST_PAYLOAD, MarketType.HAD)


# ---------------------------------------------------------------------------
# Live results shape
# ---------------------------------------------------------------------------


def test_parse_live_results_selects_full_time_stage():
    result = HkjcAdapter.parse_match_results(RESULTS_PAYLOAD, match_source_id="50078622")
    assert result.match_source_id == "50078622"
    assert result.payout_confirmed is True
    assert result.raw_home_result == 4
    assert result.raw_away_result == 1
    assert result.result_stage_id == 5
    assert result.result_type == 1
    assert result.result_sequence == 306
    assert result.source_update_at is None


def test_parse_live_results_filters_by_match_id():
    first = HkjcAdapter.parse_match_results(RESULTS_PAYLOAD, match_source_id="50078606")
    assert (first.raw_home_result, first.raw_away_result) == (1, 0)
    assert first.result_sequence == 10

    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_match_results(RESULTS_PAYLOAD)
    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_match_results(RESULTS_PAYLOAD, match_source_id="99999999")


def test_live_payout_refund_pools_are_not_refund_markets():
    result = HkjcAdapter.parse_match_results(RESULTS_PAYLOAD, match_source_id="50078622")
    assert result.refund_pool_codes == ()
    assert {"HAD", "HDC", "HIL"} <= set(result.payout_refund_pool_codes)
    assert HkjcAdapter.refunded_markets(result) == frozenset()


def test_match_level_refund_pools_accept_strings_and_objects():
    payload = _results_payload(
        "M-2",
        [_ft_result(1, 0, sequence=7)],
        payout_refund_pools=[{"poolCode": "HAD"}],
        refund_pools=["HDC", {"code": "HIL"}],
    )
    result = HkjcAdapter.parse_match_results(payload, match_source_id="M-2")
    assert result.payout_refund_pool_codes == ("HAD",)
    assert result.refund_pool_codes == ("HDC", "HIL")
    assert HkjcAdapter.refunded_markets(result) == frozenset(
        {MarketType.HDC, MarketType.HIL}
    )


def test_unmodelled_refund_codes_are_ignored():
    payload = _results_payload(
        "M-3", [_ft_result(1, 0, sequence=7)], refund_pools=["FHA", "HDC"]
    )
    result = HkjcAdapter.parse_match_results(payload, match_source_id="M-3")
    assert HkjcAdapter.refunded_markets(result) == frozenset({MarketType.HDC})


def test_parse_results_requires_confirmed_valid_full_time_row():
    unconfirmed = _results_payload(
        "M-4", [_ft_result(2, 1, sequence=9, payout_confirmed=False)]
    )
    result = HkjcAdapter.parse_match_results(unconfirmed, match_source_id="M-4")
    assert result.payout_confirmed is False
    assert result.raw_home_result is None
    assert result.raw_away_result is None
    assert result.result_stage_id is None
    assert (
        HkjcAdapter.goals_90_from_result(
            result, HkjcResultSemantics.UNVERIFIED, is_ucl=False
        )
        is None
    )

    negative = _results_payload("M-5", [_ft_result(-1, 0, sequence=9)])
    invalid = HkjcAdapter.parse_match_results(negative, match_source_id="M-5")
    assert invalid.raw_home_result is None

    no_results = _results_payload("M-6", [])
    empty = HkjcAdapter.parse_match_results(no_results, match_source_id="M-6")
    assert empty.payout_confirmed is False
    assert empty.raw_home_result is None


def test_parse_results_prefers_highest_full_time_sequence():
    payload = _results_payload(
        "M-7",
        [
            _ft_result(1, 0, sequence=10),
            _ft_result(3, 2, sequence=20),
            _ft_result(9, 9, sequence=30, stage_id=4),
            _ft_result(8, 8, sequence=40, result_type=2),
        ],
    )
    result = HkjcAdapter.parse_match_results(payload, match_source_id="M-7")
    assert (result.raw_home_result, result.raw_away_result) == (3, 2)
    assert result.result_sequence == 20


def test_parse_results_rejects_malformed_refund_shape():
    payload: dict[str, object] = {
        "data": {
            "matchNumByDate": {"total": 1},
            "matches": [
                {
                    "id": "M-10",
                    "matchDate": "2026-10-31+08:00",
                    "results": [_ft_result(1, 0, sequence=1)],
                    "poolInfo": {"refundPools": "HDC"},
                }
            ],
        }
    }
    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_match_results(payload, match_source_id="M-10")


def test_parse_results_rejects_malformed_results_list():
    payload: dict[str, object] = {
        "data": {
            "matchNumByDate": {"total": 1},
            "matches": [
                {
                    "id": "M-8",
                    "matchDate": "2026-10-31+08:00",
                    "results": "not-a-list",
                    "poolInfo": {},
                }
            ],
        }
    }
    with pytest.raises(AdapterSchemaError):
        HkjcAdapter.parse_match_results(payload, match_source_id="M-8")


def test_ucl_result_semantics_gate_blocks_unverified_settlement():
    result = HkjcAdapter.parse_match_results(RESULTS_PAYLOAD, match_source_id="50078622")
    with pytest.raises(HkjcResultSemanticsUnverifiedError):
        HkjcAdapter.goals_90_from_result(
            result, HkjcResultSemantics.UNVERIFIED, is_ucl=True
        )
    assert HkjcAdapter.goals_90_from_result(
        result, HkjcResultSemantics.UNVERIFIED, is_ucl=False
    ) == (4, 1)
    assert HkjcAdapter.goals_90_from_result(
        result, HkjcResultSemantics.REGULATION_TIME, is_ucl=True
    ) == (4, 1)


def test_goals_90_returns_none_when_result_is_missing():
    result = HkjcMatchResult(
        match_source_id="M-9",
        payout_confirmed=False,
        raw_home_result=None,
        raw_away_result=None,
        refund_pool_codes=(),
        source_update_at=None,
    )
    assert (
        HkjcAdapter.goals_90_from_result(
            result, HkjcResultSemantics.UNVERIFIED, is_ucl=True
        )
        is None
    )


# ---------------------------------------------------------------------------
# Fetch behaviour (official query replay)
# ---------------------------------------------------------------------------


def test_adapter_exposes_query_and_schema_versions():
    adapter = HkjcAdapter(
        queries_dir=QUERIES_DIR, query_version="captured-2026-11", limiter=NO_LIMIT
    )
    try:
        assert adapter.query_version == "captured-2026-11"
        assert adapter.schema_version == "graphql-v1"
    finally:
        adapter.close()


@respx.mock
@pytest.mark.parametrize(
    ("market", "odds_types"),
    [
        (MarketType.HAD, ["HAD"]),
        (MarketType.HDC, ["HDC", "EDC"]),
        (MarketType.HIL, ["HIL", "EHL"]),
    ],
)
def test_fetch_market_odds_posts_official_match_list(market, odds_types):
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json=HAD_PAYLOAD)
    )
    adapter = HkjcAdapter(
        queries_dir=QUERIES_DIR, query_version="test-v1", limiter=NO_LIMIT
    )
    try:
        result = adapter.fetch_market_odds(market, "50079081")
    finally:
        adapter.close()
    body = json.loads(route.calls[0].request.content)
    assert body["operationName"] == "matchList"
    assert body["query"].startswith("query matchList")
    assert body["variables"] == {
        "startIndex": 1,
        "endIndex": 1,
        "startDate": None,
        "endDate": None,
        "matchIds": ["50079081"],
        "fbOddsTypes": odds_types,
        "fbOddsTypesM": ["ALL"],
        "inplayOnly": False,
        "featuredMatchesOnly": False,
        "earlySettlementOnly": False,
        "showAllMatch": True,
    }
    assert result.source_name == "hkjc"
    assert result.schema_version == "graphql-v1"
    assert result.payload_hash


@respx.mock
def test_fetch_scheduled_matches_posts_official_match_list():
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json=HAD_PAYLOAD)
    )
    adapter = HkjcAdapter(
        queries_dir=QUERIES_DIR, query_version="test-v1", limiter=NO_LIMIT
    )
    try:
        result = adapter.fetch_scheduled_matches(date(2026, 11, 1), date(2026, 11, 7))
    finally:
        adapter.close()
    body = json.loads(route.calls[0].request.content)
    assert body["operationName"] == "matchList"
    assert body["query"].startswith("query matchList")
    assert body["variables"] == {
        "startIndex": None,
        "endIndex": None,
        "startDate": None,
        "endDate": None,
        "matchIds": None,
        "tournIds": None,
        "fbOddsTypes": ["HAD"],
        "fbOddsTypesM": ["HAD"],
        "inplayOnly": False,
        "featuredMatchesOnly": False,
        "frontEndIds": None,
        "earlySettlementOnly": False,
        "showAllMatch": True,
    }
    assert result.source_name == "hkjc"
    assert result.schema_version == "graphql-v1"


@respx.mock
def test_fetch_scheduled_matches_filters_the_live_all_matches_response():
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json=HAD_PAYLOAD)
    )
    adapter = HkjcAdapter(
        queries_dir=QUERIES_DIR, query_version="test-v1", limiter=NO_LIMIT
    )
    try:
        in_range = adapter.fetch_scheduled_matches(
            date(2026, 11, 1),
            date(2026, 11, 7),
        )
        out_of_range = adapter.fetch_scheduled_matches(
            date(2026, 11, 2),
            date(2026, 11, 7),
        )
    finally:
        adapter.close()

    assert route.call_count == 2
    assert len(HkjcAdapter.parse_scheduled_matches(in_range.payload)) == 5
    assert HkjcAdapter.parse_scheduled_matches(out_of_range.payload) == ()
    assert json.loads(route.calls[0].request.content)["variables"]["startDate"] is None
    assert json.loads(route.calls[0].request.content)["variables"]["endDate"] is None


@respx.mock
def test_fetch_match_results_resolves_date_then_fetches_results():
    match_list = {
        "data": {
            "matches": [
                {
                    "id": "50078622",
                    "matchDate": "2026-10-31+08:00",
                    "foPools": [],
                }
            ]
        }
    }
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=[
            httpx.Response(200, json=match_list),
            httpx.Response(200, json=RESULTS_PAYLOAD),
        ]
    )
    adapter = HkjcAdapter(
        queries_dir=QUERIES_DIR, query_version="test-v1", limiter=NO_LIMIT
    )
    try:
        result = adapter.fetch_match_results("50078622")
    finally:
        adapter.close()

    assert route.call_count == 2
    first = json.loads(route.calls[0].request.content)
    assert first["operationName"] == "matchList"
    assert first["variables"]["matchIds"] == ["50078622"]
    assert first["variables"]["fbOddsTypes"] == ["HAD"]

    second = json.loads(route.calls[1].request.content)
    assert second["operationName"] == "matchResults"
    assert second["query"].startswith("query matchResults")
    assert second["variables"] == {
        "startDate": "2026-10-31",
        "endDate": "2026-10-31",
        "startIndex": 1,
        "endIndex": 10,
        "teamId": None,
    }
    assert result.payload == RESULTS_PAYLOAD


@respx.mock
def test_fetch_match_results_accepts_explicit_date_without_match_list():
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json=RESULTS_PAYLOAD)
    )
    adapter = HkjcAdapter(
        queries_dir=QUERIES_DIR, query_version="test-v1", limiter=NO_LIMIT
    )
    try:
        result = adapter.fetch_match_results(
            "50078622",
            match_date=date(2026, 11, 4),
        )
    finally:
        adapter.close()

    assert route.call_count == 1
    body = json.loads(route.calls[0].request.content)
    assert body["operationName"] == "matchResults"
    assert body["variables"]["startDate"] == "2026-11-04"
    assert body["variables"]["endDate"] == "2026-11-04"
    assert body["variables"]["endIndex"] == 10
    assert result.payload == RESULTS_PAYLOAD


@respx.mock
def test_fetch_match_results_reuses_a_cached_date_page():
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json=RESULTS_PAYLOAD)
    )
    adapter = HkjcAdapter(
        queries_dir=QUERIES_DIR, query_version="test-v1", limiter=NO_LIMIT
    )
    try:
        first = adapter.fetch_match_results(
            "50078622",
            match_date=date(2026, 11, 4),
        )
        second = adapter.fetch_match_results(
            "50078622",
            match_date=date(2026, 11, 4),
        )
    finally:
        adapter.close()

    assert route.call_count == 1
    assert first.payload == second.payload


@respx.mock
def test_fetch_match_results_raises_when_match_absent():
    match_list = {
        "data": {
            "matches": [
                {"id": "999", "matchDate": "2026-10-31+08:00", "foPools": []}
            ]
        }
    }
    results = _results_payload("50078622", [_ft_result(1, 0, sequence=1)])
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=[
            httpx.Response(200, json=match_list),
            httpx.Response(200, json=results),
        ]
    )
    adapter = HkjcAdapter(
        queries_dir=QUERIES_DIR, query_version="test-v1", limiter=NO_LIMIT
    )
    try:
        with pytest.raises(AdapterSchemaError):
            adapter.fetch_match_results("999")
    finally:
        adapter.close()
    assert route.call_count == 2


@respx.mock
def test_fetch_match_results_paginates_until_match_found(monkeypatch):
    monkeypatch.setattr("packages.adapters.hkjc.RESULTS_PAGE_SIZE", 2)
    monkeypatch.setattr("packages.adapters.hkjc.MAX_RESULTS_PAGES", 5)
    match_list = {
        "data": {
            "matches": [
                {"id": "777", "matchDate": "2026-10-31+08:00", "foPools": []}
            ]
        }
    }
    first_page = {
        "data": {
            "matchNumByDate": {"total": 4},
            "matches": [{"id": "111"}, {"id": "222"}],
        }
    }
    second_page = {
        "data": {
            "matchNumByDate": {"total": 4},
            "matches": [{"id": "777"}, {"id": "333"}],
        }
    }
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=[
            httpx.Response(200, json=match_list),
            httpx.Response(200, json=first_page),
            httpx.Response(200, json=second_page),
        ]
    )
    adapter = HkjcAdapter(
        queries_dir=QUERIES_DIR, query_version="test-v1", limiter=NO_LIMIT
    )
    try:
        result = adapter.fetch_match_results("777")
    finally:
        adapter.close()
    assert route.call_count == 3
    second_variables = json.loads(route.calls[2].request.content)["variables"]
    assert second_variables["startIndex"] == 3
    assert second_variables["endIndex"] == 4
    assert result.payload == second_page


@respx.mock
def test_fetch_fails_closed_before_network_when_query_missing(tmp_path):
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json=HAD_PAYLOAD)
    )
    adapter = HkjcAdapter(
        queries_dir=tmp_path, query_version="test-v1", limiter=NO_LIMIT
    )
    try:
        with pytest.raises(HkjcQueryMissingError):
            adapter.fetch_market_odds(MarketType.HAD, "50079081")
        with pytest.raises(HkjcQueryMissingError):
            adapter.fetch_match_results("50079081")
    finally:
        adapter.close()
    assert route.call_count == 0


@respx.mock
def test_fetch_raises_whitelist_error_from_graphql_error_payload():
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json=WHITELIST_PAYLOAD)
    )
    adapter = HkjcAdapter(
        queries_dir=QUERIES_DIR, query_version="test-v1", limiter=NO_LIMIT
    )
    try:
        with pytest.raises(HkjcWhitelistError):
            adapter.fetch_match_results("50079081")
    finally:
        adapter.close()


@respx.mock
def test_fetch_match_results_pages_past_the_first_hundred_matches():
    pages = []
    for page in range(1, 12):
        ids = [f"page-{page}-{index}" for index in range(10)]
        if page == 11:
            ids[0] = "50079754"
        pages.append(
            {
                "data": {
                    "matchNumByDate": {"total": 110},
                    "matches": [{"id": match_id} for match_id in ids],
                }
            }
        )
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=[httpx.Response(200, json=payload) for payload in pages]
    )
    adapter = HkjcAdapter(
        queries_dir=QUERIES_DIR, query_version="test-v1", limiter=NO_LIMIT
    )
    try:
        result = adapter.fetch_match_results(
            "50079754", match_date=date(2026, 11, 8)
        )
    finally:
        adapter.close()

    assert route.call_count == 11
    assert result.payload == pages[-1]
