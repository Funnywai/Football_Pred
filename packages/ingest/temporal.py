from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from packages.domain.enums import AvailabilityBasis, SourceStatus, UclCoverageLevel
from packages.shared.time import ensure_utc

PRIMARY_AVAILABILITY_BASES = frozenset(
    {
        AvailabilityBasis.OBSERVED_SNAPSHOT,
        AvailabilityBasis.PROVIDER_POINT_IN_TIME,
    }
)


class DecisionMode(StrEnum):
    PROSPECTIVE = "prospective"
    RETROSPECTIVE = "retrospective"


@dataclass(frozen=True)
class TemporalEvidence:
    first_seen_at: datetime | None
    available_at: datetime | None
    availability_basis: AvailabilityBasis


@dataclass(frozen=True)
class TemporalGateResult:
    allowed: bool
    reason: str


def evaluate_temporal_gate(
    *,
    mode: DecisionMode,
    decision_at: datetime,
    evidence: TemporalEvidence,
) -> TemporalGateResult:
    parsed_mode = DecisionMode(mode)
    decision = ensure_utc(decision_at)
    if parsed_mode is DecisionMode.PROSPECTIVE:
        if evidence.first_seen_at is None:
            return TemporalGateResult(False, "first_seen_at_missing")
        if ensure_utc(evidence.first_seen_at) > decision:
            return TemporalGateResult(False, "first_seen_after_decision")
        return TemporalGateResult(True, "ok")
    if evidence.available_at is None:
        return TemporalGateResult(False, "available_at_missing")
    if ensure_utc(evidence.available_at) > decision:
        return TemporalGateResult(False, "available_after_decision")
    if evidence.availability_basis not in PRIMARY_AVAILABILITY_BASES:
        return TemporalGateResult(False, "non_primary_availability_basis")
    return TemporalGateResult(True, "ok")


def resolve_historical_availability(
    *,
    observed_snapshot_at: datetime | None,
    provider_point_in_time: datetime | None,
) -> tuple[datetime | None, AvailabilityBasis]:
    """Resolve a historical ``available_at`` without ever using first-seen time.

    ``first_seen_at`` is intentionally absent: the first time this system
    observed a record is not evidence of when the record was available.
    """
    if observed_snapshot_at is not None:
        return ensure_utc(observed_snapshot_at), AvailabilityBasis.OBSERVED_SNAPSHOT
    if provider_point_in_time is not None:
        return (
            ensure_utc(provider_point_in_time),
            AvailabilityBasis.PROVIDER_POINT_IN_TIME,
        )
    return None, AvailabilityBasis.UNAVAILABLE


def classify_ucl_coverage(
    *,
    has_settleable_result: bool,
    has_target_market_odds: bool,
    has_xg: bool,
    lineup_dependent: bool,
    has_lineup_fallback: bool,
) -> UclCoverageLevel:
    if not has_settleable_result or not has_target_market_odds:
        return UclCoverageLevel.INSUFFICIENT
    if lineup_dependent and not has_lineup_fallback:
        return UclCoverageLevel.INSUFFICIENT
    if not has_xg or not has_lineup_fallback:
        return UclCoverageLevel.REDUCED
    return UclCoverageLevel.FULL


@dataclass(frozen=True)
class SourceVerification:
    status: SourceStatus
    verification_date: date | None
    schema_scope: str | None
    field_scope: str | None
    test_evidence_ref: str | None
    licensing_check: str | None


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def can_mark_verified(verification: SourceVerification) -> bool:
    """A source may be marked verified only with complete, non-blank evidence."""
    return (
        verification.verification_date is not None
        and _has_text(verification.schema_scope)
        and _has_text(verification.field_scope)
        and _has_text(verification.test_evidence_ref)
        and _has_text(verification.licensing_check)
    )
