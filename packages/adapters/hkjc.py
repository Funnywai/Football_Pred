from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import ClassVar, cast
from zoneinfo import ZoneInfo

import httpx

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
    hash_text,
)
from packages.adapters.hkjc_queries.loader import load_query
from packages.domain.enums import HkjcResultSemantics, MarketType, Side
from packages.domain.errors import InvalidConditionRaw, UnsupportedMarket
from packages.domain.markets import parse_condition_raw, validate_side
from packages.shared.time import parse_iso_utc

DEFAULT_GRAPHQL_URL = "https://info.cld.hkjc.com/graphql/base/"
HONG_KONG = ZoneInfo("Asia/Hong_Kong")

# The official site uses one parameterized matchList query; the group selects
# which pools are requested through fbOddsTypes.
MARKET_ODDS_TYPES: dict[MarketType, tuple[str, ...]] = {
    MarketType.HAD: ("HAD",),
    MarketType.HDC: ("HDC", "EDC"),
    MarketType.HIL: ("HIL", "EHL"),
}

POOL_SELLING_STARTED = "SELLINGSTARTED"
POOL_NOT_OFFERED = "NOT_OFFERED"
LINE_AVAILABLE = "AVAILABLE"
FULL_TIME_STAGE_ID = 5
FULL_TIME_RESULT_TYPE = 1
RESULTS_PAGE_SIZE = 100
MAX_RESULTS_PAGES = 10

_UNKNOWN_STATUS = "UNKNOWN"
_MIN_BETTABLE_ODDS = Decimal(1)
_DEFAULT_LIMITER = MinIntervalRateLimiter(60.0)
_OFFER_TRUE = frozenset({"offer"})
_OFFER_FALSE = frozenset({"nooffer", "tempnotoffer"})


class HkjcWhitelistError(AdapterSchemaError):
    """HKJC rejected a query because it is not on the official whitelist."""


class HkjcResultSemanticsUnverifiedError(AdapterSchemaError):
    """UCL settlement was attempted before result semantics were verified."""


@dataclass(frozen=True)
class HkjcMarketLine:
    odds_type: MarketType
    condition_raw: str
    line_index: int
    side: Side
    odds_decimal: Decimal
    pool_status: str
    line_status: str
    is_main: bool
    offer_early_settlement: bool
    source_update_at: datetime | None
    offer_early_settlement_raw: str | None = None


@dataclass(frozen=True)
class HkjcOddsPayload:
    match_source_id: str
    pool_status: str
    lines: tuple[HkjcMarketLine, ...]
    source_update_at: datetime | None


@dataclass(frozen=True)
class HkjcScheduledMatch:
    match_source_id: str
    kickoff_at: datetime
    home_name: str
    away_name: str
    tournament_code: str | None
    status: str
    tournament_id: str | None = None


@dataclass(frozen=True)
class HkjcMatchResult:
    """Raw HKJC result fields.

    ``raw_home_result`` and ``raw_away_result`` are exactly what HKJC returned.
    They are not labelled as 90-minute goals because that semantics is still a
    verification gate; see :meth:`HkjcAdapter.goals_90_from_result`.

    ``refund_pool_codes`` comes from ``match.poolInfo.refundPools``.
    ``payout_refund_pool_codes`` comes from ``match.poolInfo.payoutRefundPools``,
    which live samples show enumerating every settled pool rather than only
    refunds; it is kept for provenance and must not drive voiding.
    """

    match_source_id: str
    payout_confirmed: bool
    raw_home_result: int | None
    raw_away_result: int | None
    refund_pool_codes: tuple[str, ...]
    source_update_at: datetime | None
    result_stage_id: int | None = None
    result_type: int | None = None
    result_sequence: int | None = None
    payout_refund_pool_codes: tuple[str, ...] = ()


def _as_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AdapterSchemaError(f"{label} must be an object")
    return cast("dict[str, object]", value)


def _as_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise AdapterSchemaError(f"{label} must be a list")
    return cast("list[object]", value)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterSchemaError(f"{label} must be a non-empty string")
    return value.strip()


def _require_match_source_id(value: object) -> str:
    return _require_text(value, "match_source_id")


def _optional_flag(value: object, label: str) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise AdapterSchemaError(f"{label} must be a boolean")


