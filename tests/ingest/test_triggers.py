from datetime import UTC, datetime, timedelta

import pytest

from packages.domain.enums import MarketType, Side, SnapshotKind
from packages.ingest.triggers import (
    CLOSING_TRIGGER,
    DECISION_TRIGGER,
    LINEUP_CHECK_TRIGGER,
    LINEUP_RECHECK_TRIGGER,
    TRIGGER_ORDER,
    TRIGGER_SCAN_INTERVAL,
    TRIGGER_SCAN_MISFIRE_GRACE,
    TRIGGER_SCAN_WINDOW,
    TRIGGER_SNAPSHOT_KINDS,
    bet_intent_key,
    compute_trigger_times,
    decision_slot_key,
    due_triggers,
    trigger_action,
)


def test_trigger_times_are_offsets_from_kickoff():
    kickoff = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
    times = compute_trigger_times(kickoff)
    assert times["T-24h"] == kickoff - timedelta(hours=24)
    assert times["T-3h"] == kickoff - timedelta(hours=3)
    assert times["T-75m"] == kickoff - timedelta(minutes=75)
    assert times["T-30m"] == kickoff - timedelta(minutes=30)
    assert times["T-5m"] == kickoff - timedelta(minutes=5)


def test_naive_kickoff_is_treated_as_utc():
    times = compute_trigger_times(datetime(2026, 8, 15, 14, 0))
    assert times["T-30m"] == datetime(2026, 8, 15, 13, 30, tzinfo=UTC)


def test_trigger_order_runs_from_earliest_to_closest():
    assert TRIGGER_ORDER == ("T-24h", "T-3h", "T-75m", "T-30m", "T-5m")


def test_lineup_check_and_decision_triggers_are_distinct_gates():
    assert LINEUP_CHECK_TRIGGER == "T-75m"
    assert LINEUP_RECHECK_TRIGGER == "T-30m"
    assert DECISION_TRIGGER == "T-30m"
    assert CLOSING_TRIGGER == "T-5m"
    assert trigger_action(LINEUP_CHECK_TRIGGER) == "lineup_check"
    assert trigger_action(LINEUP_RECHECK_TRIGGER) == "lineup_recheck_decision"


def test_odds_triggers_map_to_snapshot_kinds():
    assert TRIGGER_SNAPSHOT_KINDS == {
        "T-24h": SnapshotKind.T24H,
        "T-3h": SnapshotKind.T3H,
        "T-30m": SnapshotKind.T30M,
        "T-5m": SnapshotKind.T5M,
    }
    for trigger in TRIGGER_SNAPSHOT_KINDS:
        assert trigger in TRIGGER_ORDER


def test_unknown_trigger_action_is_rejected():
    with pytest.raises(ValueError):
        trigger_action("T-0m")


def test_due_triggers_fire_only_inside_the_scan_window():
    kickoff = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
    one_minute = timedelta(minutes=1)
    assert due_triggers(
        datetime(2026, 8, 15, 13, 30, tzinfo=UTC), kickoff, window=one_minute
    ) == ("T-30m",)
    assert due_triggers(
        datetime(2026, 8, 15, 13, 30, 30, tzinfo=UTC), kickoff, window=one_minute
    ) == ("T-30m",)
    assert due_triggers(
        datetime(2026, 8, 15, 13, 29, 59, tzinfo=UTC), kickoff, window=one_minute
    ) == ()
    assert due_triggers(
        datetime(2026, 8, 15, 13, 31, 1, tzinfo=UTC), kickoff, window=one_minute
    ) == ()


def test_scan_window_covers_interval_plus_misfire_grace():
    assert TRIGGER_SCAN_INTERVAL == timedelta(seconds=60)
    assert TRIGGER_SCAN_MISFIRE_GRACE >= TRIGGER_SCAN_INTERVAL
    assert TRIGGER_SCAN_WINDOW >= TRIGGER_SCAN_INTERVAL + TRIGGER_SCAN_MISFIRE_GRACE


def test_due_triggers_survive_a_delayed_tick_inside_grace():
    kickoff = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
    delayed = datetime(2026, 8, 15, 13, 31, 30, tzinfo=UTC)
    too_late = datetime(2026, 8, 15, 13, 33, 1, tzinfo=UTC)
    assert due_triggers(delayed, kickoff) == ("T-30m",)
    assert due_triggers(too_late, kickoff) == ()


def test_due_triggers_keep_firing_order_when_window_covers_several_gates():
    kickoff = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
    due = due_triggers(
        kickoff,
        kickoff,
        window=timedelta(hours=25),
    )
    assert due == TRIGGER_ORDER


def test_decision_and_bet_keys_are_stable_across_retries():
    match_id = "11111111-1111-1111-1111-111111111111"
    slot = decision_slot_key(match_id)
    intent = bet_intent_key(slot, MarketType.HAD, "0.0", Side.H)
    assert slot == f"g1:{match_id}:T-30m"
    assert intent == f"{slot}:HAD:0.0:H"
    assert decision_slot_key(match_id) == slot
    assert bet_intent_key(slot, MarketType.HAD, "0.0", Side.H) == intent
