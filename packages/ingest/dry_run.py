from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.adapters.base import FetchResult, hash_text
from packages.adapters.hkjc import LINE_AVAILABLE, POOL_SELLING_STARTED
from packages.db.models import (
    MarketLine,
    Match,
    OddsSnapshot,
    PaperBet,
    RawPayload,
    Settlement,
    Team,
)
from packages.domain.enums import (
    AvailabilityBasis,
    BetStatus,
    MarketType,
    Side,
    SnapshotKind,
)
from packages.ingest.normalize import seed_competitions
from packages.ingest.pipeline import AdapterBundle, IngestPipeline, PipelineError
from packages.ingest.temporal import DecisionMode, TemporalEvidence, evaluate_temporal_gate
from packages.ingest.triggers import (
    DECISION_TRIGGER,
    bet_intent_key,
    compute_trigger_times,
    decision_slot_key,
)
from packages.ledger.service import INITIAL_BANKROLL, LedgerService, PlaceBetRequest
from packages.shared.time import ensure_utc

KICKOFF = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
FETCHED_AT = datetime(2026, 8, 15, 13, 29, 30, tzinfo=UTC)
SNAPSHOT_AT = datetime(2026, 8, 15, 13, 30, tzinfo=UTC)
SETTLED_AT = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)

DRY_RUN_MATCH_KEY = "1001"
DRY_RUN_HKJC_MATCH_ID = "HK-1001"
DRY_RUN_LINE_KEY = "0.0"
DRY_RUN_STAKE = Decimal("100.00")
DRY_RUN_CLOSING_ODDS = Decimal("1.80")
DRY_RUN_FINAL_PROBABILITY = Decimal("0.55")
DRY_RUN_HOME_GOALS_90 = 2
DRY_RUN_AWAY_GOALS_90 = 1
_CLV_QUANTUM = Decimal("0.000001")

DRY_RUN_FD_PAYLOAD = {
    "competition": {"code": "PL"},
    "filters": {"season": "2025"},
    "matches": [
        {
            "id": 1001,
            "utcDate": "2026-08-15T14:00:00Z",
            "status": "SCHEDULED",
            "matchday": 1,
            "homeTeam": {"id": 10, "name": "Arsenal"},
            "awayTeam": {"id": 20, "name": "Chelsea"},
            "score": {"duration": "REGULAR", "fullTime": {"home": None, "away": None}},
        }
    ],
}

