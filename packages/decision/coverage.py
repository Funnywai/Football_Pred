from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import Competition, DecisionLog, Match, OddsSnapshot
from packages.decision.service import STRATEGY_VERSION, decide_match
from packages.domain.enums import MarketType, MatchStatus, SnapshotKind
from packages.ingest.triggers import DECISION_TRIGGER, decision_slot_key
from packages.shared.time import ensure_utc

_EPL_CODE: Final[str] = "EPL"
_DEFAULT_LOOKAHEAD: Final[timedelta] = timedelta(minutes=30)
_SKIPPED_RERUN_CUTOFF: Final[timedelta] = timedelta(minutes=5)
_STATUS_SKIPPED: Final[str] = "skipped"


@dataclass(frozen=True, slots=True)
class DecisionCoverage:
    eligible: int
    logged: int
    missing_match_ids: tuple[uuid.UUID, ...]
    counts_by_status: dict[str, int]


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    reconciled: int
    errors: int


def coverage_for_window(
    session: Session,
    *,
    competition_code: str = _EPL_CODE,
    start: datetime,
    end: datetime,
) -> DecisionCoverage:
    """Summarise decision-log coverage for scheduled matches in ``[start, end)``."""
    start_utc = ensure_utc(start)
    end_utc = ensure_utc(end)
    matches = session.scalars(
        select(Match)
        .join(Competition, Competition.id == Match.competition_id)
        .where(
            Competition.code == competition_code,
            Match.status == MatchStatus.SCHEDULED,
            Match.kickoff_at >= start_utc,
            Match.kickoff_at < end_utc,
        )
        .order_by(Match.kickoff_at, Match.id)
    ).all()
    eligible_ids = [match.id for match in matches]
    if not eligible_ids:
        return DecisionCoverage(
            eligible=0,
            logged=0,
            missing_match_ids=(),
            counts_by_status={},
        )

    slot_for_match = {
        match_id: decision_slot_key(
            match_id,
            strategy_version=STRATEGY_VERSION,
            trigger=DECISION_TRIGGER,
        )
        for match_id in eligible_ids
    }
    match_for_slot = {slot: match_id for match_id, slot in slot_for_match.items()}
    rows = session.execute(
        select(DecisionLog.match_id, DecisionLog.status, DecisionLog.decision_slot_key).where(
            DecisionLog.decision_slot_key.in_(list(match_for_slot))
        )
    ).all()
    logged_ids: set[uuid.UUID] = set()
    counts_by_status: dict[str, int] = {}
    for match_id, status, slot_key in rows:
        if match_for_slot.get(slot_key) != match_id:
            continue
        logged_ids.add(match_id)
        counts_by_status[status] = counts_by_status.get(status, 0) + 1

    return DecisionCoverage(
        eligible=len(eligible_ids),
        logged=len(logged_ids),
        missing_match_ids=tuple(
            match_id for match_id in eligible_ids if match_id not in logged_ids
        ),
        counts_by_status=counts_by_status,
    )


def _latest_t30m_snapshot(
    session: Session,
    match_id: uuid.UUID,
) -> OddsSnapshot | None:
    return session.scalar(
        select(OddsSnapshot)
        .where(
            OddsSnapshot.match_id == match_id,
            OddsSnapshot.market == MarketType.HAD,
            OddsSnapshot.snapshot_kind == SnapshotKind.T30M,
        )
        .order_by(OddsSnapshot.snapshot_at.desc())
        .limit(1)
    )


def run_decision_reconciliation(
    session: Session,
    *,
    now: datetime,
    lookahead: timedelta = _DEFAULT_LOOKAHEAD,
) -> ReconciliationSummary:
    """Write the missing T-30m decision log for EPL matches near kickoff."""
    current = ensure_utc(now)
    window_end = current + lookahead
    matches = session.scalars(
        select(Match)
        .join(Competition, Competition.id == Match.competition_id)
        .where(
            Competition.code == _EPL_CODE,
            Match.status == MatchStatus.SCHEDULED,
            Match.kickoff_at >= current,
            Match.kickoff_at < window_end,
        )
        .order_by(Match.kickoff_at, Match.id)
    ).all()

    reconciled = 0
    errors = 0
    for match in matches:
        snapshot = _latest_t30m_snapshot(session, match.id)
        latest = session.scalar(
            select(DecisionLog)
            .where(DecisionLog.match_id == match.id)
            .order_by(DecisionLog.decision_at.desc(), DecisionLog.id.desc())
            .limit(1)
        )
        if latest is not None and not _should_rerun_skipped(latest, snapshot, current):
            continue
        try:
            with session.begin_nested():
                _ = decide_match(session, match, snapshot, now=current)
        except Exception:  # noqa: BLE001 - isolate one match from the batch
            errors += 1
            continue
        reconciled += 1
    session.flush()
    return ReconciliationSummary(reconciled=reconciled, errors=errors)


def _should_rerun_skipped(
    log: DecisionLog,
    snapshot: OddsSnapshot | None,
    now: datetime,
) -> bool:
    if log.status != _STATUS_SKIPPED or log.snapshot_id is not None:
        return False
    if snapshot is None:
        return False
    return now - ensure_utc(log.decision_at) > _SKIPPED_RERUN_CUTOFF
