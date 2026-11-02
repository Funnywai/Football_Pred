import inspect
from datetime import UTC, date, datetime
from typing import cast

import pytest

from packages.domain.enums import AvailabilityBasis, SourceStatus, UclCoverageLevel
from packages.ingest.temporal import (
    DecisionMode,
    SourceVerification,
    TemporalEvidence,
    can_mark_verified,
    classify_ucl_coverage,
    evaluate_temporal_gate,
    resolve_historical_availability,
)

DECISION = datetime(2026, 8, 15, 13, 30, tzinfo=UTC)
VERIFICATION_DATE = date(2026, 8, 1)


def _evidence(
    *,
    first_seen_at: datetime | None = None,
    available_at: datetime | None = None,
    availability_basis: AvailabilityBasis = AvailabilityBasis.OBSERVED_SNAPSHOT,
) -> TemporalEvidence:
    return TemporalEvidence(
        first_seen_at=first_seen_at,
        available_at=available_at,
        availability_basis=availability_basis,
    )


def _verification(
    *,
    status: SourceStatus = SourceStatus.VERIFIED,
    verification_date: date | None = VERIFICATION_DATE,
    schema_scope: str | None = "fixtures and results",
    field_scope: str | None = "score, kickoff, teams",
    test_evidence_ref: str | None = "tests/adapters/test_football_data_org.py",
    licensing_check: str | None = "allowed for personal research",
) -> SourceVerification:
    return SourceVerification(
        status=status,
        verification_date=verification_date,
        schema_scope=schema_scope,
        field_scope=field_scope,
        test_evidence_ref=test_evidence_ref,
        licensing_check=licensing_check,
    )


def test_prospective_allows_first_seen_before_decision():
    result = evaluate_temporal_gate(
        mode=DecisionMode.PROSPECTIVE,
        decision_at=DECISION,
        evidence=_evidence(first_seen_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC)),
    )
    assert result.allowed is True
    assert result.reason == "ok"


def test_prospective_allows_first_seen_exactly_at_decision():
    result = evaluate_temporal_gate(
        mode=DecisionMode.PROSPECTIVE,
        decision_at=DECISION,
        evidence=_evidence(first_seen_at=DECISION),
    )
    assert result.allowed is True


def test_prospective_rejects_first_seen_after_decision():
    result = evaluate_temporal_gate(
        mode=DecisionMode.PROSPECTIVE,
        decision_at=DECISION,
        evidence=_evidence(first_seen_at=datetime(2026, 8, 15, 14, 0, tzinfo=UTC)),
    )
    assert result.allowed is False
    assert result.reason == "first_seen_after_decision"


def test_prospective_rejects_missing_first_seen():
    result = evaluate_temporal_gate(
        mode=DecisionMode.PROSPECTIVE,
        decision_at=DECISION,
        evidence=_evidence(first_seen_at=None),
    )
    assert result.allowed is False
    assert result.reason == "first_seen_at_missing"


def test_retrospective_allows_primary_basis():
    result = evaluate_temporal_gate(
        mode=DecisionMode.RETROSPECTIVE,
        decision_at=DECISION,
        evidence=_evidence(
            available_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
            availability_basis=AvailabilityBasis.PROVIDER_POINT_IN_TIME,
        ),
    )
    assert result.allowed is True


def test_retrospective_rejects_assumed_basis():
    result = evaluate_temporal_gate(
        mode=DecisionMode.RETROSPECTIVE,
        decision_at=DECISION,
        evidence=_evidence(
            available_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
            availability_basis=AvailabilityBasis.AVAILABILITY_ASSUMED,
        ),
    )
    assert result.allowed is False
    assert result.reason == "non_primary_availability_basis"


def test_retrospective_rejects_missing_available_at():
    result = evaluate_temporal_gate(
        mode=DecisionMode.RETROSPECTIVE,
        decision_at=DECISION,
        evidence=_evidence(available_at=None),
    )
    assert result.allowed is False
    assert result.reason == "available_at_missing"


def test_retrospective_rejects_available_after_decision():
    result = evaluate_temporal_gate(
        mode=DecisionMode.RETROSPECTIVE,
        decision_at=DECISION,
        evidence=_evidence(available_at=datetime(2026, 8, 15, 14, 0, tzinfo=UTC)),
    )
    assert result.allowed is False
    assert result.reason == "available_after_decision"


def test_unknown_decision_mode_fails_closed():
    bad_mode = cast(object, "unknown")
    with pytest.raises(ValueError):
        evaluate_temporal_gate(
            mode=cast(DecisionMode, bad_mode),
            decision_at=DECISION,
            evidence=_evidence(first_seen_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC)),
        )


def test_historical_availability_never_uses_first_seen():
    parameters = inspect.signature(resolve_historical_availability).parameters
    assert "first_seen_at" not in parameters
    available_at, basis = resolve_historical_availability(
        observed_snapshot_at=None,
        provider_point_in_time=None,
    )
    assert available_at is None
    assert basis is AvailabilityBasis.UNAVAILABLE


def test_historical_availability_prefers_observed_snapshot():
    observed = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    provider = datetime(2026, 8, 15, 11, 0, tzinfo=UTC)
    available_at, basis = resolve_historical_availability(
        observed_snapshot_at=observed,
        provider_point_in_time=provider,
    )
    assert available_at == observed
    assert basis is AvailabilityBasis.OBSERVED_SNAPSHOT


def test_historical_availability_falls_back_to_provider_point_in_time():
    provider = datetime(2026, 8, 15, 11, 0, tzinfo=UTC)
    available_at, basis = resolve_historical_availability(
        observed_snapshot_at=None,
        provider_point_in_time=provider,
    )
    assert available_at == provider
    assert basis is AvailabilityBasis.PROVIDER_POINT_IN_TIME


def test_ucl_coverage_levels():
    insufficient = classify_ucl_coverage(
        has_settleable_result=False,
        has_target_market_odds=True,
        has_xg=False,
        lineup_dependent=False,
        has_lineup_fallback=False,
    )
    reduced = classify_ucl_coverage(
        has_settleable_result=True,
        has_target_market_odds=True,
        has_xg=False,
        lineup_dependent=False,
        has_lineup_fallback=True,
    )
    assert insufficient is UclCoverageLevel.INSUFFICIENT
    assert reduced is UclCoverageLevel.REDUCED


def test_ucl_coverage_full_requires_result_odds_xg_and_fallback():
    full = classify_ucl_coverage(
        has_settleable_result=True,
        has_target_market_odds=True,
        has_xg=True,
        lineup_dependent=False,
        has_lineup_fallback=True,
    )
    assert full is UclCoverageLevel.FULL


def test_ucl_lineup_dependent_without_fallback_is_insufficient():
    level = classify_ucl_coverage(
        has_settleable_result=True,
        has_target_market_odds=True,
        has_xg=True,
        lineup_dependent=True,
        has_lineup_fallback=False,
    )
    assert level is UclCoverageLevel.INSUFFICIENT


def test_verified_source_requires_all_evidence():
    complete = _verification()
    incomplete = _verification(verification_date=None)
    assert can_mark_verified(complete) is True
    assert can_mark_verified(incomplete) is False


def test_verified_source_rejects_blank_evidence_text():
    blank_scope = _verification(schema_scope="   ")
    assert can_mark_verified(blank_scope) is False
