from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.worker import llm_jobs
from packages.db.base import Base
from packages.db.models import Competition, LlmResearchRun, Match, Team
from packages.domain.enums import MatchStatus

NOW = datetime(2026, 11, 9, 3, 30, tzinfo=UTC)


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)()


class _Connection:
    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.deleted: list[str] = []

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True

    def delete(self, key):
        self.deleted.append(key)
        self.keys.discard(key)


class _Queue:
    def __init__(self) -> None:
        self.connection = _Connection()
        self.jobs: list[tuple[object, tuple, dict]] = []

    def enqueue(self, func, *args, **kwargs):
        self.jobs.append((func, args, kwargs))
        return SimpleNamespace(id="job-1")


def _seed(session, kickoff_at: datetime) -> Match:
    competition = Competition(
        code="EPL",
        name="Premier League",
        country="England",
        football_data_code="E0",
    )
    home = Team(
        slug=f"home-{uuid.uuid4()}", name="Home FC", short_name="HOM", country="England"
    )
    away = Team(
        slug=f"away-{uuid.uuid4()}", name="Away FC", short_name="AWY", country="England"
    )
    session.add_all([competition, home, away])
    session.flush()
    match = Match(
        competition_id=competition.id,
        season="2026/27",
        kickoff_at=kickoff_at,
        first_seen_at=NOW - timedelta(hours=1),
        home_team_id=home.id,
        away_team_id=away.id,
        status=MatchStatus.SCHEDULED,
        source_match_ids={},
        coverage_flags=[],
    )
    session.add(match)
    session.commit()
    return match


def _run(session, match: Match, status: str) -> LlmResearchRun:
    run = LlmResearchRun(
        match_id=match.id,
        stage="T-30m",
        as_of=NOW,
        evidence_hash="hash",
        model_version="llm-assistant-v2",
        prompt_version="research-v2",
        provider="openai_compatible",
        status=status,
        abstain=False,
    )
    session.add(run)
    session.commit()
    return run


def test_enqueue_catches_up_between_t_minus_28_and_kickoff():
    engine, session = _session()
    try:
        match = _seed(session, NOW + timedelta(minutes=10))
        queue = _Queue()

        assert llm_jobs._enqueue_due(session, NOW, queue, "EPL") == 1
        assert len(queue.jobs) == 1
        assert queue.jobs[0][1][0] == str(match.id)
    finally:
        session.close()
        engine.dispose()


def test_enqueue_waits_until_t_minus_28():
    engine, session = _session()
    try:
        _seed(session, NOW + timedelta(minutes=30))
        queue = _Queue()

        assert llm_jobs._enqueue_due(session, NOW, queue, "EPL") == 0
    finally:
        session.close()
        engine.dispose()


def test_enqueue_skips_matches_that_already_have_a_run():
    engine, session = _session()
    try:
        match = _seed(session, NOW + timedelta(minutes=10))
        _run(session, match, "running")
        queue = _Queue()

        assert llm_jobs._enqueue_due(session, NOW, queue, "EPL") == 0
    finally:
        session.close()
        engine.dispose()


class _Registry:
    def __init__(self) -> None:
        self.requeued: list[str] = []

    def get_job_ids(self, start: int, end: int) -> list[str]:
        return ["job-1"]

    def requeue(self, job_id: str) -> None:
        self.requeued.append(job_id)


def test_recovery_requeues_abandoned_job_and_clears_stale_running_row(monkeypatch):
    engine, session = _session()
    try:
        match = _seed(session, NOW + timedelta(minutes=10))
        _run(session, match, "running")
        registry = _Registry()
        job = SimpleNamespace(
            func_name="apps.worker.llm_jobs.run_llm_prediction_job",
            exc_info="rq.exceptions.AbandonedJobError: abandoned",
            args=(str(match.id), "T-30m"),
        )
        monkeypatch.setattr(llm_jobs, "FailedJobRegistry", lambda queue: registry)
        monkeypatch.setattr(
            llm_jobs,
            "Job",
            SimpleNamespace(fetch=lambda *args, **kwargs: job),
        )
        queue = _Queue()

        assert llm_jobs._recover_abandoned_llm_jobs(session, NOW, queue) == 1
        assert registry.requeued == ["job-1"]
        assert session.scalars(select(LlmResearchRun)).all() == []
    finally:
        session.close()
        engine.dispose()