def _offer_early_settlement(value: object, label: str) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _OFFER_TRUE:
            return True
        if normalized in _OFFER_FALSE:
            return False
    raise AdapterSchemaError(f"{label} has unknown offerEarlySettlement {value!r}")


def _optional_timestamp(value: object, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterSchemaError(f"{label} must be an ISO timestamp string")
    try:
        return parse_iso_utc(value)
    except ValueError as exc:
        raise AdapterSchemaError(f"invalid {label} {value!r}") from exc


def _optional_tournament_code(value: object, label: str) -> str | None:
    if value is None:
        return None
    tournament = _as_mapping(value, label)
    raw_code = tournament.get("code")
    if raw_code is None:
        return None
    if not isinstance(raw_code, str):
        raise AdapterSchemaError(f"{label}.code must be a string")
    code = raw_code.strip()
    return code or None


def _optional_tournament_id(value: object, label: str) -> str | None:
    if value is None:
        return None
    tournament = _as_mapping(value, label)
    raw_id = tournament.get("id")
    if raw_id is None:
        return None
    if not isinstance(raw_id, str):
        raise AdapterSchemaError(f"{label}.id must be a string")
    tournament_id = raw_id.strip()
    return tournament_id or None


def _int_or_none(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise AdapterSchemaError(f"{label} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise AdapterSchemaError(f"{label} must be an integer")
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            raise AdapterSchemaError(f"{label} must be an integer") from exc
    raise AdapterSchemaError(f"{label} must be an integer")


def _odds_decimal(value: object, label: str) -> Decimal:
    if value is None:
        raise AdapterSchemaError(f"{label} is missing")
    if isinstance(value, bool):
        raise AdapterSchemaError(f"{label} must be a decimal price")
    try:
        odds = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise AdapterSchemaError(f"{label} is not a decimal price") from exc
    if not odds.is_finite():
        raise AdapterSchemaError(f"{label} must be a finite price")
    return odds


def _coerce_market(value: object) -> MarketType:
    try:
        return MarketType(value)
    except (TypeError, ValueError) as exc:
        raise AdapterSchemaError(f"unsupported HKJC market {value!r}") from exc


def _coerce_semantics(value: object) -> HkjcResultSemantics:
    if isinstance(value, HkjcResultSemantics):
        return value
    try:
        return HkjcResultSemantics(value)
    except (TypeError, ValueError) as exc:
        raise AdapterSchemaError(f"unknown HKJC result semantics {value!r}") from exc


def _raise_on_graphql_errors(payload: object) -> None:
    root = _as_mapping(payload, "payload")
    errors = root.get("errors")
    if not errors:
        return
    if not isinstance(errors, list):
        raise AdapterSchemaError("payload.errors must be a list")
    first = errors[0] if errors else None
    error = first if isinstance(first, dict) else {}
    extensions = error.get("extensions")
    code = extensions.get("code") if isinstance(extensions, dict) else None
    message = error.get("message")
    if code == "WHITELIST_ERROR":
        raise HkjcWhitelistError(f"HKJC rejected query: {message}")
    raise AdapterSchemaError(f"HKJC GraphQL error: {message}")


def _matches_from_payload(payload: object) -> list[object]:
    data = _as_mapping(_as_mapping(payload, "payload").get("data"), "data")
    return _as_list(data.get("matches"), "data.matches")


def _match_num_total(payload: object) -> int | None:
    data = _as_mapping(_as_mapping(payload, "payload").get("data"), "data")
    raw_summary = data.get("matchNumByDate")
    if raw_summary is None:
        return None
    summary = _as_mapping(raw_summary, "data.matchNumByDate")
    return _int_or_none(summary.get("total"), "data.matchNumByDate.total")


def _select_match(matches: list[object], match_source_id: str) -> dict[str, object]:
    target = _require_match_source_id(match_source_id)
    for raw_match in matches:
        match = _as_mapping(raw_match, "data.matches[]")
        if str(match.get("id")) == target:
            return match
    raise AdapterSchemaError(f"match {target} not found in data.matches")


def _select_one_match(
    matches: list[object], match_source_id: str | None
) -> dict[str, object]:
    if match_source_id is not None:
        return _select_match(matches, match_source_id)
    if len(matches) == 1:
        return _as_mapping(matches[0], "data.matches[0]")
    raise AdapterSchemaError(
        "match_source_id is required when data.matches has multiple matches"
    )


def _match_date(match: dict[str, object]) -> str:
    raw = _require_text(match.get("matchDate"), "data.matches[].matchDate")
    candidate = raw[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError as exc:
        raise AdapterSchemaError(f"invalid matchDate {raw!r}") from exc


def _match_local_date(raw_match: object) -> date:
    match = _as_mapping(raw_match, "data.matches[]")
    raw_date = match.get("matchDate")
    if isinstance(raw_date, str) and len(raw_date) >= 10:
        try:
            return date.fromisoformat(raw_date[:10])
        except ValueError:
            pass
    kickoff_at = _optional_timestamp(
        match.get("kickOffTime"), "data.matches[].kickOffTime"
    )
    if kickoff_at is None:
        raise AdapterSchemaError("data.matches[].kickOffTime is missing")
    return kickoff_at.astimezone(HONG_KONG).date()


def _extract_pool_codes(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise AdapterSchemaError(f"{label} must be a list")
    codes: set[str] = set()
    for item in value:
        if isinstance(item, str):
            code = item.strip()
        elif isinstance(item, dict):
            raw_code = item.get("poolCode") or item.get("oddsType") or item.get("code")
            code = str(raw_code).strip() if raw_code is not None else ""
        else:
            raise AdapterSchemaError(f"{label} entries must be strings or objects")
        if code:
            codes.add(code)
    return tuple(sorted(codes))


def _select_full_time_result(
    results: list[object],
) -> tuple[int, int, int, int, int] | None:
    """Pick the confirmed full-time row: resultType=1, stageId=5, sequence desc."""
    candidates: list[tuple[int, int, int, int, int, int]] = []
    for index, raw_result in enumerate(results):
        row = _as_mapping(raw_result, f"data.matches[].results[{index}]")
        result_type = _int_or_none(row.get("resultType"), "result.resultType")
        stage_id = _int_or_none(row.get("stageId"), "result.stageId")
        if result_type != FULL_TIME_RESULT_TYPE or stage_id != FULL_TIME_STAGE_ID:
            continue
        if not _optional_flag(row.get("payoutConfirmed"), "result.payoutConfirmed"):
            continue
        home = _int_or_none(row.get("homeResult"), "result.homeResult")
        away = _int_or_none(row.get("awayResult"), "result.awayResult")
        if home is None or away is None or home < 0 or away < 0:
            continue
        sequence = _int_or_none(row.get("sequence"), "result.sequence") or 0
        candidates.append((sequence, index, home, away, stage_id, result_type))
    if not candidates:
        return None
    sequence, _, home, away, stage_id, result_type = max(
        candidates, key=lambda item: (item[0], item[1])
    )
    return home, away, stage_id, result_type, sequence


class HkjcAdapter(BaseAdapter):
    name: ClassVar[str] = "hkjc"
    tos_risk: ClassVar[str] = "medium"
    schema_version: ClassVar[str] = "graphql-v1"

    def __init__(
        self,
        queries_dir: Path,
        query_version: str,
        graphql_url: str = DEFAULT_GRAPHQL_URL,
        client: httpx.Client | None = None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else _DEFAULT_LIMITER,
        )
        self._queries_dir: Path = Path(queries_dir)
        self._graphql_url: str = graphql_url
        self.query_version: str = query_version

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Origin": "https://bet.hkjc.com",
            "Referer": "https://bet.hkjc.com/football",
        }

    @staticmethod
    def _scheduled_match_list_variables(
        start_index: int | None,
        end_index: int | None,
    ) -> dict[str, object]:
        return {
            "startIndex": start_index,
            "endIndex": end_index,
            # The whitelisted matchList resolver rejects startDate/endDate; the
            # official site sends null and filters the returned list locally.
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

    @staticmethod
    def _match_list_variables(
        market: MarketType, match_source_id: str
    ) -> dict[str, object]:
        return {
            "startIndex": 1,
            "endIndex": 1,
            "startDate": None,
            "endDate": None,
            "matchIds": [match_source_id],
            "fbOddsTypes": list(MARKET_ODDS_TYPES[market]),
            "fbOddsTypesM": ["ALL"],
            "inplayOnly": False,
            "featuredMatchesOnly": False,
            "earlySettlementOnly": False,
            "showAllMatch": True,
        }

    def _post_match_list(
        self, market: MarketType, match_source_id: str
    ) -> FetchResult:
        query = load_query(self._queries_dir, market.value)
        body = {
            "operationName": "matchList",
            "variables": self._match_list_variables(market, match_source_id),
            "query": query,
        }
        result = self._post_json(
            self._graphql_url,
            json_body=body,
            headers=self._headers(),
        )
        _raise_on_graphql_errors(result.payload)
        return result

    def _post_scheduled_matches_page(
        self,
        start_index: int | None,
        end_index: int | None,
    ) -> FetchResult:
        query = load_query(self._queries_dir, "HAD")
        body = {
            "operationName": "matchList",
            "variables": self._scheduled_match_list_variables(
                start_index,
                end_index,
            ),
            "query": query,
        }
        result = self._post_json(
            self._graphql_url,
            json_body=body,
            headers=self._headers(),
        )
        _raise_on_graphql_errors(result.payload)
        return result

    def fetch_scheduled_matches(
        self,
        start_date: date,
        end_date: date,
        *,
        start_index: int | None = None,
        end_index: int | None = None,
    ) -> FetchResult:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        result = self._post_scheduled_matches_page(start_index, end_index)
        matches = _matches_from_payload(result.payload)
        filtered = [
            match
            for match in matches
            if start_date <= _match_local_date(match) <= end_date
        ]
        if len(filtered) == len(matches):
            return result
        payload = copy.deepcopy(result.payload)
        data = _as_mapping(payload.get("data"), "data")
        data["matches"] = filtered
        raw_text = json.dumps(payload, sort_keys=True)
        return FetchResult(
            source_name=result.source_name,
            source_url=result.source_url,
            fetched_at=result.fetched_at,
            http_status=result.http_status,
            schema_version=result.schema_version,
            payload=payload,
            payload_hash=hash_text(raw_text),
            raw_text=raw_text,
        )

    def _post_match_results(
        self, match_date: str, start_index: int, end_index: int
    ) -> FetchResult:
        query = load_query(self._queries_dir, "matchResults")
        body = {
            "operationName": "matchResults",
            "variables": {
                "startDate": match_date,
                "endDate": match_date,
                "startIndex": start_index,
                "endIndex": end_index,
                "teamId": None,
            },
            "query": query,
        }
        result = self._post_json(
            self._graphql_url,
            json_body=body,
            headers=self._headers(),
        )
        _raise_on_graphql_errors(result.payload)
        return result

    def fetch_market_odds(
        self,
        market: MarketType,
        match_source_id: str,
    ) -> FetchResult:
        parsed_market = _coerce_market(market)
        parsed_match_id = _require_match_source_id(match_source_id)
        return self._post_match_list(parsed_market, parsed_match_id)

    def _resolve_match_date(self, match_source_id: str) -> str:
        result = self._post_match_list(MarketType.HAD, match_source_id)
        matches = _matches_from_payload(result.payload)
        return _match_date(_select_match(matches, match_source_id))

    def fetch_match_results(self, match_source_id: str) -> FetchResult:
        parsed_match_id = _require_match_source_id(match_source_id)
        match_date = self._resolve_match_date(parsed_match_id)
        start_index = 1
        for _ in range(MAX_RESULTS_PAGES):
            result = self._post_match_results(
                match_date, start_index, start_index + RESULTS_PAGE_SIZE - 1
            )
            matches = _matches_from_payload(result.payload)
            for raw_match in matches:
                match = _as_mapping(raw_match, "data.matches[]")
                if str(match.get("id")) == parsed_match_id:
                    return result
            if not matches:
                break
            next_index = start_index + len(matches)
            total = _match_num_total(result.payload)
            if total is not None:
                if next_index > total:
                    break
            elif len(matches) < RESULTS_PAGE_SIZE:
                break
            start_index = next_index
        raise AdapterSchemaError(
            f"match {parsed_match_id} not found in matchResults for {match_date}"
        )

    @staticmethod
    def parse_scheduled_matches(payload: dict[str, object]) -> tuple[HkjcScheduledMatch, ...]:
        _raise_on_graphql_errors(payload)
        matches = _matches_from_payload(payload)
        scheduled: list[HkjcScheduledMatch] = []
        for index, raw_match in enumerate(matches):
            label = f"data.matches[{index}]"
            match = _as_mapping(raw_match, label)
            kickoff_at = _optional_timestamp(
                match.get("kickOffTime"), f"{label}.kickOffTime"
            )
            if kickoff_at is None:
                raise AdapterSchemaError(f"{label}.kickOffTime is missing")
            home = _as_mapping(match.get("homeTeam"), f"{label}.homeTeam")
            away = _as_mapping(match.get("awayTeam"), f"{label}.awayTeam")
            scheduled.append(
                HkjcScheduledMatch(
                    match_source_id=_require_text(match.get("id"), f"{label}.id"),
                    kickoff_at=kickoff_at,
                    home_name=_require_text(home.get("name_en"), f"{label}.homeTeam.name_en"),
                    away_name=_require_text(away.get("name_en"), f"{label}.awayTeam.name_en"),
                    tournament_code=_optional_tournament_code(
                        match.get("tournament"), f"{label}.tournament"
                    ),
                    status=_require_text(match.get("status"), f"{label}.status"),
                    tournament_id=_optional_tournament_id(
                        match.get("tournament"), f"{label}.tournament"
                    ),
                )
            )
        return tuple(scheduled)

    @staticmethod
    def parse_market_odds(
        payload: dict[str, object],
        expected_market: MarketType,
        match_source_id: str | None = None,
    ) -> HkjcOddsPayload:
        _raise_on_graphql_errors(payload)
        market = _coerce_market(expected_market)
        matches = _matches_from_payload(payload)
        match = _select_one_match(matches, match_source_id)
        match_id = _require_text(match.get("id"), "data.matches[].id")
        raw_pools = match.get("foPools")
        pools = (
            []
            if raw_pools is None
            else _as_list(raw_pools, "data.matches[].foPools")
        )
        pool: dict[str, object] | None = None
        for raw_pool in pools:
            candidate = _as_mapping(raw_pool, "data.matches[].foPools[]")
            if candidate.get("oddsType") == market.value:
                pool = candidate
                break
        if pool is None:
            return HkjcOddsPayload(
                match_source_id=match_id,
                pool_status=POOL_NOT_OFFERED,
                lines=(),
                source_update_at=None,
            )
        pool_status = str(pool.get("status") or _UNKNOWN_STATUS)
        pool_update = _optional_timestamp(pool.get("updateAt"), "pool.updateAt")
        if pool_status != POOL_SELLING_STARTED:
            return HkjcOddsPayload(
                match_source_id=match_id,
                pool_status=pool_status,
                lines=(),
                source_update_at=pool_update,
            )
        lines: list[HkjcMarketLine] = []
        raw_lines = _as_list(pool.get("lines"), "pool.lines")
        for index, raw_line in enumerate(raw_lines):
            label = f"pool.lines[{index}]"
            line = _as_mapping(raw_line, label)
            condition_raw = _require_text(line.get("condition"), f"{label}.condition")
            try:
                _ = parse_condition_raw(condition_raw)
            except InvalidConditionRaw:
                # An unparseable line cannot be graded, so it never becomes bettable.
                continue
            line_status = str(line.get("status") or _UNKNOWN_STATUS)
            if line_status != LINE_AVAILABLE:
                continue
            line_update = (
                _optional_timestamp(line.get("updateAt"), f"{label}.updateAt")
                or pool_update
            )
            is_main = _optional_flag(line.get("main"), f"{label}.main")
            combinations = _as_list(
                line.get("combinations"), f"{label}.combinations"
            )
            for combo_index, raw_combo in enumerate(combinations):
                combo_label = f"{label}.combinations[{combo_index}]"
                combo = _as_mapping(raw_combo, combo_label)
                if str(combo.get("status") or _UNKNOWN_STATUS) != LINE_AVAILABLE:
                    continue
                side_text = _require_text(combo.get("str"), f"{combo_label}.str")
                try:
                    side = Side(side_text)
                except ValueError as exc:
                    raise AdapterSchemaError(
                        f"{combo_label}.str {side_text!r} is not a HKJC side"
                    ) from exc
                try:
                    validate_side(market, side)
                except UnsupportedMarket as exc:
                    raise AdapterSchemaError(
                        f"{side.value} is not a valid outcome for {market.value}"
                    ) from exc
                odds = _odds_decimal(
                    combo.get("currentOdds"), f"{combo_label}.currentOdds"
                )
                if odds <= _MIN_BETTABLE_ODDS:
                    continue
                raw_offer = combo.get("offerEarlySettlement")
                lines.append(
                    HkjcMarketLine(
                        odds_type=market,
                        condition_raw=condition_raw,
                        line_index=index,
                        side=side,
                        odds_decimal=odds,
                        pool_status=pool_status,
                        line_status=line_status,
                        is_main=is_main,
                        offer_early_settlement=_offer_early_settlement(
                            raw_offer, f"{combo_label}.offerEarlySettlement"
                        ),
                        source_update_at=line_update,
                        offer_early_settlement_raw=(
                            raw_offer.strip() if isinstance(raw_offer, str) else None
                        ),
                    )
                )
        return HkjcOddsPayload(
            match_source_id=match_id,
            pool_status=pool_status,
            lines=tuple(lines),
            source_update_at=pool_update,
        )

    @staticmethod
    def parse_match_results(
        payload: dict[str, object],
        match_source_id: str | None = None,
    ) -> HkjcMatchResult:
        _raise_on_graphql_errors(payload)
        matches = _matches_from_payload(payload)
        match = _select_one_match(matches, match_source_id)
        match_id = _require_text(match.get("id"), "data.matches[].id")
        raw_results = match.get("results")
        results = (
            []
            if raw_results is None
            else _as_list(raw_results, "data.matches[].results")
        )
        selected = _select_full_time_result(results)
        raw_pool_info = match.get("poolInfo")
        pool_info = (
            {}
            if raw_pool_info is None
            else _as_mapping(raw_pool_info, "data.matches[].poolInfo")
        )
        refund_codes = _extract_pool_codes(
            pool_info.get("refundPools"), "poolInfo.refundPools"
        )
        payout_refund_codes = _extract_pool_codes(
            pool_info.get("payoutRefundPools"), "poolInfo.payoutRefundPools"
        )
        if selected is None:
            return HkjcMatchResult(
                match_source_id=match_id,
                payout_confirmed=False,
                raw_home_result=None,
                raw_away_result=None,
                refund_pool_codes=refund_codes,
                source_update_at=None,
                payout_refund_pool_codes=payout_refund_codes,
            )
        home, away, stage_id, result_type, sequence = selected
        return HkjcMatchResult(
            match_source_id=match_id,
            payout_confirmed=True,
            raw_home_result=home,
            raw_away_result=away,
            refund_pool_codes=refund_codes,
            source_update_at=None,
            result_stage_id=stage_id,
            result_type=result_type,
            result_sequence=sequence,
            payout_refund_pool_codes=payout_refund_codes,
        )

    @staticmethod
    def goals_90_from_result(
        result: HkjcMatchResult,
        semantics: HkjcResultSemantics,
        *,
        is_ucl: bool,
    ) -> tuple[int, int] | None:
        """Return goals usable for 90-minute settlement, or ``None``.

        HKJC ``homeResult``/``awayResult`` are not assumed to be 90-minute scores.
        UCL settlement stays blocked until ``semantics`` is explicitly verified as
        ``REGULATION_TIME``.
        """
        parsed_semantics = _coerce_semantics(semantics)
        if result.raw_home_result is None or result.raw_away_result is None:
            return None
        if is_ucl and parsed_semantics is not HkjcResultSemantics.REGULATION_TIME:
            raise HkjcResultSemanticsUnverifiedError(
                "UCL result semantics are unverified; refusing to settle UCL"
            )
        return result.raw_home_result, result.raw_away_result

    @staticmethod
    def refunded_markets(result: HkjcMatchResult) -> frozenset[MarketType]:
        """Markets actually refunded according to ``poolInfo.refundPools``.

        ``payoutRefundPools`` is intentionally excluded: live data shows it
        listing every settled pool, including HAD/HDC/HIL on normal results.
        """
        markets: set[MarketType] = set()
        for code in result.refund_pool_codes:
            try:
                markets.add(MarketType(code))
            except ValueError:
                # Refunds can reference HKJC markets this system does not model.
                continue
        return frozenset(markets)
