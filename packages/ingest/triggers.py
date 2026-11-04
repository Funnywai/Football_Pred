from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from packages.domain.enums import MarketType, Side, SnapshotKind
from packages.shared.time import ensure_utc

TRIGGER_OFFSETS: dict[str, timedelta] = {
    "T-24h": timedelta(hours=24),
    "T-3h": timedelta(hours=3),
    "T-75m": timedelta(minutes=75),
    "T-30m": timedelta(minutes=30),
    "T-5m": timedelta(minutes=5),
}

TRIGGER_ORDER: tuple[str, ...] = tuple(TRIGGER_OFFSETS)

LINEUP_CHECK_TRIGGER = "T-75m"
LINEUP_RECHECK_TRIGGER = "T-30m"
DECISION_TRIGGER = "T-30m"
CLOSING_TRIGGER = "T-5m"

# T-75m freezes a confirmed lineup when one exists; T-30m repeats the check
# immediately before the frozen decision so a late change invalidates the
# earlier evidence packet. Both gates are scheduled independently.
TRIGGER_ACTIONS: dict[str, str] = {
    "T-24h": "ingest_odds_news_weather",
    "T-3h": "update_availability_odds",
    LINEUP_CHECK_TRIGGER: "lineup_check",
    LINEUP_RECHECK_TRIGGER: "lineup_recheck_decision",
    CLOSING_TRIGGER: "closing_odds_snapshot",
}

TRIGGER_SNAPSHOT_KINDS: dict[str, SnapshotKind] = {
    "T-24h": SnapshotKind.T24H,
    "T-3h": SnapshotKind.T3H,
    "T-30m": SnapshotKind.T30M,
    "T-5m": SnapshotKind.T5M,
}

DEFAULT_STRATEGY_VERSION = "g1"

TRIGGER_SCAN_INTERVAL = timedelta(seconds=60)
TRIGGER_SCAN_MISFIRE_GRACE = timedelta(seconds=120)
TRIGGER_SCAN_WINDOW = TRIGGER_SCAN_INTERVAL + TRIGGER_SCAN_MISFIRE_GRACE


def compute_trigger_times(kickoff_at: datetime) -> dict[str, datetime]:
    kickoff = ensure_utc(kickoff_at)
    return {name: kickoff - offset for name, offset in TRIGGER_OFFSETS.items()}


def trigger_action(trigger: str) -> str:
    try:
        return TRIGGER_ACTIONS[trigger]
    except KeyError as exc:
        raise ValueError(f"unknown trigger {trigger!r}") from exc


def due_triggers(
    now: datetime,
    kickoff_at: datetime,
    *,
    window: timedelta = TRIGGER_SCAN_WINDOW,
) -> tuple[str, ...]:
    """Return triggers whose scheduled time is at most ``window`` old.

    A trigger is due when its scheduled time is at or before ``now`` and no
    more than ``window`` old. Callers must size ``window`` to cover their
    scheduler interval plus the allowed misfire grace; older triggers are not
    reported and can be lost if the scheduler tick is delayed beyond it.
    """
    if window <= timedelta(0):
        raise ValueError("window must be positive")
    current = ensure_utc(now)
    times = compute_trigger_times(kickoff_at)
    return tuple(
        name
        for name in TRIGGER_ORDER
        if timedelta(0) <= current - times[name] < window
    )


def decision_slot_key(
    match_id: uuid.UUID | str,
    *,
    strategy_version: str = DEFAULT_STRATEGY_VERSION,
    trigger: str = DECISION_TRIGGER,
    experiment_id: uuid.UUID | str | None = None,
) -> str:
    if trigger != DECISION_TRIGGER:
        raise ValueError(
            f"decision slot must use {DECISION_TRIGGER}, got {trigger!r}"
        )
    if not strategy_version.strip():
        raise ValueError("strategy_version must not be blank")
    prefix = (
        strategy_version
        if experiment_id is None
        else f"{strategy_version}:{experiment_id}"
    )
    return f"{prefix}:{match_id}:{trigger}"


def bet_intent_key(
    slot_key: str,
    market: MarketType,
    line_key: str,
    selection: Side,
) -> str:
    """One official bet intent per decision slot, market, line and selection."""
    if not slot_key.strip():
        raise ValueError("slot_key must not be blank")
    if not line_key.strip():
        raise ValueError("line_key must not be blank")
    return f"{slot_key}:{market.value}:{line_key}:{selection.value}"