DRY_RUN_HKJC_PAYLOADS = {
    MarketType.HAD: {
        "data": {
            "matches": [
                {
                    "id": DRY_RUN_HKJC_MATCH_ID,
                    "foPools": [
                        {
                            "oddsType": "HAD",
                            "status": "SELLINGSTARTED",
                            "updateAt": "2026-08-15T13:29:00Z",
                            "lines": [
                                {
                                    "condition": "0.0",
                                    "status": "AVAILABLE",
                                    "main": True,
                                    "combinations": [
                                        {
                                            "str": "H",
                                            "status": "AVAILABLE",
                                            "offerEarlySettlement": "Offer",
                                            "currentOdds": "2.00",
                                        },
                                        {
                                            "str": "D",
                                            "status": "AVAILABLE",
                                            "offerEarlySettlement": "Offer",
                                            "currentOdds": "3.40",
                                        },
                                        {
                                            "str": "A",
                                            "status": "AVAILABLE",
                                            "offerEarlySettlement": "Offer",
                                            "currentOdds": "3.80",
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }
}


def _make_fetch(
    source_name: str,
    url: str,
    payload: Mapping[str, object],
) -> FetchResult:
    raw_text = json.dumps(payload, sort_keys=True)
    return FetchResult(
        source_name=source_name,
        source_url=url,
        fetched_at=FETCHED_AT,
        http_status=200,
        schema_version="fixture-v1",
        payload=payload,
        payload_hash=hash_text(raw_text),
        raw_text=raw_text,
    )


class _FakeFootballData:
    schema_version: str = "v4"

    def fetch_matches(
        self,
        competition_code: str,
        season_start_year: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> FetchResult:
        return _make_fetch(
            "football-data.org",
            "https://fixture.local/football-data",
            DRY_RUN_FD_PAYLOAD,
        )


class _FakeHkjc:
    schema_version: ClassVar[str] = "graphql-v1"
    query_version: str = "dry-run"

    def fetch_market_odds(
        self,
        market: MarketType,
        match_source_id: str,
    ) -> FetchResult:
        if market is not MarketType.HAD:
            raise AssertionError(f"G1 dry run must not fetch {market.value}")
        return _make_fetch(
            "hkjc",
            f"https://fixture.local/hkjc/{market.value}",
            DRY_RUN_HKJC_PAYLOADS[market],
        )


def _stored_clv(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(_CLV_QUANTUM, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class DryRunResult:
    match_id: str
    bet_id: str
    settlement_status: str
    payout: Decimal
    roi: Decimal
    clv: Decimal | None


def _ensure_teams(session: Session) -> None:
    seeds = {
        "arsenal": ("Arsenal", "ARS", "England"),
        "chelsea": ("Chelsea", "CHE", "England"),
    }
    existing = set(
        session.execute(
            select(Team.slug).where(Team.slug.in_(seeds))
        ).scalars()
    )
    for slug, (name, short_name, country) in seeds.items():
        if slug in existing:
            continue
        session.add(
            Team(
                slug=slug,
                name=name,
                short_name=short_name,
                country=country,
            )
        )
    session.flush()


def _find_dry_run_match(session: Session) -> Match | None:
    matches = list(session.execute(select(Match)).scalars())
    for match in matches:
        if (match.source_match_ids or {}).get("football-data.org") == DRY_RUN_MATCH_KEY:
            return match
    return None


def _require_dry_run_match(session: Session) -> Match:
    match = _find_dry_run_match(session)
    if match is None:
        raise PipelineError("dry-run fixture match was not persisted")
    return match


def _prepare_dry_run_match(match: Match, decision_at: datetime) -> None:
    if ensure_utc(match.kickoff_at) != KICKOFF:
        raise PipelineError(
            f"dry-run fixture kickoff {match.kickoff_at} is not {KICKOFF}"
        )
    match.source_match_ids = {
        **(match.source_match_ids or {}),
        "hkjc": DRY_RUN_HKJC_MATCH_ID,
    }
    if match.first_seen_at is None or ensure_utc(match.first_seen_at) > decision_at:
        # The fixture simulates a prospective capture at T-30m, so first
        # observation must not be later than the frozen decision.
        match.first_seen_at = FETCHED_AT


def _settle(ledger: LedgerService, bet_id: uuid.UUID) -> Settlement:
    return ledger.settle_paper_bet(
        bet_id,
        home_goals_90=DRY_RUN_HOME_GOALS_90,
        away_goals_90=DRY_RUN_AWAY_GOALS_90,
        refunded_markets=frozenset(),
        payout_confirmed=True,
        hk_result_ref=f"dry-run-{DRY_RUN_HKJC_MATCH_ID}",
        closing_odds=DRY_RUN_CLOSING_ODDS,
        final_probability=DRY_RUN_FINAL_PROBABILITY,
        settled_at=SETTLED_AT,
    )


def _result_from_existing(
    session: Session,
    ledger: LedgerService,
    match: Match,
    bet: PaperBet,
) -> DryRunResult:
    if bet.market is not MarketType.HAD:
        raise PipelineError(
            f"existing dry-run bet uses {bet.market.value}; G1 requires HAD"
        )
    settlement = session.execute(
        select(Settlement).where(Settlement.paper_bet_id == bet.id)
    ).scalar_one_or_none()
    if settlement is None:
        if bet.status is not BetStatus.PENDING:
            raise PipelineError(f"bet {bet.id} is {bet.status.value} without a settlement")
        settlement = _settle(ledger, bet.id)
    summary = ledger.summary()
    return DryRunResult(
        match_id=str(match.id),
        bet_id=str(bet.id),
        settlement_status=settlement.result_status.value,
        payout=settlement.payout,
        roi=summary.roi,
        clv=_stored_clv(settlement.clv),
    )


def _assert_decision_evidence(
    session: Session,
    snapshot: OddsSnapshot,
    line: MarketLine,
    decision_at: datetime,
) -> None:
    if snapshot.market is not MarketType.HAD:
        raise PipelineError("decision snapshot must be HAD")
    if ensure_utc(snapshot.snapshot_at) != ensure_utc(decision_at):
        raise PipelineError("decision snapshot is not frozen at decision_at")
    if snapshot.raw_payload_id is None:
        raise PipelineError("decision evidence raw payload id is missing")
    raw = session.get(RawPayload, snapshot.raw_payload_id)
    if raw is None:
        raise PipelineError("decision evidence raw payload was not found")
    first_seen_at = raw.fetched_at
    gate = evaluate_temporal_gate(
        mode=DecisionMode.PROSPECTIVE,
        decision_at=decision_at,
        evidence=TemporalEvidence(
            first_seen_at=first_seen_at,
            available_at=None,
            availability_basis=AvailabilityBasis.OBSERVED_SNAPSHOT,
        ),
    )
    if not gate.allowed:
        raise PipelineError(f"decision-time evidence gate failed: {gate.reason}")
    if line.pool_status != POOL_SELLING_STARTED:
        raise PipelineError(f"decision pool is {line.pool_status}, not selling")
    if line.line_status != LINE_AVAILABLE:
        raise PipelineError(f"decision line is {line.line_status}, not available")


def run_dry_run(
    session: Session,
    *,
    initial_bankroll: Decimal = INITIAL_BANKROLL,
) -> DryRunResult:
    """Run the G1 EPL+HAD dry run as engineering and settlement validation.

    This fixture-driven demo proves the pipeline, frozen T-30m decision time,
    evidence gate, bet idempotency, bankroll reservation and settlement wiring.
    It is not LLM evidence and must never be used to claim predictive ability.
    HDC/HIL are not fetched and cannot create paper bets.
    """
    expected_decision = compute_trigger_times(KICKOFF)[DECISION_TRIGGER]
    decision_at = ensure_utc(SNAPSHOT_AT)
    if decision_at != expected_decision:
        raise PipelineError(
            f"dry-run decision time {decision_at} is not the T-30m trigger {expected_decision}"
        )

    seed_competitions(session)
    _ensure_teams(session)
    pipeline = IngestPipeline(
        session,
        AdapterBundle(football_data=_FakeFootballData(), hkjc=_FakeHkjc()),
    )
    match = _find_dry_run_match(session)
    if match is None:
        _ = pipeline.ingest_fixtures("EPL", 2025)
        match = _require_dry_run_match(session)
    _prepare_dry_run_match(match, decision_at)
    session.flush()

    slot_key = decision_slot_key(match.id)
    intent_key = bet_intent_key(slot_key, MarketType.HAD, DRY_RUN_LINE_KEY, Side.H)
    analysis_run_key = f"dry-analysis:{match.id}"
    ledger = LedgerService(session, initial_bankroll=initial_bankroll)

    existing = session.execute(
        select(PaperBet).where(PaperBet.bet_intent_key == intent_key)
    ).scalar_one_or_none()
    if existing is not None:
        return _result_from_existing(session, ledger, match, existing)

    snapshot, lines = pipeline.ingest_hkjc_odds(
        match,
        MarketType.HAD,
        SnapshotKind.T30M,
        decision_at,
        run_id=f"dry-{MarketType.HAD.value}",
    )
    line = next(
        (
            candidate
            for candidate in lines
            if candidate.condition_raw == DRY_RUN_LINE_KEY
            and candidate.side is Side.H
        ),
        None,
    )
    if line is None:
        raise PipelineError("dry-run HAD home line 0.0 is missing or unavailable")
    _assert_decision_evidence(session, snapshot, line, decision_at)

    bet = ledger.place_bet(
        PlaceBetRequest(
            match_id=match.id,
            market=MarketType.HAD,
            line_key=line.condition_raw,
            selection=Side.H,
            odds_decimal=line.odds_decimal,
            stake=DRY_RUN_STAKE,
            analysis_run_key=analysis_run_key,
            decision_slot_key=slot_key,
            bet_intent_key=intent_key,
            decision_at=decision_at,
            odds_snapshot_id=snapshot.id,
        )
    )
    settlement = _settle(ledger, bet.id)
    summary = ledger.summary()
    return DryRunResult(
        match_id=str(match.id),
        bet_id=str(bet.id),
        settlement_status=settlement.result_status.value,
        payout=settlement.payout,
        roi=summary.roi,
        clv=_stored_clv(settlement.clv),
    )
