import logging
import os
from datetime import UTC, datetime

from ops_helpers import FakeJob, FakeScheduler, make_app, make_client, make_db
from sqlalchemy import text

from app.db.models import IngestionRun


async def test_ops_status(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with make_client(make_app(db)) as client:
            response = await client.get("/ops/status")
            assert response.status_code == 200
            body = response.json()
            assert body["app_version"] == "0.1.0"
            assert body["git_sha"] == os.environ.get("GIT_SHA", "unknown")
            assert body["alembic_revision"] is None
            assert body["db_ok"] is True
            assert body["scheduler_enabled"] is False
            assert body["uptime_seconds"] >= 0
    finally:
        await db.dispose()


async def test_ops_status_reads_alembic_revision(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with db.engine.begin() as conn:
            await conn.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            )
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('0003_ledger_bets')")
            )
        async with make_client(make_app(db)) as client:
            body = (await client.get("/ops/status")).json()
            assert body["alembic_revision"] == "0003_ledger_bets"
    finally:
        await db.dispose()


async def test_ops_jobs_merges_last_run(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            session.add(
                IngestionRun(
                    job="sync_odds",
                    started_at=datetime(2026, 10, 15, 3, 0, tzinfo=UTC),
                    finished_at=datetime(2026, 10, 15, 3, 1, tzinfo=UTC),
                    status="success",
                    records_upserted=7,
                )
            )
            await session.commit()
        app = make_app(db)
        app.state.scheduler = FakeScheduler(
            [FakeJob("sync_odds", datetime(2026, 10, 15, 4, 0, tzinfo=UTC))]
        )
        async with make_client(app) as client:
            response = await client.get("/ops/jobs")
            assert response.status_code == 200
            jobs = response.json()["jobs"]
            assert len(jobs) == 1
            assert jobs[0]["id"] == "sync_odds"
            assert jobs[0]["trigger"] == "interval[sync_odds]"
            assert jobs[0]["next_run_time"] == "2026-10-15T04:00:00+00:00"
            assert jobs[0]["pending"] is False
            assert jobs[0]["last_run"] == {
                "status": "success",
                "finished_at": "2026-10-15T03:01:00+00:00",
                "records_upserted": 7,
                "error": None,
            }
    finally:
        await db.dispose()


async def test_ops_jobs_never_tracked_job_has_null_last_run(tmp_path):
    db = await make_db(tmp_path)
    try:
        app = make_app(db)
        app.state.scheduler = FakeScheduler([FakeJob("prune_odds")])
        async with make_client(app) as client:
            jobs = (await client.get("/ops/jobs")).json()["jobs"]
            assert len(jobs) == 1
            assert jobs[0]["id"] == "prune_odds"
            assert jobs[0]["next_run_time"] is None
            assert jobs[0]["last_run"] is None
    finally:
        await db.dispose()


async def test_ops_jobs_without_scheduler(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with make_client(make_app(db)) as client:
            response = await client.get("/ops/jobs")
            assert response.status_code == 200
            assert response.json() == {"jobs": []}
    finally:
        await db.dispose()


async def test_ops_runs_limit_clamp_and_order(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            for index in range(3):
                session.add(
                    IngestionRun(
                        job=f"job-{index}",
                        started_at=datetime(2026, 10, 15, index, 0, tzinfo=UTC),
                        status="success",
                    )
                )
            await session.commit()
        async with make_client(make_app(db)) as client:
            runs = (await client.get("/ops/runs", params={"limit": 9999})).json()["runs"]
            assert len(runs) == 3
            assert [run["job"] for run in runs] == ["job-2", "job-1", "job-0"]
            assert runs[0]["started_at"] == "2026-10-15T02:00:00+00:00"
            assert runs[0]["finished_at"] is None
            assert runs[0]["records_upserted"] == 0
            assert runs[0]["error"] is None
            clamped = (await client.get("/ops/runs", params={"limit": 0})).json()["runs"]
            assert len(clamped) == 1
    finally:
        await db.dispose()


async def test_ops_logs_captures_records(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with make_client(make_app(db)) as client:
            logger = logging.getLogger("tests.ops")
            logger.setLevel(logging.INFO)
            logger.info("ops-capture-marker")
            response = await client.get("/ops/logs")
            assert response.status_code == 200
            entry = next(
                item for item in response.json()["logs"] if item["message"] == "ops-capture-marker"
            )
            assert entry["level"] == "INFO"
            assert entry["logger"] == "tests.ops"
            assert set(entry) == {"time", "level", "logger", "message"}
    finally:
        await db.dispose()


async def test_ops_logs_level_filter(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with make_client(make_app(db)) as client:
            logger = logging.getLogger("tests.ops")
            logger.setLevel(logging.INFO)
            logger.info("ops-filter-info")
            logger.error("ops-filter-error")
            messages = [
                item["message"]
                for item in (await client.get("/ops/logs", params={"level": "ERROR"})).json()["logs"]
            ]
            assert "ops-filter-error" in messages
            assert "ops-filter-info" not in messages
            messages = [
                item["message"]
                for item in (await client.get("/ops/logs", params={"level": "info"})).json()["logs"]
            ]
            assert "ops-filter-error" in messages
            assert "ops-filter-info" in messages
            response = await client.get("/ops/logs", params={"level": "NOPE"})
            assert response.status_code == 422
    finally:
        await db.dispose()


async def test_ops_logs_limit_clamp(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with make_client(make_app(db)) as client:
            logger = logging.getLogger("tests.ops")
            logger.setLevel(logging.INFO)
            logger.info("ops-clamp-marker")
            logs = (await client.get("/ops/logs", params={"limit": 9999})).json()["logs"]
            assert len(logs) <= 500
            logs = (await client.get("/ops/logs", params={"limit": 0})).json()["logs"]
            assert len(logs) >= 1
    finally:
        await db.dispose()
