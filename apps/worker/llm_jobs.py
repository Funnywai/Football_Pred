from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from pathlib import Path

from rq import Queue
from rq.job import Job
from rq.registry import FailedJobRegistry
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import Competition, LlmResearchRun, Match
from packages.db.session import build_engine, build_session_factory, session_scope
from packages.domain.enums import MatchStatus
from packages.ingest.evidence import collect_match_evidence
from packages.ingest.pipeline import build_adapters
from packages.llm.orchestrator import run_llm_prediction
from packages.llm.providers import build_provider
from packages.llm.research_assistant import run_llm_research_assistant
from packages.shared.config import get_settings
from packages.shared.time import ensure_utc, utc_now

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts" / "llm"
_ASSISTANT_PROMPT_DIR = _PROMPT_DIR / "research"
# Lock for the whole job timeout: the run row is committed before the agent
# calls start, but this key prevents duplicate enqueues while a job is still
# queued behind other matches.
_LLM_DEDUPE_TTL_SECONDS = 20 * 60
_LLM_PREDICTION_OFFSET = timedelta(minutes=28)
# Six specialists, red team and judge can take several minutes in total.
# RQ's default 180s timeout is too short for the 9-call pipeline.
_LLM_JOB_TIMEOUT_SECONDS = 1200

logger = logging.getLogger(__name__)


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
            if settings.llm_mode == "assistant":
                match = session.get(Match, uuid.UUID(match_id))
                if match is not None:
                    try:
                        status = collect_match_evidence(
                            session,
                            match,
                            build_adapters(settings),
                            settings,
                        )
                        logger.info(
                            "evidence status for match %s: %s", match_id, status
                        )
                        errors = {
                            source: value
                            for source, value in status.items()
                            if str(value).startswith("error:")
                        }
                        if errors:
                            logger.warning(
                                "evidence source errors for match %s: %s",
                                match_id,
                                errors,
                            )
                    except Exception:
                        session.rollback()
                        logger.exception(
                            "evidence collection failed for match %s", match_id
                        )
                return run_llm_research_assistant(
                    session,
                    uuid.UUID(match_id),
                    stage=stage,
                    provider=provider,
                    prompt_dir=_ASSISTANT_PROMPT_DIR,
                )
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
                enqueued = _enqueue_due(
                    opened, current, queue, settings.llm_competitions
                )
                recovered = _recover_abandoned_llm_jobs(opened, current, queue)
                return enqueued + recovered
        finally:
            engine.dispose()
    enqueued = _enqueue_due(session, current, queue, settings.llm_competitions)
    recovered = _recover_abandoned_llm_jobs(session, current, queue)
    return enqueued + recovered


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
    candidates: list[Match] = []
    for match, _code in matches:
        kickoff = ensure_utc(match.kickoff_at)
        if current < kickoff - _LLM_PREDICTION_OFFSET:
            continue
        if current >= kickoff:
            continue
        candidates.append(match)
    if not candidates:
        return 0

    existing = set(
        session.scalars(
            select(LlmResearchRun.match_id).where(
                LlmResearchRun.stage == "T-30m",
                LlmResearchRun.match_id.in_([match.id for match in candidates]),
            )
        ).all()
    )
    enqueued = 0
    for match in candidates:
        if match.id in existing:
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


def _recover_abandoned_llm_jobs(
    session: Session,
    current,
    queue: Queue,
) -> int:
    connection = getattr(queue, "connection", None)
    if connection is None:
        return 0
    try:
        registry = FailedJobRegistry(queue=queue)
        job_ids = registry.get_job_ids(0, 100)
    except Exception:
        logger.exception("failed to scan failed job registry")
        return 0

    terminal = {"bet", "no_bet", "abstained", "failed"}
    handled: set[tuple[uuid.UUID, str]] = set()
    recovered = 0
    for job_id in job_ids:
        try:
            job = Job.fetch(job_id, connection=connection)
        except Exception:
            logger.debug("could not fetch failed job %s", job_id, exc_info=True)
            continue
        if job.func_name != "apps.worker.llm_jobs.run_llm_prediction_job":
            continue
        if "AbandonedJobError" not in (job.exc_info or ""):
            continue
        args = job.args or ()
        if not args:
            continue
        try:
            match_id = uuid.UUID(str(args[0]))
        except ValueError:
            continue
        stage = str(args[1]) if len(args) > 1 else "T-30m"
        if (match_id, stage) in handled:
            continue
        handled.add((match_id, stage))
        match = session.get(Match, match_id)
        if match is None or ensure_utc(match.kickoff_at) <= current:
            continue
        runs = list(
            session.scalars(
                select(LlmResearchRun).where(
                    LlmResearchRun.match_id == match_id,
                    LlmResearchRun.stage == stage,
                )
            ).all()
        )
        if any(run.status in terminal for run in runs):
            continue
        for run in runs:
            session.delete(run)
        session.flush()
        dedupe_key = f"football:llm:{match_id}:{stage}"
        connection.set(dedupe_key, "1", ex=_LLM_DEDUPE_TTL_SECONDS)
        try:
            registry.requeue(job_id)
            recovered += 1
            logger.info(
                "requeued abandoned LLM job %s for match %s", job_id, match_id
            )
        except Exception:
            connection.delete(dedupe_key)
            logger.exception("failed to requeue abandoned LLM job %s", job_id)
    return recovered
