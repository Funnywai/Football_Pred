from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from rq import Queue

from packages.ingest.triggers import (
    TRIGGER_SCAN_INTERVAL,
    TRIGGER_SCAN_MISFIRE_GRACE,
)

HONG_KONG_TIMEZONE = "Asia/Hong_Kong"


def _enqueue_daily_ingest(queue: Queue) -> None:
    queue.enqueue("apps.worker.jobs.run_daily_ingest")


def _enqueue_due_triggers(queue: Queue) -> None:
    queue.enqueue("apps.worker.jobs.enqueue_due_match_triggers")


def _enqueue_settlement_scan(queue: Queue) -> None:
    queue.enqueue("apps.worker.jobs.run_settlement_scan")


def _enqueue_decision_reconciliation(queue: Queue) -> None:
    queue.enqueue("apps.worker.jobs.run_decision_reconciliation")


def _enqueue_calibration_report(queue: Queue) -> None:
    queue.enqueue("apps.worker.jobs.run_calibration_report")


def build_scheduler(queue: Queue | None = None) -> BlockingScheduler:
    grace_seconds = int(TRIGGER_SCAN_MISFIRE_GRACE.total_seconds())
    scheduler = BlockingScheduler(
        timezone=HONG_KONG_TIMEZONE,
        job_defaults={
            "misfire_grace_time": grace_seconds,
            "coalesce": True,
            "max_instances": 1,
        },
    )
    resolved = queue
    if resolved is None:
        from apps.worker.main import build_queue

        resolved = build_queue()

    scheduler.add_job(
        lambda: _enqueue_daily_ingest(resolved),
        CronTrigger(hour=6, minute=0, timezone=HONG_KONG_TIMEZONE),
        id="daily-ingest",
        replace_existing=True,
        misfire_grace_time=grace_seconds,
    )
    scheduler.add_job(
        lambda: _enqueue_due_triggers(resolved),
        IntervalTrigger(
            seconds=int(TRIGGER_SCAN_INTERVAL.total_seconds()),
            timezone=HONG_KONG_TIMEZONE,
        ),
        id="match-trigger-scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=grace_seconds,
    )
    scheduler.add_job(
        lambda: _enqueue_settlement_scan(resolved),
        IntervalTrigger(hours=6, timezone=HONG_KONG_TIMEZONE),
        id="settlement-scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=grace_seconds,
    )
    scheduler.add_job(
        lambda: _enqueue_decision_reconciliation(resolved),
        IntervalTrigger(minutes=5, timezone=HONG_KONG_TIMEZONE),
        id="decision-reconciliation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=grace_seconds,
    )
    scheduler.add_job(
        lambda: _enqueue_calibration_report(resolved),
        IntervalTrigger(days=7, timezone=HONG_KONG_TIMEZONE),
        id="calibration-report",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=grace_seconds,
    )
    return scheduler


def main() -> None:
    build_scheduler().start()


if __name__ == "__main__":
    main()
