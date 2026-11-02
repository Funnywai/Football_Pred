from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from apps.worker.jobs import run_lineup_check, settle_match
from packages.db.models import Match
from packages.db.session import build_engine, build_session_factory
from packages.shared.config import get_settings
from packages.shared.time import ensure_utc, utc_now

DECISION_LEAD = timedelta(minutes=30)
SETTLE_DELAY = timedelta(hours=3)
SETTLE_RETRY = timedelta(minutes=30)
SETTLE_DEADLINE = timedelta(hours=6)


def _load_match(match_id: uuid.UUID) -> Match:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            match = session.get(Match, match_id)
            if match is None:
                raise SystemExit(f"unknown match {match_id}")
            return match
    finally:
        engine.dispose()


def _sleep_until(target: datetime) -> None:
    while True:
        remaining = (target - utc_now()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(60.0, remaining))


def _run_decision(match_id: str, deadline: datetime) -> dict[str, str]:
    last_error: Exception | None = None
    while utc_now() < deadline:
        try:
            return run_lineup_check(match_id, "T-30m")
        except Exception as exc:  # noqa: BLE001 - operational retry loop
            last_error = exc
            print(f"decision attempt failed: {exc}", flush=True)
            time.sleep(60)
    raise SystemExit(f"decision failed before kickoff: {last_error}")


def _settle(match_id: str, deadline: datetime) -> int:
    settled = 0
    while utc_now() < deadline:
        result = settle_match(match_id)
        settled = int(result.get("settled", 0))
        if settled:
            return settled
        time.sleep(SETTLE_RETRY.total_seconds())
    return settled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one paper-only T-30m decision and settlement cycle."
    )
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--log", type=Path, default=None)
    args = parser.parse_args(argv)

    match_id = uuid.UUID(args.match_id)
    match = _load_match(match_id)
    kickoff = ensure_utc(match.kickoff_at)
    decision_at = kickoff - DECISION_LEAD
    settle_at = kickoff + SETTLE_DELAY
    settle_deadline = kickoff + SETTLE_DEADLINE

    if args.log is not None:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        log = args.log.open("a", encoding="utf-8")
    else:
        log = None

    def emit(payload: dict[str, object]) -> None:
        line = json.dumps(payload, default=str, sort_keys=True)
        print(line, flush=True)
        if log is not None:
            log.write(line + "\n")
            log.flush()

    emit(
        {
            "event": "armed",
            "match_id": str(match_id),
            "kickoff_at": kickoff,
            "decision_at": decision_at,
            "settle_at": settle_at,
            "paper_only": True,
        }
    )

    _sleep_until(decision_at)
    decision = _run_decision(str(match_id), kickoff)
    emit({"event": "decision", "match_id": str(match_id), "result": decision})

    _sleep_until(settle_at)
    settled = _settle(str(match_id), settle_deadline)
    emit({"event": "settlement", "match_id": str(match_id), "settled": settled})

    if log is not None:
        log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
