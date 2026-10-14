"""Shared helpers for the ``/ops/*`` API tests: a sqlite Database, an app, and fakes."""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
from fastapi import FastAPI

from app.api.main import create_app
from app.config import Settings
from app.db.base import Base
from app.db.models import (
    League,
    Match,
    MatchFeature,
    ModelVersion,
    OddsSnapshot,
    Result,
    Season,
    Team,
)
from app.db.session import Database


async def make_db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'ops.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return db


def make_app(db: Database) -> FastAPI:
    app = create_app(settings=Settings(_env_file=None, enable_scheduler=False), db=db)
    app.state.db = db
    return app


def make_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class FakeJob:
    def __init__(self, job_id: str, next_run_time: datetime | None = None) -> None:
        self.id = job_id
        self.trigger = f"interval[{job_id}]"
        self.next_run_time = next_run_time
        self.pending = False


class FakeScheduler:
    def __init__(self, jobs: list[FakeJob]) -> None:
        self._jobs = jobs

    def get_jobs(self) -> list[FakeJob]:
        return list(self._jobs)


async def seed_data(db: Database) -> None:
    async with db.session_factory() as session:
        league = League(code="EPL", name_en="Premier League")
        session.add(league)
        await session.flush()
        season = Season(
            league_id=league.id,
            label="2026/27",
            start_date=date(2026, 7, 1),
            end_date=date(2027, 6, 30),
        )
        home = Team(name_en="Home FC", aliases=[])
        away = Team(name_en="Away FC", aliases=[])
        session.add_all([season, home, away])
        await session.flush()
        match = Match(
            season_id=season.id,
            league_id=league.id,
            kickoff_time=datetime(2026, 10, 12, 11, 30, tzinfo=UTC),
            status="finished",
            home_team_id=home.id,
            away_team_id=away.id,
        )
        session.add(match)
        await session.flush()
        session.add(
            OddsSnapshot(
                match_id=match.id,
                captured_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
                snapshot_bucket=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
                source="hkjc",
                inplay=False,
                odds_type="HAD",
                payload={"home": 2.1},
            )
        )
        session.add(
            Result(
                match_id=match.id,
                home_score=1,
                away_score=0,
                source="hkjc",
                confirmed=True,
                payout_confirmed=True,
                confirmed_at=datetime(2026, 10, 12, 13, 0, tzinfo=UTC),
                raw={},
            )
        )
        session.add(
            MatchFeature(
                match_id=match.id,
                feature_version="v1",
                built_at=datetime(2026, 10, 12, 10, 0, tzinfo=UTC),
                features={},
            )
        )
        session.add(
            ModelVersion(
                target="1x2",
                algorithm="lightgbm",
                params={"num_trees": 42},
                metrics={"brier": 0.2},
                artifact_path="artifacts/ml/1x2.joblib",
                status="champion",
                created_at=datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
                promoted_at=datetime(2026, 10, 12, 12, 5, tzinfo=UTC),
            )
        )
        await session.commit()
