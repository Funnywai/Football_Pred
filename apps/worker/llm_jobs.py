from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path

from rq import Queue
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import Competition, Match
from packages.db.session import build_engine, build_session_factory, session_scope
from packages.domain.enums import MatchStatus
from packages.ingest.triggers import TRIGGER_SCAN_WINDOW
from packages.llm.orchestrator import run_llm_prediction
from packages.llm.providers import build_provider
from packages.shared.config import get_settings
from packages.shared.time import ensure_utc, utc_now

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts" / "llm"
_LLM_DEDUPE_TTL_SECONDS = 6 * 60 * 60
_LLM_PREDICTION_OFFSET = timedelta(minutes=28)
# Six specialists, red team and judge can take several minutes in total.
# RQ's default 180s timeout is too short for the 9-call pipeline.
_LLM_JOB_TIMEOUT_SECONDS = 1200


def run_llm_prediction_job(match_id: str, stage: str = "T-30m") -> dict[str, object]:
    settings = get_settings()
    if not settings.llm_enabled:
        raise RuntimeError("LLM lane is disabled; set FP_LLM_ENABLED=true")
    provider = build_provider(settings)
    if provider is None:
        raise RuntimeError("LLM provider is not configured")
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with session_scope(factory) as session:
            return run_llm_prediction(
                session,
                uuid.UUID(match_id),
                stage=stage,
                provider=provider,
                prompt_dir=_PROMPT_DIR,
            )
    finally:
        engine.dispose()


def enqueue_due_llm_predictions(
    now: object | None = None,
    queue: Queue | None = None,
    *,
    session: Session | None = None,
) -> int:
    settings = get_settings()
    if not settings.llm_enabled:
        return 0
    current = ensure_utc(now or utc_now())
    if queue is None:
        from apps.worker.main import build_queue

        queue = build_queue()
    if session is None:
        engine = build_engine(settings.database_url)
        factory = build_session_factory(engine)
        try:
            with session_scope(factory) as opened:
                return _enqueue_due(opened, current, queue, settings.llm_competitions)
        finally:
            engine.dispose()
    return _enqueue_due(session, current, queue, settings.llm_competitions)


def _enqueue_due(
    session: Session,
    current,
    queue: Queue,
    competition_codes: str,
) -> int:
    codes = {
        code.strip().upper()
        for code in competition_codes.split(",")
        if code.strip()
    }
    if not codes:
        return 0
    connection = getattr(queue, "connection", None)
    if connection is None:
        return 0
    matches = session.execute(
        select(Match, Competition.code)
        .join(Competition, Competition.id == Match.competition_id)
        .where(
            Match.status == MatchStatus.SCHEDULED,
            Match.kickoff_at > current,
            Match.kickoff_at <= current + timedelta(hours=25),
            Competition.code.in_(codes),
        )
    ).all()
    enqueued = 0
    for match, _code in matches:
        if not (
            0
            <= (current - (ensure_utc(match.kickoff_at) - _LLM_PREDICTION_OFFSET)).total_seconds()
            < TRIGGER_SCAN_WINDOW.total_seconds()
        ):
            continue
        dedupe_key = f"football:llm:{match.id}:T-30m"
        if not connection.set(dedupe_key, "1", nx=True, ex=_LLM_DEDUPE_TTL_SECONDS):
            continue
        queue.enqueue(
            "apps.worker.llm_jobs.run_llm_prediction_job",
            str(match.id),
            "T-30m",
            job_id=f"llm-{uuid.uuid4()}",
            job_timeout=_LLM_JOB_TIMEOUT_SECONDS,
        )
        enqueued += 1
    return enqueued
