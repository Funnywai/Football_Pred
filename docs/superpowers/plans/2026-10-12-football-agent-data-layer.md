# Football Betting Agent — Data Layer (Sub-system A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python data layer for the football betting AI agent: a PostgreSQL schema (SQLAlchemy 2.x + Alembic), a provider abstraction with a self-written HKJC GraphQL client and a football-data.co.uk CSV client, idempotent ingestion jobs (fixture sync, odds snapshots, result reconciliation with fallback), an APScheduler runtime, FastAPI read endpoints, and a backfill CLI — all covered by recorded-fixture contract tests.

**Architecture:** Async Python service. Providers implement one `Provider` Protocol and return pydantic records; ingestion services (`FixtureSync`, `OddsSync`, `ResultReconciler`) are source-agnostic and write to Postgres through SQLAlchemy 2.x async sessions with idempotent upserts. APScheduler runs the jobs in-process; FastAPI exposes read-only endpoints for later subsystems. All HKJC specifics (exact GraphQL documents, headers, throttle, retries) are isolated in `app/providers/hkjc/`.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x (async) + Alembic, PostgreSQL (asyncpg; SQLite/aiosqlite in tests), httpx, APScheduler 3.x, pydantic v2 + pydantic-settings, pytest + pytest-asyncio.

## Global Constraints

- Python >= 3.11. Package manager: `uv` (fallback: `python -m venv .venv` + `pip install -e .`).
- Production DB: PostgreSQL via `asyncpg`. Tests: SQLite via `aiosqlite`. JSONB/ARRAY columns use `.with_variant(JSON, "sqlite")`; all timestamps use the `UtcDateTime` decorator so tests always see timezone-aware UTC datetimes.
- All timestamps are stored as `timestamptz` in UTC. Convert to `Asia/Hong_Kong` only for display.
- HKJC: send the **exact** GraphQL documents in `app/providers/hkjc/queries.py` — ad-hoc/reduced documents are rejected (`WHITELIST_ERROR`). Required headers: `Content-Type: application/json`, `Referer: https://bet.hkjc.com/`, `Origin: https://bet.hkjc.com`, browser `User-Agent`. No Node sidecar.
- HKJC odds: `matches(...)` caps odds types per call (~4) → fetch in the two batches defined in `queries.py`.
- HKJC results: use `searchHistoricFootballMatches` with explicit `startIndex`/`endIndex` (the bare `getHistoricFootballMatches` wrapper returned 0 rows).
- football-data.co.uk: `https://www.football-data.co.uk/mmz4281/{season}/{div}.csv`; Big-5 divisions only (`E0`, `SP1`, `I1`, `D1`, `F1`). UCL is NOT in this set (404).
- Idempotency: re-running any job must not duplicate rows (natural keys + `snapshot_bucket`).
- Raw retention: every fetched payload is stored (`odds_snapshots.payload`, `results.raw`).
- Fail soft: a source outage degrades (fallback/skip) and is recorded in `ingestion_runs`; never crash the scheduler.
- No live network calls in the default test run. Live smoke tests are marked `live` and run only with `pytest -m live`.
- Commit messages: `type: 中文描述` with type ∈ {feat, fix, refactor, docs, chore}. Never English.
- Legal: robots.txt-compliant, throttled (>= 1s between HKJC calls), personal/analytical use only, no commercial redistribution of raw HKJC odds.

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Dependencies, pytest config, ruff config |
| `.env.example` | Documented environment variables |
| `app/config.py` | `Settings` (pydantic-settings) + `get_settings()` |
| `app/db/base.py` | `Base` (declarative, naming convention) + `UtcDateTime` type |
| `app/db/session.py` | `Database` (async engine + session factory) |
| `app/db/models.py` | 7 ORM models: League, Season, Team, Match, OddsSnapshot, Result, IngestionRun |
| `app/providers/base.py` | `Provider` Protocol + `LeagueRecord`, `FixtureRecord`, `OddsRecord`, `ResultRecord` |
| `app/providers/hkjc/queries.py` | Exact HKJC GraphQL documents + odds-type batches |
| `app/providers/hkjc/client.py` | `HkjcGraphQLClient`: headers, gzip, throttle, retries |
| `app/providers/hkjc/provider.py` | `HkjcProvider`: fixtures, odds (two-batch), results, payout details |
| `app/providers/football_data/provider.py` | `FootballDataProvider`: CSV results + historical backfill records |
| `app/services/alias.py` | Team-name normalization + alias/fuzzy matching |
| `app/services/runs.py` | `ingestion_runs` tracking helper (`track_run`) |
| `app/services/fixtures.py` | `FixtureSync`: leagues/seasons/teams/matches upserts |
| `app/services/odds.py` | `OddsSync`: snapshot buckets + `prune_odds_snapshots` retention |
| `app/services/results.py` | `ResultReconciler`: HKJC-first → fallback → 48h flag |
| `app/api/schemas.py` | Response models for the read API |
| `app/api/routes.py` | `/matches`, `/matches/{id}/odds`, `/results`, `/health` |
| `app/api/main.py` | `create_app()` + lifespan (DB, providers, scheduler) |
| `app/scheduler.py` | APScheduler wiring + job functions |
| `app/cli.py` | `seed-leagues`, `backfill` commands |
| `app/data/leagues.py` | League seed rows |
| `app/data/team_aliases.json` | Curated alias map (canonical name → aliases) |
| `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/0001_initial_schema.py` | Migrations |
| `tests/…` | Contract, reconciliation, idempotency, alias, API, scheduler, CLI tests + recorded fixtures |

---

### Task 1: Project scaffolding, dependencies, and settings

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `.env.example`
- Modify: `.gitignore` (append Python entries)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `app.config.Settings` with fields `database_url: str`, `hkjc_graphql_url: str`, `hkjc_referer: str`, `hkjc_origin: str`, `hkjc_user_agent: str`, `football_data_base: str`, `sync_odds_interval: int`, `sync_settle_interval: int`, `league_whitelist: list[str]`, `hkjc_throttle_seconds: float`, `odds_retention_days: int`, `enable_scheduler: bool`; and `app.config.get_settings() -> Settings`.

- [ ] **Step 1: Create `pyproject.toml` and the `app` package marker**

`pyproject.toml`:

```toml
[project]
name = "football-agent-data-layer"
version = "0.1.0"
description = "Data layer for the football betting AI agent (HKJC + football-data.co.uk ingestion)"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "httpx>=0.27",
    "apscheduler>=3.10,<4",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
]

[dependency-groups]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "aiosqlite>=0.20",
    "ruff>=0.5",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-m 'not live'"
markers = [
    "live: opt-in smoke tests that hit real external endpoints (run with: pytest -m live)",
]

[tool.ruff]
line-length = 100
target-version = "py311"
```

`app/__init__.py`:

```python
"""Football betting agent — data layer (sub-system A)."""
```

- [ ] **Step 2: Create the virtualenv and install dependencies**

Run:

```bash
uv sync
```

Expected: uv creates `.venv/`, installs the project in editable mode plus the `dev` dependency group. Verify with `uv run pytest --version` → prints `pytest 8.x`.

- [ ] **Step 3: Write the failing test `tests/test_config.py`**

```python
from app.config import Settings


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.hkjc_graphql_url == "https://info.cld.hkjc.com/graphql/base/"
    assert settings.hkjc_referer == "https://bet.hkjc.com/"
    assert settings.hkjc_origin == "https://bet.hkjc.com"
    assert settings.sync_odds_interval == 600
    assert settings.sync_settle_interval == 900
    assert settings.hkjc_throttle_seconds == 1.5
    assert settings.odds_retention_days == 120
    assert settings.league_whitelist == ["EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1", "UCL"]


def test_league_whitelist_parses_comma_separated_env(monkeypatch):
    monkeypatch.setenv("LEAGUE_WHITELIST", "epl, laliga ,ucl")
    settings = Settings(_env_file=None)
    assert settings.league_whitelist == ["EPL", "LALIGA", "UCL"]


def test_league_whitelist_accepts_json_list(monkeypatch):
    monkeypatch.setenv("LEAGUE_WHITELIST", '["EPL", "UCL"]')
    settings = Settings(_env_file=None)
    assert settings.league_whitelist == ["EPL", "UCL"]
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.config'`.

- [ ] **Step 5: Implement `app/config.py` and `.env.example`**

`app/config.py`:

```python
import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/football"
    hkjc_graphql_url: str = "https://info.cld.hkjc.com/graphql/base/"
    hkjc_referer: str = "https://bet.hkjc.com/"
    hkjc_origin: str = "https://bet.hkjc.com"
    hkjc_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    football_data_base: str = "https://www.football-data.co.uk"
    sync_odds_interval: int = 600
    sync_settle_interval: int = 900
    league_whitelist: Annotated[list[str], NoDecode] = [
        "EPL",
        "LALIGA",
        "SERIEA",
        "BUNDESLIGA",
        "LIGUE1",
        "UCL",
    ]
    hkjc_throttle_seconds: float = 1.5
    odds_retention_days: int = 120
    enable_scheduler: bool = True

    @field_validator("league_whitelist", mode="before")
    @classmethod
    def _parse_whitelist(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [part.strip().upper() for part in text.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`.env.example`:

```dotenv
# PostgreSQL connection (async driver)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/football

# HKJC GraphQL endpoint + required request headers
HKJC_GRAPHQL_URL=https://info.cld.hkjc.com/graphql/base/
HKJC_REFERER=https://bet.hkjc.com/
HKJC_ORIGIN=https://bet.hkjc.com
HKJC_USER_AGENT=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36

# football-data.co.uk CSV base URL
FOOTBALL_DATA_BASE=https://www.football-data.co.uk

# Scheduler intervals (seconds)
SYNC_ODDS_INTERVAL=600
SYNC_SETTLE_INTERVAL=900

# Comma-separated league codes to ingest
LEAGUE_WHITELIST=EPL,LALIGA,SERIEA,BUNDESLIGA,LIGUE1,UCL

# Minimum seconds between two HKJC requests
HKJC_THROTTLE_SECONDS=1.5

# Odds snapshot retention (days)
ODDS_RETENTION_DAYS=120

# Start the APScheduler jobs inside the FastAPI process
ENABLE_SCHEDULER=true
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`

Expected: `3 passed`.

- [ ] **Step 7: Append Python entries to `.gitignore`**

Replace the full contents of `.gitignore` with:

```gitignore
node_modules/
dist/
.env
*.log
dev.db
.omo/
*.xlsx
analysis_summary.json
.DS_Store
__pycache__/
*.pyc
.venv/
.pytest_cache/
.ruff_cache/
*.egg-info/
```

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore .env.example app/__init__.py app/config.py tests/test_config.py
git commit -m "feat: 建立 Python 專案骨架與設定模組"
```

---

### Task 2: Database engine, session factory, and UTC datetime type

**Files:**
- Create: `app/db/__init__.py`
- Create: `app/db/base.py`
- Create: `app/db/session.py`
- Test: `tests/test_db_session.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `app.db.base.Base` (declarative base with naming convention), `app.db.base.UtcDateTime` (SQLAlchemy `TypeDecorator` that binds aware/naive datetimes as UTC and returns aware UTC datetimes), `app.db.session.Database` with `__init__(self, url: str, **engine_kwargs: object)`, attributes `engine: AsyncEngine`, `session_factory: async_sessionmaker[AsyncSession]`, and `async def dispose(self) -> None`.

- [ ] **Step 1: Write the failing test `tests/test_db_session.py`**

```python
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UtcDateTime
from app.db.session import Database


class _Stamp(Base):
    __tablename__ = "stamps"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


async def test_database_roundtrip_returns_aware_utc(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with db.session_factory() as session:
            session.add(_Stamp(at=datetime(2026, 10, 12, 12, 0, tzinfo=UTC)))
            await session.commit()
        async with db.session_factory() as session:
            row = (await session.execute(select(_Stamp))).scalar_one()
            assert row.at == datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
            assert row.at.tzinfo is not None
    finally:
        await db.dispose()


async def test_utc_datetime_normalizes_naive_input(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with db.session_factory() as session:
            session.add(_Stamp(at=datetime(2026, 10, 12, 12, 0)))
            await session.commit()
        async with db.session_factory() as session:
            row = (await session.execute(select(_Stamp))).scalar_one()
            assert row.at == datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_db_session.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.db'`.

- [ ] **Step 3: Implement `app/db/base.py`, `app/db/session.py`, and `app/db/__init__.py`**

`app/db/__init__.py`:

```python
"""Database layer: declarative base, models, and async session management."""
```

`app/db/base.py`:

```python
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UtcDateTime(TypeDecorator):
    """timestamptz on PostgreSQL; always returns timezone-aware UTC datetimes.

    SQLite (used in tests) drops timezone information, so this decorator
    re-attaches UTC on read and normalizes naive input to UTC on write.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
```

`app/db/session.py`:

```python
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """Owns the async engine and session factory for one process."""

    def __init__(self, url: str, **engine_kwargs: object) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True, **engine_kwargs)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def dispose(self) -> None:
        await self.engine.dispose()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_db_session.py -v`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/db/__init__.py app/db/base.py app/db/session.py tests/test_db_session.py
git commit -m "feat: 新增資料庫連線、Session 管理與 UTC 時間型別"
```

---

### Task 3: SQLAlchemy models for all seven tables

**Files:**
- Create: `app/db/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `app.db.base.Base`, `app.db.base.UtcDateTime`, `app.db.session.Database`.
- Produces: ORM classes `League`, `Season`, `Team`, `Match`, `OddsSnapshot`, `Result`, `IngestionRun` with the exact columns from the spec §5. Key attributes used by later tasks: `League.code/name_en/name_ch/country/hkjc_tourn_id/active`, `Season.league_id/label/start_date/end_date`, `Team.name_en/name_ch/hkjc_team_id/aliases/external_ids`, `Match.season_id/league_id/hkjc_match_id/kickoff_time/status/home_team_id/away_team_id/venue/round/created_at/updated_at`, `OddsSnapshot.match_id/captured_at/snapshot_bucket/source/inplay/odds_type/payload`, `Result.match_id/home_score/away_score/ttl_corner/source/confirmed/payout_confirmed/confirmed_at/raw`, `IngestionRun.job/started_at/finished_at/status/records_upserted/error`.

- [ ] **Step 1: Write the failing test `tests/test_models.py`**

```python
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.models import IngestionRun, League, Match, OddsSnapshot, Result, Season, Team
from app.db.session import Database


async def _seed(db: Database) -> dict[str, int]:
    async with db.session_factory() as session:
        league = League(
            code="EPL",
            name_en="English Premier League",
            name_ch="英格蘭超級聯賽",
            country="England",
        )
        session.add(league)
        await session.flush()
        season = Season(
            league_id=league.id,
            label="2026/27",
            start_date=date(2026, 7, 1),
            end_date=date(2027, 6, 30),
        )
        home = Team(
            name_en="Manchester United",
            name_ch="曼聯",
            hkjc_team_id="T1",
            aliases=["Man Utd", "曼聯"],
        )
        away = Team(name_en="Liverpool", name_ch="利物浦", hkjc_team_id="T2", aliases=["Liverpool FC"])
        session.add_all([season, home, away])
        await session.flush()
        match = Match(
            season_id=season.id,
            league_id=league.id,
            hkjc_match_id="M1",
            kickoff_time=datetime(2026, 10, 12, 19, 30, tzinfo=UTC),
            home_team_id=home.id,
            away_team_id=away.id,
            venue="Old Trafford",
            round="Round 8",
        )
        session.add(match)
        await session.commit()
        return {
            "league": league.id,
            "season": season.id,
            "home": home.id,
            "away": away.id,
            "match": match.id,
        }


async def test_models_create_and_roundtrip(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        ids = await _seed(db)
        async with db.session_factory() as session:
            team = (await session.execute(select(Team).where(Team.id == ids["home"]))).scalar_one()
            assert team.aliases == ["Man Utd", "曼聯"]
            assert team.external_ids == {}
            match = (await session.execute(select(Match).where(Match.id == ids["match"]))).scalar_one()
            assert match.status == "scheduled"
            assert match.kickoff_time == datetime(2026, 10, 12, 19, 30, tzinfo=UTC)
    finally:
        await db.dispose()


async def test_odds_snapshot_unique_bucket(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        ids = await _seed(db)
        bucket = datetime(2026, 10, 12, 19, 30, tzinfo=UTC)
        async with db.session_factory() as session:
            session.add(
                OddsSnapshot(
                    match_id=ids["match"],
                    captured_at=bucket,
                    snapshot_bucket=bucket,
                    source="hkjc",
                    inplay=False,
                    odds_type="HAD",
                    payload={"home": 2.1},
                )
            )
            await session.commit()
        async with db.session_factory() as session:
            session.add(
                OddsSnapshot(
                    match_id=ids["match"],
                    captured_at=bucket,
                    snapshot_bucket=bucket,
                    source="hkjc",
                    inplay=False,
                    odds_type="HAD",
                    payload={"home": 2.2},
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await db.dispose()


async def test_result_unique_per_match(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        ids = await _seed(db)
        async with db.session_factory() as session:
            session.add(
                Result(
                    match_id=ids["match"],
                    home_score=2,
                    away_score=1,
                    source="hkjc",
                    confirmed=True,
                    payout_confirmed=True,
                    confirmed_at=datetime(2026, 10, 12, 21, 45, tzinfo=UTC),
                    raw={"homeResult": "2"},
                )
            )
            await session.commit()
        async with db.session_factory() as session:
            session.add(
                Result(
                    match_id=ids["match"],
                    home_score=0,
                    away_score=0,
                    source="football_data",
                    confirmed=False,
                    payout_confirmed=False,
                    raw={},
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await db.dispose()


async def test_ingestion_run_defaults(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with db.session_factory() as session:
            run = IngestionRun(
                job="sync_odds",
                started_at=datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
                status="running",
            )
            session.add(run)
            await session.commit()
            assert run.records_upserted == 0
            assert run.finished_at is None
            assert run.error is None
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.db.models'`.

- [ ] **Step 3: Implement `app/db/models.py`**

```python
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UtcDateTime


def _json_type() -> JSONB:
    return JSONB().with_variant(JSON, "sqlite")


def _string_array_type() -> ARRAY:
    return ARRAY(Text).with_variant(JSON, "sqlite")


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_ch: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(60))
    hkjc_tourn_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    seasons: Mapped[list["Season"]] = relationship(back_populates="league")


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("league_id", "label", name="uq_seasons_league_label"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    league: Mapped[League] = relationship(back_populates="seasons")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_ch: Mapped[str | None] = mapped_column(String(120))
    hkjc_team_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    aliases: Mapped[list[str]] = mapped_column(_string_array_type(), nullable=False, default=list)
    external_ids: Mapped[dict] = mapped_column(_json_type(), nullable=False, default=dict)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint(
            "season_id",
            "home_team_id",
            "away_team_id",
            "kickoff_time",
            name="uq_matches_natural",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    hkjc_match_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    kickoff_time: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    venue: Mapped[str | None] = mapped_column(String(160))
    round: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    season: Mapped[Season] = relationship()
    league: Mapped[League] = relationship()
    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])
    result: Mapped["Result | None"] = relationship(back_populates="match", uselist=False)


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "odds_type",
            "inplay",
            "snapshot_bucket",
            name="uq_odds_snapshots_bucket",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    snapshot_bucket: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    inplay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    odds_type: Mapped[str] = mapped_column(String(8), nullable=False)
    payload: Mapped[dict] = mapped_column(_json_type(), nullable=False)

    match: Mapped[Match] = relationship()


class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), unique=True, nullable=False)
    home_score: Mapped[int] = mapped_column(Integer, nullable=False)
    away_score: Mapped[int] = mapped_column(Integer, nullable=False)
    ttl_corner: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payout_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    raw: Mapped[dict] = mapped_column(_json_type(), nullable=False, default=dict)

    match: Mapped[Match] = relationship(back_populates="result")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    records_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/db/models.py tests/test_models.py
git commit -m "feat: 定義七張資料表的 SQLAlchemy 模型"
```

---

### Task 4: Alembic setup and initial migration

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_initial_schema.py`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Consumes: `app.config.get_settings()`, `app.db.base.Base`, `app.db.models` (import registers all tables on `Base.metadata`).
- Produces: Alembic revision `0001` creating all seven tables; `alembic upgrade head` applies it to PostgreSQL.

- [ ] **Step 1: Write the failing test `tests/test_migrations.py`**

```python
import io

from alembic import command
from alembic.config import Config

EXPECTED_TABLES = [
    "leagues",
    "seasons",
    "teams",
    "matches",
    "odds_snapshots",
    "results",
    "ingestion_runs",
]


def test_offline_migration_creates_all_tables():
    cfg = Config("alembic.ini")
    cfg.output_buffer = io.StringIO()
    command.upgrade(cfg, "head", sql=True)
    sql = cfg.output_buffer.getvalue()
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE {table}" in sql
    assert "uq_odds_snapshots_bucket" in sql
    assert "uq_matches_natural" in sql
    assert "uq_results_match_id" in sql
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_migrations.py -v`

Expected: FAIL — `alembic.util.exc.CommandError: No 'script_location' key found in configuration` (or `FileNotFoundError: alembic.ini`).

- [ ] **Step 3: Implement `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, and the initial migration**

`alembic.ini`:

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

`alembic/env.py`:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.db import models  # noqa: F401  (registers all tables on Base.metadata)
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`alembic/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`alembic/versions/0001_initial_schema.py`:

```python
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "leagues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.Column("name_ch", sa.String(length=120), nullable=True),
        sa.Column("country", sa.String(length=60), nullable=True),
        sa.Column("hkjc_tourn_id", sa.String(length=40), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("code", name="uq_leagues_code"),
        sa.UniqueConstraint("hkjc_tourn_id", name="uq_leagues_hkjc_tourn_id"),
    )
    op.create_table(
        "seasons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), nullable=False),
        sa.Column("label", sa.String(length=20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.UniqueConstraint("league_id", "label", name="uq_seasons_league_label"),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.Column("name_ch", sa.String(length=120), nullable=True),
        sa.Column("hkjc_team_id", sa.String(length=40), nullable=True),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "external_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("hkjc_team_id", name="uq_teams_hkjc_team_id"),
    )
    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id"), nullable=False),
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), nullable=False),
        sa.Column("hkjc_match_id", sa.String(length=40), nullable=True),
        sa.Column("kickoff_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("home_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("away_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("venue", sa.String(length=160), nullable=True),
        sa.Column("round", sa.String(length=60), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("hkjc_match_id", name="uq_matches_hkjc_match_id"),
        sa.UniqueConstraint(
            "season_id",
            "home_team_id",
            "away_team_id",
            "kickoff_time",
            name="uq_matches_natural",
        ),
    )
    op.create_table(
        "odds_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("inplay", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("odds_type", sa.String(length=8), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "match_id",
            "odds_type",
            "inplay",
            "snapshot_bucket",
            name="uq_odds_snapshots_bucket",
        ),
    )
    op.create_index("ix_odds_snapshots_match_id", "odds_snapshots", ["match_id"])
    op.create_table(
        "results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=False),
        sa.Column("away_score", sa.Integer(), nullable=False),
        sa.Column("ttl_corner", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "payout_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "raw",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("match_id", name="uq_results_match_id"),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("records_upserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ingestion_runs")
    op.drop_table("results")
    op.drop_index("ix_odds_snapshots_match_id", table_name="odds_snapshots")
    op.drop_table("odds_snapshots")
    op.drop_table("matches")
    op.drop_table("teams")
    op.drop_table("seasons")
    op.drop_table("leagues")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_migrations.py -v`

Expected: `1 passed`.

- [ ] **Step 5: Verify the migration applies to a real PostgreSQL (manual, once)**

If no local Postgres is running, start one with Docker:

```bash
docker run -d --name football-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=football -p 5432:5432 postgres:16
```

Then, with `DATABASE_URL` set in `.env` (see `.env.example`):

```bash
uv run alembic upgrade head
```

Expected: `Running upgrade  -> 0001, initial schema`. Then `uv run alembic downgrade base` and `uv run alembic upgrade head` again to confirm reversibility.

- [ ] **Step 6: Commit**

```bash
git add alembic.ini alembic/env.py alembic/script.py.mako alembic/versions/0001_initial_schema.py tests/test_migrations.py
git commit -m "feat: 新增 Alembic 設定與初始資料庫遷移"
```

---

### Task 5: Provider Protocol and record types

**Files:**
- Create: `app/providers/__init__.py`
- Create: `app/providers/base.py`
- Test: `tests/test_provider_protocol.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `app.providers.base.Provider` (runtime-checkable Protocol with `name: str`, `async fetch_leagues() -> list[LeagueRecord]`, `async fetch_fixtures(date_from: date, date_to: date) -> list[FixtureRecord]`, `async fetch_odds(fixtures: list[FixtureRecord]) -> list[OddsRecord]`, `async fetch_results(date_from: date, date_to: date) -> list[ResultRecord]`); pydantic models `LeagueRecord(code, name_en, name_ch, country, hkjc_tourn_id)`, `FixtureRecord(source, league_name, hkjc_tourn_id, hkjc_match_id, kickoff_time, status, home_team_name_en, home_team_name_ch, home_team_hkjc_id, away_team_name_en, away_team_name_ch, away_team_hkjc_id, venue, round, raw)`, `OddsRecord(match_hkjc_id, odds_type, inplay, captured_at, payload)`, `ResultRecord(match_hkjc_id, match_date, home_team_name, away_team_name, home_score, away_score, ttl_corner, source, confirmed, payout_confirmed, raw)`.

- [ ] **Step 1: Write the failing test `tests/test_provider_protocol.py`**

```python
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.providers.base import (
    FixtureRecord,
    LeagueRecord,
    OddsRecord,
    Provider,
    ResultRecord,
)


class _DummyProvider:
    name = "dummy"

    async def fetch_leagues(self) -> list[LeagueRecord]:
        return []

    async def fetch_fixtures(self, date_from: date, date_to: date) -> list[FixtureRecord]:
        return []

    async def fetch_odds(self, fixtures: list[FixtureRecord]) -> list[OddsRecord]:
        return []

    async def fetch_results(self, date_from: date, date_to: date) -> list[ResultRecord]:
        return []


def test_dummy_provider_satisfies_protocol():
    assert isinstance(_DummyProvider(), Provider)


def test_result_record_requires_identity():
    with pytest.raises(ValidationError):
        ResultRecord(home_score=1, away_score=0, source="hkjc")


def test_result_record_accepts_hkjc_identity():
    record = ResultRecord(
        match_hkjc_id="M1", home_score=1, away_score=0, source="hkjc", confirmed=True
    )
    assert record.ttl_corner is None
    assert record.payout_confirmed is False


def test_result_record_accepts_date_identity():
    record = ResultRecord(
        match_date=date(2026, 10, 11),
        home_team_name="Man Utd",
        away_team_name="Liverpool",
        home_score=2,
        away_score=1,
        source="football_data",
    )
    assert record.confirmed is False


def test_fixture_record_defaults():
    record = FixtureRecord(
        source="hkjc",
        league_name="English Premier League",
        kickoff_time=datetime(2026, 10, 12, 19, 30, tzinfo=UTC),
        home_team_name_en="Manchester United",
        away_team_name_en="Liverpool",
    )
    assert record.status == "scheduled"
    assert record.raw == {}
    assert record.hkjc_match_id is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_provider_protocol.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.providers'`.

- [ ] **Step 3: Implement `app/providers/base.py` and `app/providers/__init__.py`**

`app/providers/__init__.py`:

```python
"""External data providers (HKJC GraphQL, football-data.co.uk CSV)."""
```

`app/providers/base.py`:

```python
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator


class LeagueRecord(BaseModel):
    code: str
    name_en: str
    name_ch: str | None = None
    country: str | None = None
    hkjc_tourn_id: str | None = None


class FixtureRecord(BaseModel):
    source: str
    league_name: str
    hkjc_tourn_id: str | None = None
    hkjc_match_id: str | None = None
    kickoff_time: datetime
    status: str = "scheduled"
    home_team_name_en: str
    home_team_name_ch: str | None = None
    home_team_hkjc_id: str | None = None
    away_team_name_en: str
    away_team_name_ch: str | None = None
    away_team_hkjc_id: str | None = None
    venue: str | None = None
    round: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class OddsRecord(BaseModel):
    match_hkjc_id: str
    odds_type: str
    inplay: bool = False
    captured_at: datetime
    payload: dict[str, Any]


class ResultRecord(BaseModel):
    match_hkjc_id: str | None = None
    match_date: date | None = None
    home_team_name: str | None = None
    away_team_name: str | None = None
    home_score: int
    away_score: int
    ttl_corner: int | None = None
    source: str
    confirmed: bool = False
    payout_confirmed: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_identity(self) -> "ResultRecord":
        has_hkjc = self.match_hkjc_id is not None
        has_external = (
            self.match_date is not None
            and self.home_team_name is not None
            and self.away_team_name is not None
        )
        if not has_hkjc and not has_external:
            raise ValueError(
                "ResultRecord requires match_hkjc_id or (match_date, home_team_name, away_team_name)"
            )
        return self


@runtime_checkable
class Provider(Protocol):
    name: str

    async def fetch_leagues(self) -> list[LeagueRecord]: ...

    async def fetch_fixtures(self, date_from: date, date_to: date) -> list[FixtureRecord]: ...

    async def fetch_odds(self, fixtures: list[FixtureRecord]) -> list[OddsRecord]: ...

    async def fetch_results(self, date_from: date, date_to: date) -> list[ResultRecord]: ...
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_provider_protocol.py -v`

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/providers/__init__.py app/providers/base.py tests/test_provider_protocol.py
git commit -m "feat: 定義 Provider 介面與資料記錄型別"
```

---

### Task 6: HKJC GraphQL query documents

**Files:**
- Create: `app/providers/hkjc/__init__.py`
- Create: `app/providers/hkjc/queries.py`
- Test: `tests/test_hkjc_queries.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `app.providers.hkjc.queries.FOOTBALL_MATCHES_QUERY: str`, `HISTORIC_FOOTBALL_MATCHES_QUERY: str`, `HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY: str`, `ODDS_TYPE_BATCHES: list[list[str]]`, `DEFAULT_ODDS_TYPES: list[str]`.

**Provenance note (read before editing):** these three documents are copied byte-for-byte from `Bobosky2005/hkjc-api` (`src/query/footballMatchesQuery.ts`, commit `142ecf4`). HKJC rejects ad-hoc/reduced documents (`WHITELIST_ERROR`), so **never** hand-edit the field selections. The reference package itself has no hardcoded two-array odds split — it ships `DEFAULT_FOOTBALL_ODDS_TYPES = ['HAD','HDC','HIL','CRS']` and a `batchSize = 4` loop, and sets no explicit HTTP headers (it relies on `graphql-request` defaults). This plan keeps the exact documents, sends the four headers the spec verified, and defines two batches covering the spec's seven odds types (`HAD/HDC/HIL/CRS/HHA/CHD/CHL`), each batch ≤ 4 types to respect the verified per-call cap.

- [ ] **Step 1: Write the failing test `tests/test_hkjc_queries.py`**

```python
from app.providers.hkjc.queries import (
    DEFAULT_ODDS_TYPES,
    FOOTBALL_MATCHES_QUERY,
    HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY,
    HISTORIC_FOOTBALL_MATCHES_QUERY,
    ODDS_TYPE_BATCHES,
)


def test_football_matches_query_shape():
    assert "query matchList(" in FOOTBALL_MATCHES_QUERY
    assert "matches(startIndex: $startIndex" in FOOTBALL_MATCHES_QUERY
    assert "fbOddsTypes: $fbOddsTypesM" in FOOTBALL_MATCHES_QUERY
    assert "foPools(fbOddsTypes: $fbOddsTypes)" in FOOTBALL_MATCHES_QUERY
    assert "runningResult" in FOOTBALL_MATCHES_QUERY


def test_historic_matches_query_uses_match_result_with_pagination():
    assert "query matchResults(" in HISTORIC_FOOTBALL_MATCHES_QUERY
    assert "matchResult(startDate: $startDate, endDate: $endDate, startIndex: $startIndex,endIndex: $endIndex" in HISTORIC_FOOTBALL_MATCHES_QUERY
    assert "payoutConfirmed" in HISTORIC_FOOTBALL_MATCHES_QUERY
    assert "ttlCornerResult" in HISTORIC_FOOTBALL_MATCHES_QUERY


def test_historic_details_query_requests_payout_pools():
    assert "query matchResultDetails(" in HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY
    assert "matchResult(matchId: $matchId)" in HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY
    assert "resultOnly: true" in HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY
    assert "winOrd" in HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY


def test_odds_type_batches_cover_spec_types_and_respect_cap():
    assert DEFAULT_ODDS_TYPES == ["HAD", "HDC", "HIL", "CRS"]
    assert len(ODDS_TYPE_BATCHES) == 2
    for batch in ODDS_TYPE_BATCHES:
        assert 0 < len(batch) <= 4
    flattened = [t for batch in ODDS_TYPE_BATCHES for t in batch]
    assert flattened == ["HAD", "HDC", "HIL", "CRS", "HHA", "CHD", "CHL"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_hkjc_queries.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.providers.hkjc'`.

- [ ] **Step 3: Implement `app/providers/hkjc/queries.py` and `app/providers/hkjc/__init__.py`**

`app/providers/hkjc/__init__.py`:

```python
"""HKJC GraphQL provider (exact query documents ported from Bobosky2005/hkjc-api)."""
```

`app/providers/hkjc/queries.py`:

```python
"""Exact HKJC GraphQL documents.

Copied byte-for-byte from Bobosky2005/hkjc-api (src/query/footballMatchesQuery.ts,
commit 142ecf4). HKJC rejects ad-hoc or reduced documents with WHITELIST_ERROR,
so do not edit the field selections below.
"""

FOOTBALL_MATCHES_QUERY = """
query matchList($startIndex: Int, $endIndex: Int,$startDate: String, $endDate: String, $matchIds: [String], $tournIds: [String], $fbOddsTypes: [FBOddsType]!, $fbOddsTypesM: [FBOddsType]!, $inplayOnly: Boolean, $featuredMatchesOnly: Boolean, $frontEndIds: [String], $earlySettlementOnly: Boolean, $showAllMatch: Boolean) {
    matches(startIndex: $startIndex,endIndex: $endIndex, startDate: $startDate, endDate: $endDate, matchIds: $matchIds, tournIds: $tournIds, fbOddsTypes: $fbOddsTypesM, inplayOnly: $inplayOnly, featuredMatchesOnly: $featuredMatchesOnly, frontEndIds: $frontEndIds, earlySettlementOnly: $earlySettlementOnly, showAllMatch: $showAllMatch) {
      id
      frontEndId
      matchDate
      kickOffTime
      status
      updateAt
      sequence
      esIndicatorEnabled
      homeTeam {
        id
        name_en
        name_ch
      }
      awayTeam {
        id
        name_en
        name_ch
      }
      tournament {
        id
        frontEndId
        nameProfileId
        isInteractiveServiceAvailable
        code
        name_en
        name_ch
      }
      isInteractiveServiceAvailable
      inplayDelay
      venue {
        code
        name_en
        name_ch
      }
      tvChannels {
        code
        name_en
        name_ch
      }
      liveEvents {
        id
        code
      }
      featureStartTime
      featureMatchSequence
      poolInfo {
        normalPools
        inplayPools
        sellingPools
        ntsInfo
        entInfo
        definedPools
      }
      runningResult {
        homeScore
        awayScore
        corner
        homeCorner
        awayCorner
      }
      runningResultExtra {
        homeScore
        awayScore
        corner
        homeCorner
        awayCorner
      }
      adminOperation {
        remark {
          typ
        }
      }
      foPools(fbOddsTypes: $fbOddsTypes) {
        id
        status
        oddsType
        instNo
        inplay
        name_ch
        name_en
        updateAt
        expectedSuspendDateTime
        lines {
          lineId
          status
          condition
          main
          combinations {
            combId
            str
            status
            offerEarlySettlement
            currentOdds
            selections {
              selId
              str
              name_ch
              name_en
            }
          }
        }
      }
    }
  }
"""

HISTORIC_FOOTBALL_MATCHES_QUERY = """
query matchResults($startDate: String, $endDate: String, $startIndex: Int,$endIndex: Int,$teamId: String) {
    timeOffset {
    fb
    }
    matchNumByDate(startDate: $startDate, endDate: $endDate, teamId: $teamId) {
    total
    }
    matches: matchResult(startDate: $startDate, endDate: $endDate, startIndex: $startIndex,endIndex: $endIndex, teamId: $teamId) {
    id
    status
    frontEndId
    matchDayOfWeek
    matchNumber
    matchDate
    kickOffTime
    sequence
    homeTeam {
        id
        name_en
        name_ch
    }
    awayTeam {
        id
        name_en
        name_ch
    }
    tournament {
        code
        name_en
        name_ch
    }
    results {
        homeResult
        awayResult
        ttlCornerResult
        resultConfirmType
        payoutConfirmed
        stageId
        resultType
        sequence
    }
    poolInfo {
        payoutRefundPools
        refundPools
        ntsInfo
        entInfo
        definedPools
        ngsInfo {
        str
        name_en
        name_ch
        instNo
        }
        agsInfo {
        str
        name_en
        name_ch
        }
    }
    }
}
"""

HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY = """
query matchResultDetails($matchId: String, $fbOddsTypes: [FBOddsType]!) {
  matches: matchResult(matchId: $matchId) {
    id
    foPools(fbOddsTypes: $fbOddsTypes, resultOnly: true) {
      id
      status
      oddsType
      instNo
      name_ch
      name_en
      lines(resultOnly: true) {
        combinations {
          str
          status
          winOrd
          selections {
            selId
            str
            name_ch
            name_en
          }
        }
      }
    }
    additionalResults {
      resSetId
      results {
        awayResult
        homeResult
        ttlCornerResult
        mask
        payoutConfirmed
        resultConfirmType
        resultType
        sequence
        stageId
      }
    }
  }
}
"""

# The reference client's default set (4 types) is batch 1; batch 2 carries the
# remaining spec odds types. Each call stays <= 4 types (verified per-call cap).
DEFAULT_ODDS_TYPES: list[str] = ["HAD", "HDC", "HIL", "CRS"]

ODDS_TYPE_BATCHES: list[list[str]] = [
    ["HAD", "HDC", "HIL", "CRS"],
    ["HHA", "CHD", "CHL"],
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_hkjc_queries.py -v`

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/providers/hkjc/__init__.py app/providers/hkjc/queries.py tests/test_hkjc_queries.py
git commit -m "feat: 加入 HKJC GraphQL 查詢文件模組"
```

---

### Task 7: HKJC GraphQL client (headers, gzip, throttle, retries)

**Files:**
- Create: `app/providers/hkjc/client.py`
- Test: `tests/test_hkjc_client.py`

**Interfaces:**
- Consumes: `httpx`.
- Produces: `app.providers.hkjc.client.HkjcGraphQLError(RuntimeError)`; `HkjcGraphQLClient(url, referer, origin, user_agent, throttle_seconds=1.5, max_retries=3, backoff_base=1.0, client=None)` with `async def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]` (returns the GraphQL `data` object) and `async def aclose(self) -> None`.

- [ ] **Step 1: Write the failing test `tests/test_hkjc_client.py`**

```python
import gzip
import json

import httpx
import pytest

from app.providers.hkjc.client import HkjcGraphQLClient, HkjcGraphQLError


def _client(handler, **kwargs) -> HkjcGraphQLClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HkjcGraphQLClient(
        url="https://example.test/graphql",
        referer="https://bet.hkjc.com/",
        origin="https://bet.hkjc.com",
        user_agent="test-agent",
        throttle_seconds=0.0,
        backoff_base=0.0,
        client=http,
        **kwargs,
    )


async def test_execute_sends_required_headers_and_returns_data():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"__typename": "Query"}})

    client = _client(handler)
    data = await client.execute("query { __typename }", {})
    assert data == {"__typename": "Query"}
    assert seen["headers"]["content-type"] == "application/json"
    assert seen["headers"]["referer"] == "https://bet.hkjc.com/"
    assert seen["headers"]["origin"] == "https://bet.hkjc.com"
    assert seen["headers"]["user-agent"] == "test-agent"
    assert seen["body"]["query"] == "query { __typename }"
    await client.aclose()


async def test_execute_decodes_gzip_body_without_content_encoding_header():
    def handler(request: httpx.Request) -> httpx.Response:
        raw = json.dumps({"data": {"ok": True}}).encode("utf-8")
        return httpx.Response(200, content=gzip.compress(raw))

    client = _client(handler)
    assert await client.execute("query { x }", {}) == {"ok": True}
    await client.aclose()


async def test_execute_retries_on_500_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"data": {"ok": True}})

    client = _client(handler, max_retries=2)
    assert await client.execute("query { x }", {}) == {"ok": True}
    assert calls["n"] == 2
    await client.aclose()


async def test_execute_raises_on_graphql_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "WHITELIST_ERROR"}]})

    client = _client(handler)
    with pytest.raises(HkjcGraphQLError):
        await client.execute("query { x }", {})
    await client.aclose()


async def test_execute_raises_after_exhausting_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    client = _client(handler, max_retries=1)
    with pytest.raises(HkjcGraphQLError):
        await client.execute("query { x }", {})
    await client.aclose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_hkjc_client.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.providers.hkjc.client'`.

- [ ] **Step 3: Implement `app/providers/hkjc/client.py`**

```python
import asyncio
import gzip
import json
import time
from typing import Any

import httpx


class HkjcGraphQLError(RuntimeError):
    """Raised when the HKJC GraphQL endpoint fails or returns GraphQL errors."""


class HkjcGraphQLClient:
    """Minimal async HKJC GraphQL client.

    Sends the four headers the spec verified, throttles to at most one request
    per ``throttle_seconds``, retries 5xx/timeouts with exponential backoff, and
    transparently handles gzip-encoded responses.
    """

    def __init__(
        self,
        url: str,
        referer: str,
        origin: str,
        user_agent: str,
        throttle_seconds: float = 1.5,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Referer": referer,
            "Origin": origin,
            "User-Agent": user_agent,
        }
        self._throttle_seconds = throttle_seconds
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        payload = {"query": query, "variables": variables}
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            await self._throttle()
            try:
                response = await self._client.post(self._url, headers=self._headers, json=payload)
            except httpx.HTTPError as exc:
                last_error = exc
                await self._backoff(attempt)
                continue
            if response.status_code >= 500:
                last_error = HkjcGraphQLError(f"HKJC returned HTTP {response.status_code}")
                await self._backoff(attempt)
                continue
            if response.status_code >= 400:
                raise HkjcGraphQLError(
                    f"HKJC returned HTTP {response.status_code}: {response.text[:200]}"
                )
            body = self._decode_json(response)
            if body.get("errors"):
                raise HkjcGraphQLError(f"HKJC GraphQL errors: {body['errors']}")
            data = body.get("data")
            if not isinstance(data, dict):
                raise HkjcGraphQLError("HKJC response missing 'data' object")
            return data
        raise HkjcGraphQLError(
            f"HKJC request failed after {self._max_retries + 1} attempts: {last_error}"
        )

    async def _throttle(self) -> None:
        async with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            wait = self._throttle_seconds - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    async def _backoff(self, attempt: int) -> None:
        if self._backoff_base > 0:
            await asyncio.sleep(min(self._backoff_base * (2**attempt), 8.0))

    @staticmethod
    def _decode_json(response: httpx.Response) -> dict[str, Any]:
        content = response.content
        if content[:2] == b"\x1f\x8b":
            content = gzip.decompress(content)
        return json.loads(content.decode("utf-8"))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_hkjc_client.py -v`

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/providers/hkjc/client.py tests/test_hkjc_client.py
git commit -m "feat: 實作 HKJC GraphQL 客戶端（標頭、gzip、節流與重試）"
```

---

### Task 8: HkjcProvider (fixtures, two-batch odds, results, payout details)

**Files:**
- Create: `app/providers/hkjc/provider.py`
- Create: `tests/fixtures/hkjc_football_matches.json`
- Create: `tests/fixtures/hkjc_historic_matches.json`
- Create: `tests/fixtures/hkjc_match_details.json`
- Test: `tests/test_hkjc_provider.py`

**Interfaces:**
- Consumes: `app.providers.base.{FixtureRecord, LeagueRecord, OddsRecord, Provider, ResultRecord}`, `app.providers.hkjc.client.HkjcGraphQLClient`, `app.providers.hkjc.queries.*`.
- Produces: `app.providers.hkjc.provider.HkjcProvider(client, tourn_ids=None)` implementing `Provider` (`name = "hkjc"`), plus `async def fetch_result_details(self, match_id: str) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing test `tests/test_hkjc_provider.py`**

```python
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.providers.hkjc.provider import HkjcProvider

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _FakeClient:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, query: str, variables: dict) -> dict:
        self.calls.append((query, variables))
        return self._responses.pop(0)


async def test_fetch_fixtures_parses_matches():
    client = _FakeClient([_load("hkjc_football_matches.json")["data"]])
    provider = HkjcProvider(client)
    fixtures = await provider.fetch_fixtures(date(2026, 10, 12), date(2026, 10, 15))
    assert len(fixtures) == 2
    first = fixtures[0]
    assert first.hkjc_match_id == "M-1001"
    assert first.league_name == "English Premier League"
    assert first.hkjc_tourn_id == "TOURN-EPL"
    assert first.kickoff_time == datetime(2026, 10, 12, 11, 30, tzinfo=UTC)
    assert first.status == "scheduled"
    assert first.home_team_name_en == "Manchester United"
    assert first.home_team_name_ch == "曼聯"
    assert first.away_team_hkjc_id == "T-2"
    assert first.venue == "Old Trafford"
    assert fixtures[1].status == "live"


async def test_fetch_fixtures_passes_date_range_and_tourn_ids():
    client = _FakeClient([_load("hkjc_football_matches.json")["data"]])
    provider = HkjcProvider(client, tourn_ids=["TOURN-EPL"])
    await provider.fetch_fixtures(date(2026, 10, 12), date(2026, 10, 15))
    _, variables = client.calls[0]
    assert variables["startDate"] == "2026-10-12"
    assert variables["endDate"] == "2026-10-15"
    assert variables["tournIds"] == ["TOURN-EPL"]
    assert variables["showAllMatch"] is False


async def test_fetch_odds_uses_two_batches_and_parses_pools():
    client = _FakeClient([_load("hkjc_football_matches.json")["data"], {"matches": []}])
    provider = HkjcProvider(client)
    fixtures = await provider.fetch_fixtures(date(2026, 10, 12), date(2026, 10, 15))
    client.calls.clear()
    records = await provider.fetch_odds(fixtures)
    assert len(records) == 3
    assert client.calls[0][1]["fbOddsTypes"] == ["HAD", "HDC", "HIL", "CRS"]
    assert client.calls[1][1]["fbOddsTypes"] == ["HHA", "CHD", "CHL"]
    assert client.calls[0][1]["fbOddsTypesM"] == ["HAD", "HDC", "HIL", "CRS"]
    assert {r.odds_type for r in records} == {"HAD", "HDC"}
    assert all(r.captured_at.tzinfo is not None for r in records)
    assert records[0].payload["oddsType"] in {"HAD", "HDC"}


async def test_fetch_results_parses_finished_matches_with_pagination():
    client = _FakeClient([_load("hkjc_historic_matches.json")["data"]])
    provider = HkjcProvider(client)
    records = await provider.fetch_results(date(2026, 10, 10), date(2026, 10, 12))
    assert len(records) == 2
    first = records[0]
    assert first.match_hkjc_id == "M-1001"
    assert first.home_score == 0
    assert first.away_score == 0
    assert first.ttl_corner == 9
    assert first.confirmed is True
    assert first.payout_confirmed is True
    _, variables = client.calls[0]
    assert variables["startIndex"] == 0
    assert variables["endIndex"] == 500


async def test_fetch_result_details_returns_payout_pools():
    client = _FakeClient([_load("hkjc_match_details.json")["data"]])
    provider = HkjcProvider(client)
    details = await provider.fetch_result_details("M-1001")
    assert details["id"] == "M-1001"
    assert details["foPools"][0]["lines"][0]["combinations"][0]["winOrd"] == "H"


@pytest.mark.live
async def test_live_hkjc_smoke():
    from app.config import get_settings
    from app.providers.hkjc.client import HkjcGraphQLClient

    settings = get_settings()
    client = HkjcGraphQLClient(
        url=settings.hkjc_graphql_url,
        referer=settings.hkjc_referer,
        origin=settings.hkjc_origin,
        user_agent=settings.hkjc_user_agent,
        throttle_seconds=settings.hkjc_throttle_seconds,
    )
    try:
        provider = HkjcProvider(client)
        today = datetime.now(UTC).date()
        fixtures = await provider.fetch_fixtures(today, today)
        assert isinstance(fixtures, list)
    finally:
        await client.aclose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_hkjc_provider.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.providers.hkjc.provider'`.

- [ ] **Step 3: Create the recorded fixtures**

`tests/fixtures/hkjc_football_matches.json`:

```json
{
  "data": {
    "matches": [
      {
        "id": "M-1001",
        "frontEndId": "FB1001",
        "matchDate": "2026-10-12",
        "kickOffTime": "2026-10-12T19:30:00+08:00",
        "status": "SCHEDULED",
        "updateAt": "2026-10-12T09:00:00+08:00",
        "sequence": 1,
        "esIndicatorEnabled": false,
        "homeTeam": {"id": "T-1", "name_en": "Manchester United", "name_ch": "曼聯"},
        "awayTeam": {"id": "T-2", "name_en": "Liverpool", "name_ch": "利物浦"},
        "tournament": {
          "id": "TOURN-EPL",
          "frontEndId": "EPL",
          "nameProfileId": "1",
          "isInteractiveServiceAvailable": true,
          "code": "EPL",
          "name_en": "English Premier League",
          "name_ch": "英格蘭超級聯賽"
        },
        "isInteractiveServiceAvailable": true,
        "inplayDelay": false,
        "venue": {"code": "OT", "name_en": "Old Trafford", "name_ch": "奧脫福球場"},
        "tvChannels": [],
        "liveEvents": [],
        "featureStartTime": null,
        "featureMatchSequence": null,
        "poolInfo": {
          "normalPools": true,
          "inplayPools": true,
          "sellingPools": true,
          "ntsInfo": null,
          "entInfo": null,
          "definedPools": []
        },
        "runningResult": null,
        "runningResultExtra": null,
        "adminOperation": null,
        "foPools": [
          {
            "id": "POOL-HAD-1",
            "status": "OPEN",
            "oddsType": "HAD",
            "instNo": 1,
            "inplay": false,
            "name_ch": "主客和",
            "name_en": "Home/Away/Draw",
            "updateAt": "2026-10-12T09:00:00+08:00",
            "expectedSuspendDateTime": null,
            "lines": [
              {
                "lineId": "L1",
                "status": "OPEN",
                "condition": null,
                "main": true,
                "combinations": [
                  {
                    "combId": "C1",
                    "str": "H",
                    "status": "OPEN",
                    "offerEarlySettlement": false,
                    "currentOdds": 2.1,
                    "selections": [
                      {"selId": "S1", "str": "H", "name_ch": "主", "name_en": "Home"}
                    ]
                  }
                ]
              }
            ]
          },
          {
            "id": "POOL-HDC-1",
            "status": "OPEN",
            "oddsType": "HDC",
            "instNo": 2,
            "inplay": false,
            "name_ch": "讓球",
            "name_en": "Handicap",
            "updateAt": "2026-10-12T09:00:00+08:00",
            "expectedSuspendDateTime": null,
            "lines": [
              {
                "lineId": "L2",
                "status": "OPEN",
                "condition": "-1",
                "main": true,
                "combinations": [
                  {
                    "combId": "C2",
                    "str": "H",
                    "status": "OPEN",
                    "offerEarlySettlement": false,
                    "currentOdds": 1.85,
                    "selections": [
                      {"selId": "S2", "str": "H", "name_ch": "主", "name_en": "Home"}
                    ]
                  }
                ]
              }
            ]
          }
        ]
      },
      {
        "id": "M-1002",
        "frontEndId": "FB1002",
        "matchDate": "2026-10-12",
        "kickOffTime": "2026-10-12T22:00:00+08:00",
        "status": "LIVE",
        "updateAt": "2026-10-12T22:20:00+08:00",
        "sequence": 2,
        "esIndicatorEnabled": false,
        "homeTeam": {"id": "T-3", "name_en": "Arsenal", "name_ch": "阿仙奴"},
        "awayTeam": {"id": "T-4", "name_en": "Chelsea", "name_ch": "車路士"},
        "tournament": {
          "id": "TOURN-EPL",
          "frontEndId": "EPL",
          "nameProfileId": "1",
          "isInteractiveServiceAvailable": true,
          "code": "EPL",
          "name_en": "English Premier League",
          "name_ch": "英格蘭超級聯賽"
        },
        "isInteractiveServiceAvailable": true,
        "inplayDelay": false,
        "venue": {"code": "EM", "name_en": "Emirates Stadium", "name_ch": "酋長球場"},
        "tvChannels": [],
        "liveEvents": [],
        "featureStartTime": null,
        "featureMatchSequence": null,
        "poolInfo": {
          "normalPools": true,
          "inplayPools": true,
          "sellingPools": true,
          "ntsInfo": null,
          "entInfo": null,
          "definedPools": []
        },
        "runningResult": {"homeScore": 1, "awayScore": 0, "corner": 3, "homeCorner": 2, "awayCorner": 1},
        "runningResultExtra": null,
        "adminOperation": null,
        "foPools": [
          {
            "id": "POOL-HAD-2",
            "status": "OPEN",
            "oddsType": "HAD",
            "instNo": 1,
            "inplay": true,
            "name_ch": "主客和",
            "name_en": "Home/Away/Draw",
            "updateAt": "2026-10-12T22:20:00+08:00",
            "expectedSuspendDateTime": null,
            "lines": [
              {
                "lineId": "L3",
                "status": "OPEN",
                "condition": null,
                "main": true,
                "combinations": [
                  {
                    "combId": "C3",
                    "str": "H",
                    "status": "OPEN",
                    "offerEarlySettlement": false,
                    "currentOdds": 1.55,
                    "selections": [
                      {"selId": "S3", "str": "H", "name_ch": "主", "name_en": "Home"}
                    ]
                  }
                ]
              }
            ]
          }
        ]
      }
    ]
  }
}
```

`tests/fixtures/hkjc_historic_matches.json`:

```json
{
  "data": {
    "timeOffset": {"fb": 8},
    "matchNumByDate": {"total": 2},
    "matches": [
      {
        "id": "M-1001",
        "status": "FINISHED",
        "frontEndId": "FB1001",
        "matchDayOfWeek": "MON",
        "matchNumber": 1,
        "matchDate": "2026-10-12",
        "kickOffTime": "2026-10-12T19:30:00+08:00",
        "sequence": 1,
        "homeTeam": {"id": "T-1", "name_en": "Manchester United", "name_ch": "曼聯"},
        "awayTeam": {"id": "T-2", "name_en": "Liverpool", "name_ch": "利物浦"},
        "tournament": {"code": "EPL", "name_en": "English Premier League", "name_ch": "英格蘭超級聯賽"},
        "results": [
          {
            "homeResult": "0",
            "awayResult": "0",
            "ttlCornerResult": "9",
            "resultConfirmType": "CONFIRMED",
            "payoutConfirmed": true,
            "stageId": null,
            "resultType": "FINAL",
            "sequence": 1
          }
        ],
        "poolInfo": {
          "payoutRefundPools": [],
          "refundPools": [],
          "ntsInfo": null,
          "entInfo": null,
          "definedPools": [],
          "ngsInfo": null,
          "agsInfo": null
        }
      },
      {
        "id": "M-1002",
        "status": "FINISHED",
        "frontEndId": "FB1002",
        "matchDayOfWeek": "MON",
        "matchNumber": 2,
        "matchDate": "2026-10-12",
        "kickOffTime": "2026-10-12T22:00:00+08:00",
        "sequence": 2,
        "homeTeam": {"id": "T-3", "name_en": "Arsenal", "name_ch": "阿仙奴"},
        "awayTeam": {"id": "T-4", "name_en": "Chelsea", "name_ch": "車路士"},
        "tournament": {"code": "EPL", "name_en": "English Premier League", "name_ch": "英格蘭超級聯賽"},
        "results": [
          {
            "homeResult": "2",
            "awayResult": "1",
            "ttlCornerResult": "11",
            "resultConfirmType": "CONFIRMED",
            "payoutConfirmed": false,
            "stageId": null,
            "resultType": "FINAL",
            "sequence": 1
          }
        ],
        "poolInfo": {
          "payoutRefundPools": [],
          "refundPools": [],
          "ntsInfo": null,
          "entInfo": null,
          "definedPools": [],
          "ngsInfo": null,
          "agsInfo": null
        }
      }
    ]
  }
}
```

`tests/fixtures/hkjc_match_details.json`:

```json
{
  "data": {
    "matches": {
      "id": "M-1001",
      "foPools": [
        {
          "id": "POOL-HAD-1",
          "status": "SETTLED",
          "oddsType": "HAD",
          "instNo": 1,
          "name_ch": "主客和",
          "name_en": "Home/Away/Draw",
          "lines": [
            {
              "combinations": [
                {
                  "str": "H",
                  "status": "SETTLED",
                  "winOrd": "H",
                  "selections": [
                    {"selId": "S1", "str": "H", "name_ch": "主", "name_en": "Home"}
                  ]
                }
              ]
            }
          ]
        }
      ],
      "additionalResults": {
        "resSetId": "RS-1",
        "results": [
          {
            "awayResult": "0",
            "homeResult": "0",
            "ttlCornerResult": "9",
            "mask": null,
            "payoutConfirmed": true,
            "resultConfirmType": "CONFIRMED",
            "resultType": "FINAL",
            "sequence": 1,
            "stageId": null
          }
        ]
      }
    }
  }
}
```

- [ ] **Step 4: Implement `app/providers/hkjc/provider.py`**

```python
from datetime import UTC, date, datetime
from typing import Any

from app.providers.base import FixtureRecord, LeagueRecord, OddsRecord, ResultRecord
from app.providers.hkjc.client import HkjcGraphQLClient
from app.providers.hkjc.queries import (
    FOOTBALL_MATCHES_QUERY,
    HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY,
    HISTORIC_FOOTBALL_MATCHES_QUERY,
    ODDS_TYPE_BATCHES,
)

DATE_FORMAT = "%Y-%m-%d"
RESULT_PAGE_SIZE = 500

_STATUS_MAP = {
    "SCHEDULED": "scheduled",
    "LIVE": "live",
    "FINISHED": "finished",
    "POSTPONED": "postponed",
    "ABANDONED": "abandoned",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
}


def _parse_datetime(value: str) -> datetime:
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Unrecognised HKJC datetime: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _map_status(value: str | None) -> str:
    if not value:
        return "scheduled"
    return _STATUS_MAP.get(value.upper(), "scheduled")


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


class HkjcProvider:
    """HKJC GraphQL provider. All HKJC specifics live behind this class."""

    name = "hkjc"

    def __init__(self, client: HkjcGraphQLClient, tourn_ids: list[str] | None = None) -> None:
        self._client = client
        self._tourn_ids = tourn_ids

    async def fetch_leagues(self) -> list[LeagueRecord]:
        return []

    async def fetch_fixtures(self, date_from: date, date_to: date) -> list[FixtureRecord]:
        variables = {
            "startDate": date_from.strftime(DATE_FORMAT),
            "endDate": date_to.strftime(DATE_FORMAT),
            "matchIds": None,
            "tournIds": self._tourn_ids,
            "fbOddsTypes": ["HAD"],
            "fbOddsTypesM": ["HAD"],
            "inplayOnly": False,
            "featuredMatchesOnly": False,
            "frontEndIds": None,
            "earlySettlementOnly": False,
            "showAllMatch": False,
        }
        data = await self._client.execute(FOOTBALL_MATCHES_QUERY, variables)
        return [self._to_fixture(item) for item in data.get("matches") or []]

    def _to_fixture(self, item: dict[str, Any]) -> FixtureRecord:
        tournament = item.get("tournament") or {}
        home = item.get("homeTeam") or {}
        away = item.get("awayTeam") or {}
        venue = item.get("venue") or {}
        return FixtureRecord(
            source=self.name,
            league_name=tournament.get("name_en") or tournament.get("code") or "Unknown",
            hkjc_tourn_id=_optional_str(tournament.get("id")),
            hkjc_match_id=_optional_str(item.get("id")),
            kickoff_time=_parse_datetime(item["kickOffTime"]),
            status=_map_status(item.get("status")),
            home_team_name_en=home.get("name_en") or "",
            home_team_name_ch=home.get("name_ch"),
            home_team_hkjc_id=_optional_str(home.get("id")),
            away_team_name_en=away.get("name_en") or "",
            away_team_name_ch=away.get("name_ch"),
            away_team_hkjc_id=_optional_str(away.get("id")),
            venue=venue.get("name_en"),
            round=None,
            raw=item,
        )

    async def fetch_odds(self, fixtures: list[FixtureRecord]) -> list[OddsRecord]:
        match_ids = [f.hkjc_match_id for f in fixtures if f.hkjc_match_id]
        if not match_ids:
            return []
        captured_at = datetime.now(UTC)
        records: list[OddsRecord] = []
        for batch in ODDS_TYPE_BATCHES:
            variables = {
                "startDate": None,
                "endDate": None,
                "matchIds": match_ids,
                "tournIds": None,
                "fbOddsTypes": batch,
                "fbOddsTypesM": batch,
                "inplayOnly": False,
                "featuredMatchesOnly": False,
                "frontEndIds": None,
                "earlySettlementOnly": False,
                "showAllMatch": True,
            }
            data = await self._client.execute(FOOTBALL_MATCHES_QUERY, variables)
            for item in data.get("matches") or []:
                match_id = _optional_str(item.get("id"))
                if match_id is None:
                    continue
                for pool in item.get("foPools") or []:
                    records.append(
                        OddsRecord(
                            match_hkjc_id=match_id,
                            odds_type=pool["oddsType"],
                            inplay=bool(pool.get("inplay")),
                            captured_at=captured_at,
                            payload=pool,
                        )
                    )
        return records

    async def fetch_results(self, date_from: date, date_to: date) -> list[ResultRecord]:
        variables = {
            "startDate": date_from.strftime(DATE_FORMAT),
            "endDate": date_to.strftime(DATE_FORMAT),
            "startIndex": 0,
            "endIndex": RESULT_PAGE_SIZE,
            "teamId": None,
        }
        data = await self._client.execute(HISTORIC_FOOTBALL_MATCHES_QUERY, variables)
        records: list[ResultRecord] = []
        for item in data.get("matches") or []:
            results = item.get("results") or []
            if not results:
                continue
            result = results[0]
            ttl = result.get("ttlCornerResult")
            records.append(
                ResultRecord(
                    match_hkjc_id=_optional_str(item.get("id")),
                    home_score=int(result["homeResult"]),
                    away_score=int(result["awayResult"]),
                    ttl_corner=int(ttl) if ttl is not None else None,
                    source=self.name,
                    confirmed=True,
                    payout_confirmed=bool(result.get("payoutConfirmed")),
                    raw=item,
                )
            )
        return records

    async def fetch_result_details(self, match_id: str) -> dict[str, Any]:
        variables = {
            "matchId": match_id,
            "fbOddsTypes": ["HAD", "HDC", "HIL", "CRS", "HHA", "CHD", "CHL"],
        }
        data = await self._client.execute(HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY, variables)
        return data.get("matches") or {}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_hkjc_provider.py -v`

Expected: `5 passed, 1 deselected` (the `live` test is deselected by the default `-m 'not live'`).

- [ ] **Step 6: Run the opt-in live smoke test (manual, once, hits the real endpoint)**

Run: `uv run pytest tests/test_hkjc_provider.py -m live -v`

Expected: `1 passed` (or a clear network error if HKJC is unreachable — that is not a code failure).

- [ ] **Step 7: Commit**

```bash
git add app/providers/hkjc/provider.py tests/fixtures/hkjc_football_matches.json tests/fixtures/hkjc_historic_matches.json tests/fixtures/hkjc_match_details.json tests/test_hkjc_provider.py
git commit -m "feat: 實作 HkjcProvider（賽程、兩批次賠率、賽果與派彩細節）"
```

---

### Task 9: FootballDataProvider (CSV results + historical backfill records)

**Files:**
- Create: `app/providers/football_data/__init__.py`
- Create: `app/providers/football_data/provider.py`
- Create: `tests/fixtures/football_data_E0_2627.csv`
- Test: `tests/test_football_data_provider.py`

**Interfaces:**
- Consumes: `app.providers.base.{FixtureRecord, LeagueRecord, OddsRecord, ResultRecord}`, `httpx`.
- Produces: `app.providers.football_data.provider.FootballDataProvider(base_url, client=None, divisions=None)` (`name = "football_data"`) implementing `Provider`, plus `async def fetch_historical(self, season_start_year: int, divisions: list[str] | None = None) -> list[HistoricalMatchRecord]` and `async def aclose(self) -> None`; `HistoricalMatchRecord(division, league_code, season_label, match_date, kickoff_time, home_team_name, away_team_name, home_score, away_score, odds)`; helpers `season_code(year) -> str`, `DIVISIONS: dict[str, str]`.

- [ ] **Step 1: Write the failing test `tests/test_football_data_provider.py`**

```python
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from app.providers.football_data.provider import FootballDataProvider, season_code

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://www.football-data.co.uk"


def _client() -> httpx.AsyncClient:
    csv_bytes = (FIXTURES / "football_data_E0_2627.csv").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/E0.csv"):
            return httpx.Response(200, content=csv_bytes)
        return httpx.Response(404, text="not found")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_season_code():
    assert season_code(2026) == "2627"
    assert season_code(2010) == "1011"
    assert season_code(1999) == "9900"


async def test_fetch_results_parses_and_filters_by_date():
    provider = FootballDataProvider(BASE_URL, client=_client(), divisions=["E0"])
    records = await provider.fetch_results(date(2026, 8, 21), date(2026, 8, 22))
    assert len(records) == 3
    first = records[0]
    assert first.match_date == date(2026, 8, 21)
    assert first.home_team_name == "Arsenal"
    assert first.away_team_name == "Coventry"
    assert first.home_score == 3
    assert first.away_score == 0
    assert first.source == "football_data"
    assert first.confirmed is False
    assert first.ttl_corner is None
    await provider.aclose()


async def test_fetch_results_skips_unplayed_rows():
    provider = FootballDataProvider(BASE_URL, client=_client(), divisions=["E0"])
    records = await provider.fetch_results(date(2026, 8, 22), date(2026, 8, 22))
    assert all(r.home_team_name != "Man City" for r in records)
    await provider.aclose()


async def test_fetch_results_uses_expected_url():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=(FIXTURES / "football_data_E0_2627.csv").read_bytes())

    provider = FootballDataProvider(
        BASE_URL, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), divisions=["E0"]
    )
    await provider.fetch_results(date(2026, 8, 21), date(2026, 8, 21))
    assert seen == ["https://www.football-data.co.uk/mmz4281/2627/E0.csv"]
    await provider.aclose()


async def test_fetch_historical_returns_odds():
    provider = FootballDataProvider(BASE_URL, client=_client(), divisions=["E0"])
    records = await provider.fetch_historical(2026)
    assert len(records) == 3
    first = records[0]
    assert first.league_code == "EPL"
    assert first.season_label == "2026/27"
    assert first.odds["B365"]["open"] == [1.2, 7.0, 13.0]
    assert first.odds["B365"]["close"] == [1.18, 7.5, 13.0]
    assert first.kickoff_time == datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
    await provider.aclose()


async def test_fetch_historical_returns_empty_for_missing_division():
    provider = FootballDataProvider(BASE_URL, client=_client(), divisions=["SP1"])
    assert await provider.fetch_historical(2026) == []
    await provider.aclose()


@pytest.mark.live
async def test_live_football_data_smoke():
    provider = FootballDataProvider(BASE_URL, divisions=["E0"])
    try:
        records = await provider.fetch_results(date(2026, 8, 21), date(2026, 8, 22))
        assert isinstance(records, list)
    finally:
        await provider.aclose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_football_data_provider.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.providers.football_data'`.

- [ ] **Step 3: Create the recorded fixture `tests/fixtures/football_data_E0_2627.csv`**

```csv
Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,PPH,PPD,PPA,MaxH,MaxD,MaxA,AvgH,AvgD,AvgA,B365CH,B365CD,B365CA,PPCH,PPCD,PPCA,MaxCH,MaxCD,MaxCA,AvgCH,AvgCD,AvgCA
E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H,1.2,7,13,1.17,7,15,1.23,7.5,16.5,1.19,6.77,14.19,1.18,7.5,13,1.17,7,15,1.22,7.5,16,1.2,6.72,14
E0,22/08/2026,12:30,Hull,Man United,2,0,H,8.5,5,1.36,8.5,4.75,1.33,9,5.25,1.39,8.37,4.93,1.36,9,5,1.33,8.5,5,1.33,9,5.5,1.37,8.49,5.11,1.34
E0,22/08/2026,15:00,Everton,Crystal Palace,2,0,H,2.15,3.5,3.3,2.1,3.3,3.2,2.15,3.3,3.3,2.23,3.4,3.24,2.38,3.4,3,2.25,3.25,3,2.38,3.5,3.2,2.32,3.36,3.05
E0,22/08/2026,17:30,Man City,Bournemouth,,,,1.48,4.5,6.25,1.44,4.5,6,1.48,5,6.6,1.45,4.72,5.93,,,,,,,,,,,,
```

- [ ] **Step 4: Implement `app/providers/football_data/provider.py` and `app/providers/football_data/__init__.py`**

`app/providers/football_data/__init__.py`:

```python
"""football-data.co.uk CSV provider (results fallback + historical backfill)."""
```

`app/providers/football_data/provider.py`:

```python
import csv
import io
from datetime import UTC, date, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.providers.base import FixtureRecord, LeagueRecord, OddsRecord, ResultRecord

DIVISIONS: dict[str, str] = {
    "E0": "EPL",
    "SP1": "LALIGA",
    "I1": "SERIEA",
    "D1": "BUNDESLIGA",
    "F1": "LIGUE1",
}

# bookmaker -> (open_home, open_draw, open_away, close_home, close_draw, close_away)
BOOKMAKERS: dict[str, tuple[str, str, str, str, str, str]] = {
    "B365": ("B365H", "B365D", "B365A", "B365CH", "B365CD", "B365CA"),
    "PP": ("PPH", "PPD", "PPA", "PPCH", "PPCD", "PPCA"),
    "Max": ("MaxH", "MaxD", "MaxA", "MaxCH", "MaxCD", "MaxCA"),
    "Avg": ("AvgH", "AvgD", "AvgA", "AvgCH", "AvgCD", "AvgCA"),
}


class HistoricalMatchRecord(BaseModel):
    division: str
    league_code: str
    season_label: str
    match_date: date
    kickoff_time: datetime
    home_team_name: str
    away_team_name: str
    home_score: int
    away_score: int
    odds: dict[str, dict[str, list[float | None]]] = Field(default_factory=dict)


def season_code(year: int) -> str:
    return f"{year % 100:02d}{(year + 1) % 100:02d}"


def _season_start_year(value: date) -> int:
    return value.year if value.month >= 7 else value.year - 1


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    number = _to_float(value)
    return None if number is None else int(number)


def _parse_date(value: str) -> date:
    text = value.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised football-data date: {value!r}")


def _parse_kickoff(match_date: date, time_text: str | None) -> datetime:
    text = (time_text or "").strip()
    hour, minute = 12, 0
    if ":" in text:
        parts = text.split(":")
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            hour, minute = 12, 0
    return datetime(match_date.year, match_date.month, match_date.day, hour, minute, tzinfo=UTC)


def _parse_odds(row: dict[str, str]) -> dict[str, dict[str, list[float | None]]]:
    odds: dict[str, dict[str, list[float | None]]] = {}
    for bookmaker, (oh, od, oa, ch, cd, ca) in BOOKMAKERS.items():
        opening = [_to_float(row.get(oh)), _to_float(row.get(od)), _to_float(row.get(oa))]
        closing = [_to_float(row.get(ch)), _to_float(row.get(cd)), _to_float(row.get(ca))]
        if any(v is not None for v in opening) or any(v is not None for v in closing):
            odds[bookmaker] = {"open": opening, "close": closing}
    return odds


class FootballDataProvider:
    """Downloads football-data.co.uk season CSVs. Big-5 divisions only (UCL is absent)."""

    name = "football_data"

    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        divisions: list[str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._divisions = divisions or list(DIVISIONS)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_leagues(self) -> list[LeagueRecord]:
        return []

    async def fetch_fixtures(self, date_from: date, date_to: date) -> list[FixtureRecord]:
        return []

    async def fetch_odds(self, fixtures: list[FixtureRecord]) -> list[OddsRecord]:
        return []

    async def fetch_results(self, date_from: date, date_to: date) -> list[ResultRecord]:
        season = season_code(_season_start_year(date_from))
        records: list[ResultRecord] = []
        for division in self._divisions:
            for row in await self._download(season, division):
                match_date = _parse_date(row["Date"])
                if not (date_from <= match_date <= date_to):
                    continue
                home_score = _to_int(row.get("FTHG"))
                away_score = _to_int(row.get("FTAG"))
                if home_score is None or away_score is None:
                    continue
                records.append(
                    ResultRecord(
                        match_date=match_date,
                        home_team_name=row["HomeTeam"].strip(),
                        away_team_name=row["AwayTeam"].strip(),
                        home_score=home_score,
                        away_score=away_score,
                        ttl_corner=None,
                        source=self.name,
                        confirmed=False,
                        payout_confirmed=False,
                        raw=row,
                    )
                )
        return records

    async def fetch_historical(
        self, season_start_year: int, divisions: list[str] | None = None
    ) -> list[HistoricalMatchRecord]:
        season = season_code(season_start_year)
        label = f"{season_start_year}/{season_start_year + 1}"
        records: list[HistoricalMatchRecord] = []
        for division in divisions or self._divisions:
            for row in await self._download(season, division):
                home_score = _to_int(row.get("FTHG"))
                away_score = _to_int(row.get("FTAG"))
                if home_score is None or away_score is None:
                    continue
                match_date = _parse_date(row["Date"])
                records.append(
                    HistoricalMatchRecord(
                        division=division,
                        league_code=DIVISIONS.get(division, division),
                        season_label=label,
                        match_date=match_date,
                        kickoff_time=_parse_kickoff(match_date, row.get("Time")),
                        home_team_name=row["HomeTeam"].strip(),
                        away_team_name=row["AwayTeam"].strip(),
                        home_score=home_score,
                        away_score=away_score,
                        odds=_parse_odds(row),
                    )
                )
        return records

    async def _download(self, season: str, division: str) -> list[dict[str, Any]]:
        url = f"{self._base_url}/mmz4281/{season}/{division}.csv"
        response = await self._client.get(url)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        text = response.content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_football_data_provider.py -v`

Expected: `6 passed, 1 deselected`.

- [ ] **Step 6: Commit**

```bash
git add app/providers/football_data/__init__.py app/providers/football_data/provider.py tests/fixtures/football_data_E0_2627.csv tests/test_football_data_provider.py
git commit -m "feat: 實作 FootballDataProvider（CSV 賽果與歷史回填資料）"
```

---

### Task 10: Team-name alias matching

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/alias.py`
- Create: `app/data/__init__.py`
- Create: `app/data/team_aliases.json`
- Test: `tests/test_alias.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `app.services.alias.normalize_team_name(name: str) -> str`, `load_alias_map(path: Path | None = None) -> dict[str, str]`, `TeamMatcher(teams, alias_map=None)` with `match(name: str) -> Any | None` (returns the matching team object or `None`), and `FUZZY_THRESHOLD: float`.

- [ ] **Step 1: Write the failing test `tests/test_alias.py`**

```python
from dataclasses import dataclass, field

from app.services.alias import TeamMatcher, load_alias_map, normalize_team_name


@dataclass
class _Team:
    name_en: str
    name_ch: str | None = None
    aliases: list[str] = field(default_factory=list)


def _teams() -> list[_Team]:
    return [
        _Team("Manchester United", "曼聯", ["Man Utd", "Man United"]),
        _Team("Manchester City", "曼城", ["Man City"]),
        _Team("Tottenham Hotspur", "熱刺", ["Tottenham", "Spurs"]),
        _Team("Liverpool", "利物浦", ["Liverpool FC"]),
    ]


def test_normalize_team_name():
    assert normalize_team_name("Manchester United FC") == "manchester united"
    assert normalize_team_name("Nott'm Forest") == "nott m forest"
    assert normalize_team_name("Atlético Madrid") == "atletico madrid"
    assert normalize_team_name("  曼聯  ") == "曼聯"


def test_alias_map_loads_canonical_names():
    alias_map = load_alias_map()
    assert alias_map[normalize_team_name("曼聯")] == "Manchester United"
    assert alias_map[normalize_team_name("Spurs")] == "Tottenham Hotspur"


def test_match_by_chinese_name():
    matcher = TeamMatcher(_teams())
    assert matcher.match("曼聯").name_en == "Manchester United"


def test_match_by_alias():
    matcher = TeamMatcher(_teams())
    assert matcher.match("Man Utd").name_en == "Manchester United"
    assert matcher.match("Spurs").name_en == "Tottenham Hotspur"


def test_match_by_canonical_name():
    matcher = TeamMatcher(_teams())
    assert matcher.match("Manchester United").name_en == "Manchester United"


def test_match_fuzzy_typo():
    matcher = TeamMatcher(_teams())
    assert matcher.match("Manchester Untied").name_en == "Manchester United"


def test_match_returns_none_for_unknown():
    matcher = TeamMatcher(_teams())
    assert matcher.match("Real Madrid") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_alias.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.services'`.

- [ ] **Step 3: Implement `app/services/alias.py`, `app/services/__init__.py`, `app/data/__init__.py`, and `app/data/team_aliases.json`**

`app/services/__init__.py`:

```python
"""Ingestion services: fixture sync, odds sync, result reconciliation, alias matching."""
```

`app/data/__init__.py`:

```python
"""Static seed data (leagues, team aliases)."""
```

`app/services/alias.py`:

```python
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ALIASES_PATH = Path(__file__).resolve().parent.parent / "data" / "team_aliases.json"
FUZZY_THRESHOLD = 0.85
_STRIP_TOKENS = {"fc", "afc", "cf", "sc", "club", "football", "futbol", "calcio"}


def normalize_team_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", text)
    tokens = [token for token in text.split() if token and token not in _STRIP_TOKENS]
    return " ".join(tokens)


def load_alias_map(path: Path | None = None) -> dict[str, str]:
    raw = json.loads((path or ALIASES_PATH).read_text(encoding="utf-8"))
    index: dict[str, str] = {}
    for canonical, aliases in raw.items():
        index[normalize_team_name(canonical)] = canonical
        for alias in aliases:
            index[normalize_team_name(alias)] = canonical
    return index


class TeamMatcher:
    """Matches a source team name against known teams by exact key, curated alias, then fuzzy."""

    def __init__(self, teams: list[Any], alias_map: dict[str, str] | None = None) -> None:
        self._teams = list(teams)
        self._alias_map = alias_map if alias_map is not None else load_alias_map()
        self._by_key: dict[str, Any] = {}
        for team in self._teams:
            candidates = [team.name_en, team.name_ch, *(team.aliases or [])]
            for candidate in candidates:
                if candidate:
                    self._by_key.setdefault(normalize_team_name(candidate), team)

    def match(self, name: str) -> Any | None:
        key = normalize_team_name(name)
        if not key:
            return None
        if key in self._by_key:
            return self._by_key[key]
        canonical = self._alias_map.get(key)
        if canonical is not None:
            canonical_key = normalize_team_name(canonical)
            if canonical_key in self._by_key:
                return self._by_key[canonical_key]
        best: Any | None = None
        best_ratio = 0.0
        for candidate_key, team in self._by_key.items():
            ratio = SequenceMatcher(None, key, candidate_key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = team
        if best is not None and best_ratio >= FUZZY_THRESHOLD:
            return best
        return None
```

`app/data/team_aliases.json`:

```json
{
  "Manchester United": ["Man Utd", "Man United", "曼聯", "曼联"],
  "Manchester City": ["Man City", "曼城"],
  "Liverpool": ["Liverpool FC", "利物浦"],
  "Arsenal": ["Arsenal FC", "阿仙奴", "阿森纳"],
  "Chelsea": ["Chelsea FC", "車路士", "切尔西"],
  "Tottenham Hotspur": ["Tottenham", "Spurs", "熱刺", "热刺"],
  "Newcastle United": ["Newcastle", "紐卡素", "纽卡斯尔"],
  "Everton": ["Everton FC", "愛華頓", "埃弗顿"],
  "Aston Villa": ["Villa", "阿士東維拉", "阿斯顿维拉"],
  "West Ham United": ["West Ham", "韋斯咸", "西汉姆"],
  "Brighton & Hove Albion": ["Brighton", "白禮頓", "布莱顿"],
  "Real Madrid": ["皇馬", "皇家馬德里", "皇家马德里"],
  "Barcelona": ["FC Barcelona", "巴塞隆拿", "巴塞罗那", "巴薩"],
  "Atletico Madrid": ["Atlético Madrid", "馬德里體育會", "马德里竞技"],
  "Bayern Munich": ["Bayern München", "拜仁慕尼黑", "拜仁"],
  "Borussia Dortmund": ["Dortmund", "多蒙特", "多特蒙德"],
  "Juventus": ["祖雲達斯", "尤文图斯"],
  "Inter Milan": ["Inter", "國際米蘭", "国际米兰"],
  "AC Milan": ["米蘭", "AC米蘭", "AC米兰"],
  "Paris Saint-Germain": ["PSG", "巴黎聖日耳門", "巴黎圣日耳曼"]
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_alias.py -v`

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/services/__init__.py app/services/alias.py app/data/__init__.py app/data/team_aliases.json tests/test_alias.py
git commit -m "feat: 實作球隊名稱別名與模糊比對"
```

---

### Task 11: Ingestion-run tracking and league seed data

**Files:**
- Create: `app/services/runs.py`
- Create: `app/data/leagues.py`
- Test: `tests/test_runs.py`

**Interfaces:**
- Consumes: `app.db.models.{IngestionRun, League}`, `app.db.session.Database`.
- Produces: `app.services.runs.track_run(session_factory, job: str, work: Callable[[AsyncSession], Awaitable[int]]) -> int`; `app.services.runs.flag_manual_review(session_factory, job: str, match_ids: list[int]) -> None`; `app.data.leagues.LEAGUE_SEED: list[dict]`; `app.data.leagues.seed_leagues(session: AsyncSession) -> int`.

- [ ] **Step 1: Write the failing test `tests/test_runs.py`**

```python
import pytest
from sqlalchemy import select

from app.data.leagues import seed_leagues
from app.db.base import Base
from app.db.models import IngestionRun, League
from app.db.session import Database
from app.services.runs import flag_manual_review, track_run


async def _db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return db


async def test_track_run_records_success(tmp_path):
    db = await _db(tmp_path)
    try:
        async def work(session) -> int:
            return 7

        count = await track_run(db.session_factory, "sync_odds", work)
        assert count == 7
        async with db.session_factory() as session:
            run = (await session.execute(select(IngestionRun))).scalar_one()
            assert run.job == "sync_odds"
            assert run.status == "success"
            assert run.records_upserted == 7
            assert run.finished_at is not None
    finally:
        await db.dispose()


async def test_track_run_records_failure(tmp_path):
    db = await _db(tmp_path)
    try:
        async def work(session) -> int:
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await track_run(db.session_factory, "settle_results", work)
        async with db.session_factory() as session:
            run = (await session.execute(select(IngestionRun))).scalar_one()
            assert run.status == "failed"
            assert "ValueError" in (run.error or "")
    finally:
        await db.dispose()


async def test_flag_manual_review_writes_row(tmp_path):
    db = await _db(tmp_path)
    try:
        await flag_manual_review(db.session_factory, "manual_review", [11, 22])
        async with db.session_factory() as session:
            run = (await session.execute(select(IngestionRun))).scalar_one()
            assert run.job == "manual_review"
            assert run.status == "flagged"
            assert run.records_upserted == 2
            assert "11" in (run.error or "")
    finally:
        await db.dispose()


async def test_flag_manual_review_noop_when_empty(tmp_path):
    db = await _db(tmp_path)
    try:
        await flag_manual_review(db.session_factory, "manual_review", [])
        async with db.session_factory() as session:
            assert (await session.execute(select(IngestionRun))).scalars().all() == []
    finally:
        await db.dispose()


async def test_seed_leagues_is_idempotent(tmp_path):
    db = await _db(tmp_path)
    try:
        async with db.session_factory() as session:
            assert await seed_leagues(session) == 6
            await session.commit()
        async with db.session_factory() as session:
            assert await seed_leagues(session) == 0
            await session.commit()
            leagues = (await session.execute(select(League))).scalars().all()
            assert {league.code for league in leagues} == {
                "EPL",
                "LALIGA",
                "SERIEA",
                "BUNDESLIGA",
                "LIGUE1",
                "UCL",
            }
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_runs.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.services.runs'`.

- [ ] **Step 3: Implement `app/services/runs.py` and `app/data/leagues.py`**

`app/services/runs.py`:

```python
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import IngestionRun


async def track_run(
    session_factory: async_sessionmaker[AsyncSession],
    job: str,
    work: Callable[[AsyncSession], Awaitable[int]],
) -> int:
    """Run ``work`` inside one transaction and record an ingestion_runs row.

    Failures are recorded (status="failed") and re-raised so the scheduler can log them.
    """
    async with session_factory() as session:
        run = IngestionRun(job=job, started_at=datetime.now(UTC), status="running")
        session.add(run)
        await session.commit()
        run_id = run.id
    try:
        async with session_factory() as session:
            count = await work(session)
            await session.commit()
    except Exception as exc:
        async with session_factory() as session:
            failed = await session.get(IngestionRun, run_id)
            if failed is not None:
                failed.status = "failed"
                failed.finished_at = datetime.now(UTC)
                failed.error = f"{type(exc).__name__}: {exc}"
                await session.commit()
        raise
    async with session_factory() as session:
        finished = await session.get(IngestionRun, run_id)
        if finished is not None:
            finished.status = "success"
            finished.finished_at = datetime.now(UTC)
            finished.records_upserted = count
            await session.commit()
    return count


async def flag_manual_review(
    session_factory: async_sessionmaker[AsyncSession],
    job: str,
    match_ids: list[int],
) -> None:
    """Record unresolved matches for manual review. No-op when the list is empty."""
    if not match_ids:
        return
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add(
            IngestionRun(
                job=job,
                started_at=now,
                finished_at=now,
                status="flagged",
                records_upserted=len(match_ids),
                error=json.dumps({"unresolved_match_ids": match_ids}),
            )
        )
        await session.commit()
```

`app/data/leagues.py`:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import League

LEAGUE_SEED: list[dict[str, str]] = [
    {
        "code": "EPL",
        "name_en": "English Premier League",
        "name_ch": "英格蘭超級聯賽",
        "country": "England",
    },
    {
        "code": "LALIGA",
        "name_en": "Spanish La Liga",
        "name_ch": "西班牙甲組聯賽",
        "country": "Spain",
    },
    {
        "code": "SERIEA",
        "name_en": "Italian Serie A",
        "name_ch": "意大利甲組聯賽",
        "country": "Italy",
    },
    {
        "code": "BUNDESLIGA",
        "name_en": "German Bundesliga",
        "name_ch": "德國甲組聯賽",
        "country": "Germany",
    },
    {
        "code": "LIGUE1",
        "name_en": "French Ligue 1",
        "name_ch": "法國甲組聯賽",
        "country": "France",
    },
    {
        "code": "UCL",
        "name_en": "UEFA Champions League",
        "name_ch": "歐洲聯賽冠軍盃",
        "country": "Europe",
    },
]


async def seed_leagues(session: AsyncSession) -> int:
    """Insert any missing whitelisted leagues. Returns the number inserted."""
    inserted = 0
    for row in LEAGUE_SEED:
        existing = (
            await session.execute(select(League).where(League.code == row["code"]))
        ).scalar_one_or_none()
        if existing is None:
            session.add(League(**row))
            inserted += 1
    await session.flush()
    return inserted
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_runs.py -v`

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/services/runs.py app/data/leagues.py tests/test_runs.py
git commit -m "feat: 新增 ingestion_runs 追蹤與聯賽種子資料"
```

---

### Task 12: FixtureSync service

**Files:**
- Create: `app/services/fixtures.py`
- Test: `tests/test_fixture_sync.py`

**Interfaces:**
- Consumes: `app.config.Settings`, `app.db.models.{League, Match, Season, Team}`, `app.providers.base.{FixtureRecord, Provider}`, `app.services.alias.{TeamMatcher, normalize_team_name}`, `app.services.runs.track_run`.
- Produces: `app.services.fixtures.season_label_for(kickoff: datetime) -> str`, `season_bounds(label: str) -> tuple[date, date]`, and `FixtureSync(session_factory, provider, settings)` with `async def run(self, date_from: date, date_to: date) -> int` and `async def upsert(self, fixtures: list[FixtureRecord]) -> int`.

- [ ] **Step 1: Write the failing test `tests/test_fixture_sync.py`**

```python
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.config import Settings
from app.data.leagues import seed_leagues
from app.db.base import Base
from app.db.models import League, Match, Season, Team
from app.db.session import Database
from app.providers.base import FixtureRecord
from app.services.fixtures import FixtureSync, season_bounds, season_label_for


class _FakeProvider:
    name = "fake"

    def __init__(self, fixtures: list[FixtureRecord]) -> None:
        self._fixtures = fixtures

    async def fetch_leagues(self):
        return []

    async def fetch_fixtures(self, date_from, date_to):
        return self._fixtures

    async def fetch_odds(self, fixtures):
        return []

    async def fetch_results(self, date_from, date_to):
        return []


def _fixture(**overrides) -> FixtureRecord:
    base = dict(
        source="fake",
        league_name="English Premier League",
        hkjc_tourn_id="TOURN-EPL",
        hkjc_match_id="M-1001",
        kickoff_time=datetime(2026, 10, 12, 11, 30, tzinfo=UTC),
        status="scheduled",
        home_team_name_en="Manchester United",
        home_team_name_ch="曼聯",
        home_team_hkjc_id="T-1",
        away_team_name_en="Liverpool",
        away_team_name_ch="利物浦",
        away_team_hkjc_id="T-2",
        venue="Old Trafford",
    )
    base.update(overrides)
    return FixtureRecord(**base)


async def _db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db.session_factory() as session:
        await seed_leagues(session)
        await session.commit()
    return db


def test_season_label_and_bounds():
    assert season_label_for(datetime(2026, 10, 12, tzinfo=UTC)) == "2026/27"
    assert season_label_for(datetime(2026, 3, 1, tzinfo=UTC)) == "2025/26"
    assert season_bounds("2026/27") == (date(2026, 7, 1), date(2027, 6, 30))


async def test_fixture_sync_creates_match_teams_and_season(tmp_path):
    db = await _db(tmp_path)
    try:
        provider = _FakeProvider([_fixture()])
        sync = FixtureSync(db.session_factory, provider, Settings(_env_file=None))
        assert await sync.run(date(2026, 10, 12), date(2026, 10, 15)) == 1
        async with db.session_factory() as session:
            match = (await session.execute(select(Match))).scalar_one()
            assert match.hkjc_match_id == "M-1001"
            assert match.status == "scheduled"
            assert match.venue == "Old Trafford"
            season = (await session.execute(select(Season))).scalar_one()
            assert season.label == "2026/27"
            teams = (await session.execute(select(Team))).scalars().all()
            assert {team.hkjc_team_id for team in teams} == {"T-1", "T-2"}
            league = (await session.execute(select(League).where(League.code == "EPL"))).scalar_one()
            assert league.hkjc_tourn_id == "TOURN-EPL"
    finally:
        await db.dispose()


async def test_fixture_sync_is_idempotent(tmp_path):
    db = await _db(tmp_path)
    try:
        provider = _FakeProvider([_fixture()])
        sync = FixtureSync(db.session_factory, provider, Settings(_env_file=None))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        async with db.session_factory() as session:
            matches = (await session.execute(select(Match))).scalars().all()
            assert len(matches) == 1
    finally:
        await db.dispose()


async def test_fixture_sync_skips_non_whitelisted_league(tmp_path):
    db = await _db(tmp_path)
    try:
        provider = _FakeProvider(
            [_fixture(hkjc_match_id="M-2001", league_name="Friendly Cup", hkjc_tourn_id="TOURN-FRIENDLY")]
        )
        sync = FixtureSync(db.session_factory, provider, Settings(_env_file=None))
        assert await sync.run(date(2026, 10, 12), date(2026, 10, 15)) == 0
        async with db.session_factory() as session:
            assert (await session.execute(select(Match))).scalars().all() == []
    finally:
        await db.dispose()


async def test_fixture_sync_updates_existing_match(tmp_path):
    db = await _db(tmp_path)
    try:
        sync = FixtureSync(db.session_factory, _FakeProvider([_fixture()]), Settings(_env_file=None))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        updated = _fixture(status="live", venue="Anfield")
        sync2 = FixtureSync(db.session_factory, _FakeProvider([updated]), Settings(_env_file=None))
        await sync2.run(date(2026, 10, 12), date(2026, 10, 15))
        async with db.session_factory() as session:
            match = (await session.execute(select(Match))).scalar_one()
            assert match.status == "live"
            assert match.venue == "Anfield"
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_fixture_sync.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.services.fixtures'`.

- [ ] **Step 3: Implement `app/services/fixtures.py`**

```python
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import League, Match, Season, Team
from app.providers.base import FixtureRecord, Provider
from app.services.alias import TeamMatcher, normalize_team_name
from app.services.runs import track_run


def season_label_for(kickoff: datetime) -> str:
    year = kickoff.year if kickoff.month >= 7 else kickoff.year - 1
    return f"{year}/{year + 1}"


def season_bounds(label: str) -> tuple[date, date]:
    start_year = int(label.split("/")[0])
    return date(start_year, 7, 1), date(start_year + 1, 6, 30)


class FixtureSync:
    """Upserts leagues, seasons, teams, and matches from provider fixtures."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: Provider,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._settings = settings

    async def run(self, date_from: date, date_to: date) -> int:
        fixtures = await self._provider.fetch_fixtures(date_from, date_to)
        return await self.upsert(fixtures)

    async def upsert(self, fixtures: list[FixtureRecord]) -> int:
        return await track_run(
            self._session_factory,
            "sync_fixtures",
            lambda session: self._upsert_all(session, fixtures),
        )

    async def _upsert_all(self, session: AsyncSession, fixtures: list[FixtureRecord]) -> int:
        count = 0
        for fixture in fixtures:
            league = await self._resolve_league(session, fixture)
            if league is None or league.code not in self._settings.league_whitelist:
                continue
            season = await self._resolve_season(session, league, fixture.kickoff_time)
            home = await self._resolve_team(
                session,
                fixture.home_team_name_en,
                fixture.home_team_name_ch,
                fixture.home_team_hkjc_id,
            )
            away = await self._resolve_team(
                session,
                fixture.away_team_name_en,
                fixture.away_team_name_ch,
                fixture.away_team_hkjc_id,
            )
            await self._upsert_match(session, fixture, league, season, home, away)
            count += 1
        return count

    async def _resolve_league(self, session: AsyncSession, fixture: FixtureRecord) -> League | None:
        if fixture.hkjc_tourn_id:
            league = (
                await session.execute(
                    select(League).where(League.hkjc_tourn_id == fixture.hkjc_tourn_id)
                )
            ).scalar_one_or_none()
            if league is not None:
                return league
        target = normalize_team_name(fixture.league_name)
        leagues = (await session.execute(select(League))).scalars().all()
        for league in leagues:
            names = [league.name_en, league.name_ch]
            if any(name and normalize_team_name(name) == target for name in names):
                if fixture.hkjc_tourn_id and league.hkjc_tourn_id is None:
                    league.hkjc_tourn_id = fixture.hkjc_tourn_id
                return league
        return None

    async def _resolve_season(
        self, session: AsyncSession, league: League, kickoff: datetime
    ) -> Season:
        label = season_label_for(kickoff)
        season = (
            await session.execute(
                select(Season).where(Season.league_id == league.id, Season.label == label)
            )
        ).scalar_one_or_none()
        if season is None:
            start, end = season_bounds(label)
            season = Season(league_id=league.id, label=label, start_date=start, end_date=end)
            session.add(season)
            await session.flush()
        return season

    async def _resolve_team(
        self,
        session: AsyncSession,
        name_en: str,
        name_ch: str | None,
        hkjc_team_id: str | None,
    ) -> Team:
        if hkjc_team_id:
            team = (
                await session.execute(select(Team).where(Team.hkjc_team_id == hkjc_team_id))
            ).scalar_one_or_none()
            if team is not None:
                return team
        teams = (await session.execute(select(Team))).scalars().all()
        matcher = TeamMatcher(teams)
        for candidate in (name_en, name_ch):
            if not candidate:
                continue
            matched = matcher.match(candidate)
            if matched is not None:
                if hkjc_team_id and matched.hkjc_team_id is None:
                    matched.hkjc_team_id = hkjc_team_id
                return matched
        team = Team(
            name_en=name_en,
            name_ch=name_ch,
            hkjc_team_id=hkjc_team_id,
            aliases=[],
            external_ids={},
        )
        session.add(team)
        await session.flush()
        return team

    async def _upsert_match(
        self,
        session: AsyncSession,
        fixture: FixtureRecord,
        league: League,
        season: Season,
        home: Team,
        away: Team,
    ) -> None:
        match: Match | None = None
        if fixture.hkjc_match_id:
            match = (
                await session.execute(
                    select(Match).where(Match.hkjc_match_id == fixture.hkjc_match_id)
                )
            ).scalar_one_or_none()
        if match is None:
            session.add(
                Match(
                    season_id=season.id,
                    league_id=league.id,
                    hkjc_match_id=fixture.hkjc_match_id,
                    kickoff_time=fixture.kickoff_time,
                    status=fixture.status,
                    home_team_id=home.id,
                    away_team_id=away.id,
                    venue=fixture.venue,
                    round=fixture.round,
                )
            )
            await session.flush()
            return
        match.season_id = season.id
        match.league_id = league.id
        match.kickoff_time = fixture.kickoff_time
        match.status = fixture.status
        match.home_team_id = home.id
        match.away_team_id = away.id
        match.venue = fixture.venue
        match.round = fixture.round
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_fixture_sync.py -v`

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/services/fixtures.py tests/test_fixture_sync.py
git commit -m "feat: 實作賽程同步服務 FixtureSync"
```

---

### Task 13: OddsSync service and odds retention

**Files:**
- Create: `app/services/odds.py`
- Test: `tests/test_odds_sync.py`

**Interfaces:**
- Consumes: `app.config.Settings`, `app.db.models.{Match, OddsSnapshot}`, `app.providers.base.{OddsRecord, Provider}`, `app.services.fixtures.FixtureSync`, `app.services.runs.track_run`.
- Produces: `app.services.odds.snapshot_bucket(captured_at: datetime, interval_seconds: int) -> datetime`; `OddsSync(session_factory, provider, settings)` with `async def run(self, date_from: date, date_to: date) -> int`; `async def prune_odds_snapshots(session_factory, retention_days: int, now: datetime | None = None) -> int`.

- [ ] **Step 1: Write the failing test `tests/test_odds_sync.py`**

```python
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.config import Settings
from app.data.leagues import seed_leagues
from app.db.base import Base
from app.db.models import Match, OddsSnapshot
from app.db.session import Database
from app.providers.base import FixtureRecord, OddsRecord
from app.services.odds import OddsSync, prune_odds_snapshots, snapshot_bucket


class _FakeProvider:
    name = "fake"

    def __init__(self, fixtures: list[FixtureRecord], odds: list[OddsRecord]) -> None:
        self._fixtures = fixtures
        self._odds = odds

    async def fetch_leagues(self):
        return []

    async def fetch_fixtures(self, date_from, date_to):
        return self._fixtures

    async def fetch_odds(self, fixtures):
        return self._odds

    async def fetch_results(self, date_from, date_to):
        return []


def _fixture() -> FixtureRecord:
    return FixtureRecord(
        source="fake",
        league_name="English Premier League",
        hkjc_tourn_id="TOURN-EPL",
        hkjc_match_id="M-1001",
        kickoff_time=datetime(2026, 10, 12, 11, 30, tzinfo=UTC),
        home_team_name_en="Manchester United",
        home_team_name_ch="曼聯",
        home_team_hkjc_id="T-1",
        away_team_name_en="Liverpool",
        away_team_name_ch="利物浦",
        away_team_hkjc_id="T-2",
    )


def _odds(captured_at: datetime) -> list[OddsRecord]:
    return [
        OddsRecord(match_hkjc_id="M-1001", odds_type="HAD", inplay=False, captured_at=captured_at, payload={"v": 1}),
        OddsRecord(match_hkjc_id="M-1001", odds_type="HDC", inplay=False, captured_at=captured_at, payload={"v": 1}),
    ]


async def _db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db.session_factory() as session:
        await seed_leagues(session)
        await session.commit()
    return db


def test_snapshot_bucket_floors_to_interval():
    captured = datetime(2026, 10, 12, 12, 7, 30, tzinfo=UTC)
    assert snapshot_bucket(captured, 600) == datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    assert snapshot_bucket(captured, 900) == datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


async def test_odds_sync_inserts_snapshots(tmp_path):
    db = await _db(tmp_path)
    try:
        captured = datetime(2026, 10, 12, 12, 7, 30, tzinfo=UTC)
        provider = _FakeProvider([_fixture()], _odds(captured))
        sync = OddsSync(db.session_factory, provider, Settings(_env_file=None))
        assert await sync.run(date(2026, 10, 12), date(2026, 10, 15)) == 2
        async with db.session_factory() as session:
            snapshots = (await session.execute(select(OddsSnapshot))).scalars().all()
            assert len(snapshots) == 2
            assert {s.odds_type for s in snapshots} == {"HAD", "HDC"}
            assert all(s.snapshot_bucket == datetime(2026, 10, 12, 12, 0, tzinfo=UTC) for s in snapshots)
    finally:
        await db.dispose()


async def test_odds_sync_is_idempotent_within_bucket(tmp_path):
    db = await _db(tmp_path)
    try:
        captured = datetime(2026, 10, 12, 12, 7, 30, tzinfo=UTC)
        provider = _FakeProvider([_fixture()], _odds(captured))
        sync = OddsSync(db.session_factory, provider, Settings(_env_file=None))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        async with db.session_factory() as session:
            assert len((await session.execute(select(OddsSnapshot))).scalars().all()) == 2
    finally:
        await db.dispose()


async def test_odds_sync_new_bucket_adds_rows(tmp_path):
    db = await _db(tmp_path)
    try:
        first = datetime(2026, 10, 12, 12, 7, 30, tzinfo=UTC)
        second = datetime(2026, 10, 12, 12, 17, 30, tzinfo=UTC)
        sync = OddsSync(db.session_factory, _FakeProvider([_fixture()], _odds(first)), Settings(_env_file=None))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        sync2 = OddsSync(db.session_factory, _FakeProvider([_fixture()], _odds(second)), Settings(_env_file=None))
        await sync2.run(date(2026, 10, 12), date(2026, 10, 15))
        async with db.session_factory() as session:
            assert len((await session.execute(select(OddsSnapshot))).scalars().all()) == 4
    finally:
        await db.dispose()


async def test_prune_odds_snapshots_removes_old_rows(tmp_path):
    db = await _db(tmp_path)
    try:
        captured = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
        provider = _FakeProvider([_fixture()], _odds(captured))
        sync = OddsSync(db.session_factory, provider, Settings(_env_file=None))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        deleted = await prune_odds_snapshots(
            db.session_factory, retention_days=30, now=captured + timedelta(days=60)
        )
        assert deleted == 2
        async with db.session_factory() as session:
            assert (await session.execute(select(OddsSnapshot))).scalars().all() == []
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_odds_sync.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.services.odds'`.

- [ ] **Step 3: Implement `app/services/odds.py`**

```python
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Match, OddsSnapshot
from app.providers.base import OddsRecord, Provider
from app.services.fixtures import FixtureSync
from app.services.runs import track_run


def snapshot_bucket(captured_at: datetime, interval_seconds: int) -> datetime:
    """Floor a timestamp to the sync interval so re-runs within a window are idempotent."""
    epoch = int(captured_at.timestamp())
    bucket = epoch - (epoch % interval_seconds)
    return datetime.fromtimestamp(bucket, tz=UTC)


class OddsSync:
    """Syncs fixtures, then stores one odds snapshot per (match, odds_type, inplay, bucket)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: Provider,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._settings = settings
        self._fixture_sync = FixtureSync(session_factory, provider, settings)

    async def run(self, date_from: date, date_to: date) -> int:
        fixtures = await self._provider.fetch_fixtures(date_from, date_to)
        await self._fixture_sync.upsert(fixtures)
        records = await self._provider.fetch_odds(fixtures)
        return await track_run(
            self._session_factory,
            "sync_odds",
            lambda session: self._upsert_snapshots(session, records),
        )

    async def _upsert_snapshots(self, session: AsyncSession, records: list[OddsRecord]) -> int:
        count = 0
        for record in records:
            match = (
                await session.execute(
                    select(Match).where(Match.hkjc_match_id == record.match_hkjc_id)
                )
            ).scalar_one_or_none()
            if match is None:
                continue
            bucket = snapshot_bucket(record.captured_at, self._settings.sync_odds_interval)
            existing = (
                await session.execute(
                    select(OddsSnapshot).where(
                        OddsSnapshot.match_id == match.id,
                        OddsSnapshot.odds_type == record.odds_type,
                        OddsSnapshot.inplay == record.inplay,
                        OddsSnapshot.snapshot_bucket == bucket,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    OddsSnapshot(
                        match_id=match.id,
                        captured_at=record.captured_at,
                        snapshot_bucket=bucket,
                        source=self._provider.name,
                        inplay=record.inplay,
                        odds_type=record.odds_type,
                        payload=record.payload,
                    )
                )
            else:
                existing.captured_at = record.captured_at
                existing.payload = record.payload
            count += 1
        await session.flush()
        return count


async def prune_odds_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
    retention_days: int,
    now: datetime | None = None,
) -> int:
    """Delete odds snapshots older than the retention window. Returns rows deleted."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    async with session_factory() as session:
        result = await session.execute(
            delete(OddsSnapshot).where(OddsSnapshot.captured_at < cutoff)
        )
        await session.commit()
        return result.rowcount or 0
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_odds_sync.py -v`

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/services/odds.py tests/test_odds_sync.py
git commit -m "feat: 實作賠率快照同步與保留清理"
```

---

### Task 14: ResultReconciler (HKJC-first → football-data fallback → 48h flag)

**Files:**
- Create: `app/services/results.py`
- Test: `tests/test_result_reconciler.py`

**Interfaces:**
- Consumes: `app.config.Settings`, `app.db.models.{Match, Result, Team}`, `app.providers.base.{Provider, ResultRecord}`, `app.services.alias.TeamMatcher`, `app.services.runs.{flag_manual_review, track_run}`.
- Produces: `app.services.results.ResultReconciler(session_factory, hkjc_provider, fallback_provider, settings)` with `async def run(self, now: datetime | None = None) -> int`; constants `HKJC_LOOKBACK_DAYS`, `FALLBACK_AFTER_HOURS`, `MANUAL_REVIEW_AFTER_HOURS`, `FALLBACK_LOOKBACK_DAYS`.

- [ ] **Step 1: Write the failing test `tests/test_result_reconciler.py`**

```python
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.config import Settings
from app.data.leagues import seed_leagues
from app.db.base import Base
from app.db.models import IngestionRun, League, Match, Result, Season, Team
from app.db.session import Database
from app.providers.base import ResultRecord
from app.services.results import ResultReconciler


class _FakeProvider:
    name = "fake"

    def __init__(self, results: list[ResultRecord]) -> None:
        self._results = results

    async def fetch_leagues(self):
        return []

    async def fetch_fixtures(self, date_from, date_to):
        return []

    async def fetch_odds(self, fixtures):
        return []

    async def fetch_results(self, date_from, date_to):
        return self._results


async def _db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return db


async def _seed_match(db: Database, kickoff: datetime) -> int:
    async with db.session_factory() as session:
        await seed_leagues(session)
        league = (await session.execute(select(League).where(League.code == "EPL"))).scalar_one()
        season = Season(
            league_id=league.id, label="2026/27", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        home = Team(name_en="Manchester United", name_ch="曼聯", hkjc_team_id="T-1", aliases=["Man Utd"])
        away = Team(name_en="Liverpool", name_ch="利物浦", hkjc_team_id="T-2", aliases=[])
        session.add_all([season, home, away])
        await session.flush()
        match = Match(
            season_id=season.id,
            league_id=league.id,
            hkjc_match_id="M-1001",
            kickoff_time=kickoff,
            status="finished",
            home_team_id=home.id,
            away_team_id=away.id,
        )
        session.add(match)
        await session.commit()
        return match.id


async def test_hkjc_result_is_upserted(tmp_path):
    db = await _db(tmp_path)
    try:
        now = datetime(2026, 10, 12, 22, 0, tzinfo=UTC)
        await _seed_match(db, datetime(2026, 10, 12, 11, 30, tzinfo=UTC))
        hkjc = _FakeProvider(
            [
                ResultRecord(
                    match_hkjc_id="M-1001",
                    home_score=0,
                    away_score=0,
                    ttl_corner=9,
                    source="hkjc",
                    confirmed=True,
                    payout_confirmed=True,
                    raw={"homeResult": "0"},
                )
            ]
        )
        reconciler = ResultReconciler(db.session_factory, hkjc, _FakeProvider([]), Settings(_env_file=None))
        assert await reconciler.run(now=now) == 1
        async with db.session_factory() as session:
            result = (await session.execute(select(Result))).scalar_one()
            assert result.source == "hkjc"
            assert result.confirmed is True
            assert result.ttl_corner == 9
            assert result.payout_confirmed is True
            assert result.confirmed_at is not None
    finally:
        await db.dispose()


async def test_fallback_result_is_upserted_when_hkjc_misses(tmp_path):
    db = await _db(tmp_path)
    try:
        now = datetime(2026, 10, 12, 22, 0, tzinfo=UTC)
        await _seed_match(db, datetime(2026, 10, 12, 11, 30, tzinfo=UTC))
        fallback = _FakeProvider(
            [
                ResultRecord(
                    match_date=date(2026, 10, 12),
                    home_team_name="Man Utd",
                    away_team_name="Liverpool",
                    home_score=2,
                    away_score=1,
                    source="football_data",
                )
            ]
        )
        reconciler = ResultReconciler(db.session_factory, _FakeProvider([]), fallback, Settings(_env_file=None))
        assert await reconciler.run(now=now) == 1
        async with db.session_factory() as session:
            result = (await session.execute(select(Result))).scalar_one()
            assert result.source == "football_data"
            assert result.confirmed is False
            assert result.ttl_corner is None
            assert result.home_score == 2
    finally:
        await db.dispose()


async def test_unresolved_after_48h_is_flagged(tmp_path):
    db = await _db(tmp_path)
    try:
        now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
        match_id = await _seed_match(db, datetime(2026, 10, 12, 11, 30, tzinfo=UTC))
        reconciler = ResultReconciler(
            db.session_factory, _FakeProvider([]), _FakeProvider([]), Settings(_env_file=None)
        )
        await reconciler.run(now=now)
        async with db.session_factory() as session:
            runs = (
                await session.execute(select(IngestionRun).where(IngestionRun.job == "manual_review"))
            ).scalars().all()
            assert len(runs) == 1
            assert runs[0].status == "flagged"
            assert str(match_id) in (runs[0].error or "")
    finally:
        await db.dispose()


async def test_hkjc_overwrites_football_data_row(tmp_path):
    db = await _db(tmp_path)
    try:
        now = datetime(2026, 10, 12, 22, 0, tzinfo=UTC)
        match_id = await _seed_match(db, datetime(2026, 10, 12, 11, 30, tzinfo=UTC))
        async with db.session_factory() as session:
            session.add(
                Result(
                    match_id=match_id,
                    home_score=9,
                    away_score=9,
                    source="football_data",
                    confirmed=False,
                    payout_confirmed=False,
                    raw={},
                )
            )
            await session.commit()
        hkjc = _FakeProvider(
            [
                ResultRecord(
                    match_hkjc_id="M-1001",
                    home_score=0,
                    away_score=0,
                    ttl_corner=9,
                    source="hkjc",
                    confirmed=True,
                    payout_confirmed=True,
                )
            ]
        )
        reconciler = ResultReconciler(db.session_factory, hkjc, _FakeProvider([]), Settings(_env_file=None))
        await reconciler.run(now=now)
        async with db.session_factory() as session:
            result = (await session.execute(select(Result))).scalar_one()
            assert result.source == "hkjc"
            assert result.home_score == 0
            assert result.confirmed is True
    finally:
        await db.dispose()


async def test_fallback_upsert_skips_existing_hkjc_row(tmp_path):
    db = await _db(tmp_path)
    try:
        match_id = await _seed_match(db, datetime(2026, 10, 12, 11, 30, tzinfo=UTC))
        async with db.session_factory() as session:
            session.add(
                Result(
                    match_id=match_id,
                    home_score=0,
                    away_score=0,
                    ttl_corner=9,
                    source="hkjc",
                    confirmed=True,
                    payout_confirmed=True,
                    raw={},
                )
            )
            await session.commit()
        reconciler = ResultReconciler(
            db.session_factory, _FakeProvider([]), _FakeProvider([]), Settings(_env_file=None)
        )
        record = ResultRecord(
            match_date=date(2026, 10, 12),
            home_team_name="Man Utd",
            away_team_name="Liverpool",
            home_score=5,
            away_score=5,
            source="football_data",
        )
        async with db.session_factory() as session:
            count = await reconciler._upsert_fallback(session, [record], [match_id])
            await session.commit()
        assert count == 0
        async with db.session_factory() as session:
            result = (await session.execute(select(Result))).scalar_one()
            assert result.source == "hkjc"
            assert result.home_score == 0
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_result_reconciler.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.services.results'`.

- [ ] **Step 3: Implement `app/services/results.py`**

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Match, Result, Team
from app.providers.base import Provider, ResultRecord
from app.services.alias import TeamMatcher
from app.services.runs import flag_manual_review, track_run

HKJC_LOOKBACK_DAYS = 2
FALLBACK_AFTER_HOURS = 4
MANUAL_REVIEW_AFTER_HOURS = 48
FALLBACK_LOOKBACK_DAYS = 7


class ResultReconciler:
    """Settles finished matches: HKJC first, football-data fallback, then a 48h manual-review flag."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hkjc_provider: Provider,
        fallback_provider: Provider,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._hkjc = hkjc_provider
        self._fallback = fallback_provider
        self._settings = settings

    async def run(self, now: datetime | None = None) -> int:
        moment = now or datetime.now(UTC)
        hkjc_count = await self._reconcile_hkjc(moment)
        fallback_count = await self._reconcile_fallback(moment)
        await self._flag_unresolved(moment)
        return hkjc_count + fallback_count

    async def _reconcile_hkjc(self, now: datetime) -> int:
        date_from = (now - timedelta(days=HKJC_LOOKBACK_DAYS)).date()
        records = await self._hkjc.fetch_results(date_from, now.date())
        return await track_run(
            self._session_factory,
            "settle_results_hkjc",
            lambda session: self._upsert_hkjc(session, records),
        )

    async def _upsert_hkjc(self, session: AsyncSession, records: list[ResultRecord]) -> int:
        count = 0
        for record in records:
            if record.match_hkjc_id is None:
                continue
            match = (
                await session.execute(
                    select(Match).where(Match.hkjc_match_id == record.match_hkjc_id)
                )
            ).scalar_one_or_none()
            if match is None:
                continue
            await self._upsert_result(
                session,
                match,
                record,
                source="hkjc",
                confirmed=True,
                ttl_corner=record.ttl_corner,
            )
            count += 1
        return count

    async def _reconcile_fallback(self, now: datetime) -> int:
        cutoff = now - timedelta(hours=FALLBACK_AFTER_HOURS)
        async with self._session_factory() as session:
            candidates = (
                await session.execute(
                    select(Match.id)
                    .outerjoin(Result, Result.match_id == Match.id)
                    .where(Result.id.is_(None), Match.kickoff_time < cutoff)
                )
            ).scalars().all()
        if not candidates:
            return 0
        date_from = (now - timedelta(days=FALLBACK_LOOKBACK_DAYS)).date()
        records = await self._fallback.fetch_results(date_from, now.date())
        return await track_run(
            self._session_factory,
            "settle_results_fallback",
            lambda session: self._upsert_fallback(session, records, list(candidates)),
        )

    async def _upsert_fallback(
        self, session: AsyncSession, records: list[ResultRecord], candidate_ids: list[int]
    ) -> int:
        teams = (await session.execute(select(Team))).scalars().all()
        matcher = TeamMatcher(teams)
        candidates = (
            await session.execute(select(Match).where(Match.id.in_(candidate_ids)))
        ).scalars().all()
        count = 0
        for record in records:
            if record.match_date is None or record.home_team_name is None or record.away_team_name is None:
                continue
            home = matcher.match(record.home_team_name)
            away = matcher.match(record.away_team_name)
            if home is None or away is None:
                continue
            for match in candidates:
                if match.home_team_id != home.id or match.away_team_id != away.id:
                    continue
                if abs((match.kickoff_time.date() - record.match_date).days) > 1:
                    continue
                existing = (
                    await session.execute(select(Result).where(Result.match_id == match.id))
                ).scalar_one_or_none()
                if existing is not None and existing.source == "hkjc":
                    continue
                await self._upsert_result(
                    session,
                    match,
                    record,
                    source="football_data",
                    confirmed=False,
                    ttl_corner=None,
                )
                count += 1
                break
        return count

    async def _upsert_result(
        self,
        session: AsyncSession,
        match: Match,
        record: ResultRecord,
        source: str,
        confirmed: bool,
        ttl_corner: int | None,
    ) -> None:
        existing = (
            await session.execute(select(Result).where(Result.match_id == match.id))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                Result(
                    match_id=match.id,
                    home_score=record.home_score,
                    away_score=record.away_score,
                    ttl_corner=ttl_corner,
                    source=source,
                    confirmed=confirmed,
                    payout_confirmed=record.payout_confirmed,
                    confirmed_at=datetime.now(UTC) if confirmed else None,
                    raw=record.raw,
                )
            )
        else:
            existing.home_score = record.home_score
            existing.away_score = record.away_score
            existing.ttl_corner = ttl_corner
            existing.source = source
            existing.confirmed = confirmed
            existing.payout_confirmed = record.payout_confirmed
            if confirmed:
                existing.confirmed_at = datetime.now(UTC)
            existing.raw = record.raw
        await session.flush()

    async def _flag_unresolved(self, now: datetime) -> None:
        cutoff = now - timedelta(hours=MANUAL_REVIEW_AFTER_HOURS)
        async with self._session_factory() as session:
            unresolved = (
                await session.execute(
                    select(Match.id)
                    .outerjoin(Result, Result.match_id == Match.id)
                    .where(Result.id.is_(None), Match.kickoff_time < cutoff)
                )
            ).scalars().all()
        await flag_manual_review(self._session_factory, "manual_review", list(unresolved))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_result_reconciler.py -v`

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/services/results.py tests/test_result_reconciler.py
git commit -m "feat: 實作賽果對帳服務（HKJC 優先、外部回退、48 小時人工複核）"
```

---

### Task 15: FastAPI read API

**Files:**
- Create: `app/api/__init__.py`
- Create: `app/api/schemas.py`
- Create: `app/api/routes.py`
- Create: `app/api/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `app.config.{Settings, get_settings}`, `app.db.session.Database`, `app.db.models.*`, `app.providers.hkjc.client.HkjcGraphQLClient`, `app.providers.hkjc.provider.HkjcProvider`, `app.providers.football_data.provider.FootballDataProvider`.
- Produces: `app.api.main.create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI`; endpoints `GET /health`, `GET /matches`, `GET /matches/{match_id}/odds`, `GET /results`; response models `MatchOut`, `OddsOut`, `ResultOut`, `TeamOut`.

- [ ] **Step 1: Write the failing test `tests/test_api.py`**

```python
from datetime import UTC, date, datetime

import httpx
from sqlalchemy import select

from app.api.main import create_app
from app.config import Settings
from app.data.leagues import seed_leagues
from app.db.base import Base
from app.db.models import League, Match, OddsSnapshot, Result, Season, Team
from app.db.session import Database


async def _db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return db


async def _seed(db: Database) -> int:
    async with db.session_factory() as session:
        await seed_leagues(session)
        league = (await session.execute(select(League).where(League.code == "EPL"))).scalar_one()
        season = Season(
            league_id=league.id, label="2026/27", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        home = Team(name_en="Manchester United", name_ch="曼聯", hkjc_team_id="T-1", aliases=[])
        away = Team(name_en="Liverpool", name_ch="利物浦", hkjc_team_id="T-2", aliases=[])
        session.add_all([season, home, away])
        await session.flush()
        match = Match(
            season_id=season.id,
            league_id=league.id,
            hkjc_match_id="M-1001",
            kickoff_time=datetime(2026, 10, 12, 11, 30, tzinfo=UTC),
            status="finished",
            home_team_id=home.id,
            away_team_id=away.id,
            venue="Old Trafford",
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
            OddsSnapshot(
                match_id=match.id,
                captured_at=datetime(2026, 10, 12, 9, 10, tzinfo=UTC),
                snapshot_bucket=datetime(2026, 10, 12, 9, 10, tzinfo=UTC),
                source="hkjc",
                inplay=False,
                odds_type="HAD",
                payload={"home": 2.2},
            )
        )
        session.add(
            Result(
                match_id=match.id,
                home_score=0,
                away_score=0,
                ttl_corner=9,
                source="hkjc",
                confirmed=True,
                payout_confirmed=True,
                raw={},
            )
        )
        await session.commit()
        return match.id


async def _client(db: Database) -> httpx.AsyncClient:
    app = create_app(settings=Settings(_env_file=None, enable_scheduler=False), db=db)
    app.state.db = db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health(tmp_path):
    db = await _db(tmp_path)
    try:
        async with await _client(db) as client:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
    finally:
        await db.dispose()


async def test_list_matches(tmp_path):
    db = await _db(tmp_path)
    try:
        await _seed(db)
        async with await _client(db) as client:
            response = await client.get("/matches")
            assert response.status_code == 200
            body = response.json()
            assert len(body) == 1
            assert body[0]["league_code"] == "EPL"
            assert body[0]["home_team"]["name_ch"] == "曼聯"
            assert body[0]["status"] == "finished"
    finally:
        await db.dispose()


async def test_list_matches_filters_by_league(tmp_path):
    db = await _db(tmp_path)
    try:
        await _seed(db)
        async with await _client(db) as client:
            response = await client.get("/matches", params={"league": "LALIGA"})
            assert response.json() == []
    finally:
        await db.dispose()


async def test_match_odds_returns_latest_per_type(tmp_path):
    db = await _db(tmp_path)
    try:
        match_id = await _seed(db)
        async with await _client(db) as client:
            response = await client.get(f"/matches/{match_id}/odds")
            body = response.json()
            assert len(body) == 1
            assert body[0]["odds_type"] == "HAD"
            assert body[0]["payload"] == {"home": 2.2}
    finally:
        await db.dispose()


async def test_match_odds_history_returns_all(tmp_path):
    db = await _db(tmp_path)
    try:
        match_id = await _seed(db)
        async with await _client(db) as client:
            response = await client.get(f"/matches/{match_id}/odds", params={"history": "true"})
            assert len(response.json()) == 2
    finally:
        await db.dispose()


async def test_match_odds_404(tmp_path):
    db = await _db(tmp_path)
    try:
        async with await _client(db) as client:
            response = await client.get("/matches/999/odds")
            assert response.status_code == 404
    finally:
        await db.dispose()


async def test_list_results(tmp_path):
    db = await _db(tmp_path)
    try:
        await _seed(db)
        async with await _client(db) as client:
            response = await client.get("/results")
            body = response.json()
            assert len(body) == 1
            assert body[0]["home_score"] == 0
            assert body[0]["source"] == "hkjc"
            assert body[0]["ttl_corner"] == 9
            assert body[0]["league_code"] == "EPL"
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_api.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.api'`.

- [ ] **Step 3: Implement `app/api/schemas.py`, `app/api/routes.py`, `app/api/main.py`, and `app/api/__init__.py`**

`app/api/__init__.py`:

```python
"""FastAPI read API for later subsystems (ML engine, ledger, UI)."""
```

`app/api/schemas.py`:

```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name_en: str
    name_ch: str | None = None


class MatchOut(BaseModel):
    id: int
    league_code: str
    league_name: str
    kickoff_time: datetime
    status: str
    home_team: TeamOut
    away_team: TeamOut
    venue: str | None = None
    round: str | None = None
    hkjc_match_id: str | None = None


class OddsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    odds_type: str
    inplay: bool
    source: str
    captured_at: datetime
    snapshot_bucket: datetime
    payload: dict[str, Any]


class ResultOut(BaseModel):
    match_id: int
    home_score: int
    away_score: int
    ttl_corner: int | None = None
    source: str
    confirmed: bool
    payout_confirmed: bool
    confirmed_at: datetime | None = None
    kickoff_time: datetime
    league_code: str
    home_team: TeamOut
    away_team: TeamOut
```

`app/api/routes.py`:

```python
from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.schemas import MatchOut, OddsOut, ResultOut, TeamOut
from app.db.models import League, Match, OddsSnapshot, Result, Team

router = APIRouter()


async def get_session(request: Request):
    async with request.app.state.db.session_factory() as session:
        yield session


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/matches", response_model=list[MatchOut])
async def list_matches(
    session: AsyncSession = Depends(get_session),
    date_from: date | None = None,
    date_to: date | None = None,
    league: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[MatchOut]:
    home = aliased(Team)
    away = aliased(Team)
    stmt = (
        select(Match, League, home, away)
        .join(League, League.id == Match.league_id)
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .order_by(Match.kickoff_time)
        .limit(limit)
        .offset(offset)
    )
    if date_from is not None:
        stmt = stmt.where(Match.kickoff_time >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to is not None:
        stmt = stmt.where(Match.kickoff_time <= datetime.combine(date_to, time.max, tzinfo=UTC))
    if league is not None:
        stmt = stmt.where(League.code == league)
    if status is not None:
        stmt = stmt.where(Match.status == status)
    rows = (await session.execute(stmt)).all()
    return [
        MatchOut(
            id=match.id,
            league_code=lg.code,
            league_name=lg.name_en,
            kickoff_time=match.kickoff_time,
            status=match.status,
            home_team=TeamOut.model_validate(home_team),
            away_team=TeamOut.model_validate(away_team),
            venue=match.venue,
            round=match.round,
            hkjc_match_id=match.hkjc_match_id,
        )
        for match, lg, home_team, away_team in rows
    ]


@router.get("/matches/{match_id}/odds", response_model=list[OddsOut])
async def match_odds(
    match_id: int,
    session: AsyncSession = Depends(get_session),
    odds_type: str | None = None,
    inplay: bool | None = None,
    history: bool = False,
) -> list[OddsOut]:
    match = await session.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="match not found")
    stmt = select(OddsSnapshot).where(OddsSnapshot.match_id == match_id)
    if odds_type is not None:
        stmt = stmt.where(OddsSnapshot.odds_type == odds_type)
    if inplay is not None:
        stmt = stmt.where(OddsSnapshot.inplay == inplay)
    stmt = stmt.order_by(OddsSnapshot.captured_at.desc())
    snapshots = (await session.execute(stmt)).scalars().all()
    if history:
        return [OddsOut.model_validate(snapshot) for snapshot in snapshots]
    latest: dict[tuple[str, bool], OddsSnapshot] = {}
    for snapshot in snapshots:
        latest.setdefault((snapshot.odds_type, snapshot.inplay), snapshot)
    return [OddsOut.model_validate(snapshot) for snapshot in latest.values()]


@router.get("/results", response_model=list[ResultOut])
async def list_results(
    session: AsyncSession = Depends(get_session),
    date_from: date | None = None,
    date_to: date | None = None,
    league: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ResultOut]:
    home = aliased(Team)
    away = aliased(Team)
    stmt = (
        select(Result, Match, League, home, away)
        .join(Match, Match.id == Result.match_id)
        .join(League, League.id == Match.league_id)
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .order_by(Match.kickoff_time.desc())
        .limit(limit)
        .offset(offset)
    )
    if date_from is not None:
        stmt = stmt.where(Match.kickoff_time >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to is not None:
        stmt = stmt.where(Match.kickoff_time <= datetime.combine(date_to, time.max, tzinfo=UTC))
    if league is not None:
        stmt = stmt.where(League.code == league)
    rows = (await session.execute(stmt)).all()
    return [
        ResultOut(
            match_id=result.match_id,
            home_score=result.home_score,
            away_score=result.away_score,
            ttl_corner=result.ttl_corner,
            source=result.source,
            confirmed=result.confirmed,
            payout_confirmed=result.payout_confirmed,
            confirmed_at=result.confirmed_at,
            kickoff_time=match.kickoff_time,
            league_code=lg.code,
            home_team=TeamOut.model_validate(home_team),
            away_team=TeamOut.model_validate(away_team),
        )
        for result, match, lg, home_team, away_team in rows
    ]
```

`app/api/main.py`:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import Settings, get_settings
from app.db.session import Database
from app.providers.football_data.provider import FootballDataProvider
from app.providers.hkjc.client import HkjcGraphQLClient
from app.providers.hkjc.provider import HkjcProvider


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        if not hasattr(app.state, "db"):
            app.state.db = Database(settings.database_url)
        hkjc_client = HkjcGraphQLClient(
            url=settings.hkjc_graphql_url,
            referer=settings.hkjc_referer,
            origin=settings.hkjc_origin,
            user_agent=settings.hkjc_user_agent,
            throttle_seconds=settings.hkjc_throttle_seconds,
        )
        app.state.hkjc_client = hkjc_client
        app.state.hkjc_provider = HkjcProvider(hkjc_client)
        app.state.football_data_provider = FootballDataProvider(settings.football_data_base)
        try:
            yield
        finally:
            await hkjc_client.aclose()
            await app.state.football_data_provider.aclose()
            if db is None:
                await app.state.db.dispose()

    app = FastAPI(title="Football Betting Agent — Data Layer", lifespan=lifespan)
    if db is not None:
        app.state.db = db
    app.include_router(router)
    return app
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_api.py -v`

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/api/__init__.py app/api/schemas.py app/api/routes.py app/api/main.py tests/test_api.py
git commit -m "feat: 新增 FastAPI 唯讀查詢端點"
```

---

### Task 16: APScheduler wiring and odds retention job

**Files:**
- Create: `app/scheduler.py`
- Modify: `app/api/main.py` (start/stop the scheduler in the lifespan)
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `app.config.Settings`, `app.providers.base.Provider`, `app.services.odds.{OddsSync, prune_odds_snapshots}`, `app.services.results.ResultReconciler`.
- Produces: `app.scheduler.build_scheduler(settings, session_factory, hkjc_provider, fallback_provider) -> AsyncIOScheduler` registering jobs `sync_odds`, `settle_results`, `prune_odds`.

- [ ] **Step 1: Write the failing test `tests/test_scheduler.py`**

```python
from app.config import Settings
from app.scheduler import build_scheduler


class _FakeProvider:
    name = "fake"

    async def fetch_leagues(self):
        return []

    async def fetch_fixtures(self, date_from, date_to):
        return []

    async def fetch_odds(self, fixtures):
        return []

    async def fetch_results(self, date_from, date_to):
        return []


def test_build_scheduler_registers_expected_jobs():
    settings = Settings(_env_file=None, sync_odds_interval=600, sync_settle_interval=900)
    scheduler = build_scheduler(settings, None, _FakeProvider(), _FakeProvider())
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"sync_odds", "settle_results", "prune_odds"}
    assert jobs["sync_odds"].trigger.interval.total_seconds() == 600
    assert jobs["settle_results"].trigger.interval.total_seconds() == 900
    assert jobs["prune_odds"].trigger.__class__.__name__ == "CronTrigger"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_scheduler.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.scheduler'`.

- [ ] **Step 3: Implement `app/scheduler.py`**

```python
import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.providers.base import Provider
from app.services.odds import OddsSync, prune_odds_snapshots
from app.services.results import ResultReconciler

logger = logging.getLogger(__name__)


def build_scheduler(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    hkjc_provider: Provider,
    fallback_provider: Provider,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _sync_odds_job,
        "interval",
        seconds=settings.sync_odds_interval,
        id="sync_odds",
        max_instances=1,
        coalesce=True,
        args=[settings, session_factory, hkjc_provider],
    )
    scheduler.add_job(
        _settle_results_job,
        "interval",
        seconds=settings.sync_settle_interval,
        id="settle_results",
        max_instances=1,
        coalesce=True,
        args=[settings, session_factory, hkjc_provider, fallback_provider],
    )
    scheduler.add_job(
        _prune_odds_job,
        "cron",
        hour=4,
        minute=0,
        id="prune_odds",
        max_instances=1,
        coalesce=True,
        args=[settings, session_factory],
    )
    return scheduler


async def _sync_odds_job(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    provider: Provider,
) -> None:
    today = datetime.now(UTC).date()
    try:
        await OddsSync(session_factory, provider, settings).run(today, today + timedelta(days=3))
    except Exception:
        logger.exception("sync_odds job failed")


async def _settle_results_job(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    hkjc_provider: Provider,
    fallback_provider: Provider,
) -> None:
    try:
        await ResultReconciler(session_factory, hkjc_provider, fallback_provider, settings).run()
    except Exception:
        logger.exception("settle_results job failed")


async def _prune_odds_job(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    try:
        await prune_odds_snapshots(session_factory, settings.odds_retention_days)
    except Exception:
        logger.exception("prune_odds job failed")
```

- [ ] **Step 4: Modify `app/api/main.py` to start and stop the scheduler**

Add the import at the top:

```python
from app.scheduler import build_scheduler
```

Replace the `try: yield finally:` block inside `lifespan` with:

```python
        scheduler = None
        if settings.enable_scheduler:
            scheduler = build_scheduler(
                settings,
                app.state.db.session_factory,
                app.state.hkjc_provider,
                app.state.football_data_provider,
            )
            scheduler.start()
        app.state.scheduler = scheduler
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            await hkjc_client.aclose()
            await app.state.football_data_provider.aclose()
            if db is None:
                await app.state.db.dispose()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_scheduler.py -v`

Expected: `1 passed`.

- [ ] **Step 6: Run the full suite to confirm nothing regressed**

Run: `uv run pytest -v`

Expected: all tests pass, `live` tests deselected.

- [ ] **Step 7: Commit**

```bash
git add app/scheduler.py app/api/main.py tests/test_scheduler.py
git commit -m "feat: 新增 APScheduler 排程器與賠率保留清理任務"
```

---

### Task 17: Backfill CLI

**Files:**
- Create: `app/cli.py`
- Test: `tests/test_cli_backfill.py`

**Interfaces:**
- Consumes: `app.config.get_settings`, `app.data.leagues.seed_leagues`, `app.db.models.{League, Match, OddsSnapshot, Season, Team}`, `app.db.session.Database`, `app.providers.football_data.provider.{FootballDataProvider, HistoricalMatchRecord}`, `app.services.alias.TeamMatcher`, `app.services.fixtures.season_bounds`, `app.services.runs.track_run`.
- Produces: `app.cli.backfill(session_factory, provider, year_from, year_to, divisions) -> int`; `app.cli.main(argv=None) -> None` with subcommands `backfill` and `seed-leagues`.

- [ ] **Step 1: Write the failing test `tests/test_cli_backfill.py`**

```python
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.cli import backfill
from app.data.leagues import seed_leagues
from app.db.base import Base
from app.db.models import Match, OddsSnapshot
from app.db.session import Database
from app.providers.football_data.provider import HistoricalMatchRecord


class _FakeProvider:
    name = "football_data"

    def __init__(self, records: list[HistoricalMatchRecord]) -> None:
        self._records = records

    async def fetch_historical(self, year, divisions=None):
        return self._records


def _record() -> HistoricalMatchRecord:
    return HistoricalMatchRecord(
        division="E0",
        league_code="EPL",
        season_label="2010/11",
        match_date=date(2010, 8, 14),
        kickoff_time=datetime(2010, 8, 14, 15, 0, tzinfo=UTC),
        home_team_name="Manchester United",
        away_team_name="Liverpool",
        home_score=2,
        away_score=1,
        odds={"B365": {"open": [1.5, 4.0, 6.0], "close": [1.6, 3.8, 5.5]}},
    )


async def _db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db.session_factory() as session:
        await seed_leagues(session)
        await session.commit()
    return db


async def test_backfill_creates_matches_and_odds(tmp_path):
    db = await _db(tmp_path)
    try:
        total = await backfill(db.session_factory, _FakeProvider([_record()]), 2010, 2010, ["E0"])
        assert total == 1
        async with db.session_factory() as session:
            match = (await session.execute(select(Match))).scalar_one()
            assert match.hkjc_match_id is None
            assert match.status == "finished"
            snapshot = (await session.execute(select(OddsSnapshot))).scalar_one()
            assert snapshot.odds_type == "HAD"
            assert snapshot.source == "football_data"
            assert snapshot.payload["odds"]["B365"]["close"] == [1.6, 3.8, 5.5]
    finally:
        await db.dispose()


async def test_backfill_is_idempotent(tmp_path):
    db = await _db(tmp_path)
    try:
        provider = _FakeProvider([_record()])
        await backfill(db.session_factory, provider, 2010, 2010, ["E0"])
        await backfill(db.session_factory, provider, 2010, 2010, ["E0"])
        async with db.session_factory() as session:
            assert len((await session.execute(select(Match))).scalars().all()) == 1
            assert len((await session.execute(select(OddsSnapshot))).scalars().all()) == 1
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_cli_backfill.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'app.cli'`.

- [ ] **Step 3: Implement `app/cli.py`**

```python
import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.data.leagues import seed_leagues
from app.db.models import League, Match, OddsSnapshot, Season, Team
from app.db.session import Database
from app.providers.football_data.provider import FootballDataProvider, HistoricalMatchRecord
from app.services.alias import TeamMatcher
from app.services.fixtures import season_bounds
from app.services.runs import track_run

DEFAULT_DIVISIONS = ["E0", "SP1", "I1", "D1", "F1"]


async def backfill(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FootballDataProvider,
    year_from: int,
    year_to: int,
    divisions: list[str],
) -> int:
    total = 0
    for year in range(year_from, year_to + 1):
        records = await provider.fetch_historical(year, divisions=divisions)
        total += await track_run(
            session_factory,
            "backfill_history",
            lambda session, recs=records: _upsert_history(session, recs),
        )
    return total


async def _upsert_history(session: AsyncSession, records: list[HistoricalMatchRecord]) -> int:
    count = 0
    for record in records:
        league = (
            await session.execute(select(League).where(League.code == record.league_code))
        ).scalar_one_or_none()
        if league is None:
            continue
        season = (
            await session.execute(
                select(Season).where(
                    Season.league_id == league.id, Season.label == record.season_label
                )
            )
        ).scalar_one_or_none()
        if season is None:
            start, end = season_bounds(record.season_label)
            season = Season(
                league_id=league.id,
                label=record.season_label,
                start_date=start,
                end_date=end,
            )
            session.add(season)
            await session.flush()
        home = await _resolve_team(session, record.home_team_name)
        away = await _resolve_team(session, record.away_team_name)
        match = (
            await session.execute(
                select(Match).where(
                    Match.season_id == season.id,
                    Match.home_team_id == home.id,
                    Match.away_team_id == away.id,
                    Match.kickoff_time == record.kickoff_time,
                )
            )
        ).scalar_one_or_none()
        if match is None:
            match = Match(
                season_id=season.id,
                league_id=league.id,
                hkjc_match_id=None,
                kickoff_time=record.kickoff_time,
                status="finished",
                home_team_id=home.id,
                away_team_id=away.id,
            )
            session.add(match)
            await session.flush()
        existing = (
            await session.execute(
                select(OddsSnapshot).where(
                    OddsSnapshot.match_id == match.id,
                    OddsSnapshot.odds_type == "HAD",
                    OddsSnapshot.inplay.is_(False),
                    OddsSnapshot.snapshot_bucket == record.kickoff_time,
                )
            )
        ).scalar_one_or_none()
        payload = {"odds": record.odds}
        if existing is None:
            session.add(
                OddsSnapshot(
                    match_id=match.id,
                    captured_at=record.kickoff_time,
                    snapshot_bucket=record.kickoff_time,
                    source="football_data",
                    inplay=False,
                    odds_type="HAD",
                    payload=payload,
                )
            )
        else:
            existing.payload = payload
        count += 1
    return count


async def _resolve_team(session: AsyncSession, name: str) -> Team:
    teams = (await session.execute(select(Team))).scalars().all()
    matched = TeamMatcher(teams).match(name)
    if matched is not None:
        return matched
    team = Team(name_en=name, name_ch=None, hkjc_team_id=None, aliases=[], external_ids={})
    session.add(team)
    await session.flush()
    return team


async def _run_backfill(args: argparse.Namespace) -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    provider = FootballDataProvider(settings.football_data_base, divisions=args.divisions)
    try:
        async with db.session_factory() as session:
            await seed_leagues(session)
            await session.commit()
        total = await backfill(
            db.session_factory, provider, args.year_from, args.year_to, args.divisions
        )
        print(f"backfill complete: {total} matches upserted")
    finally:
        await provider.aclose()
        await db.dispose()


async def _run_seed_leagues() -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        async with db.session_factory() as session:
            inserted = await seed_leagues(session)
            await session.commit()
        print(f"seed-leagues complete: {inserted} leagues inserted")
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backfill_parser = subparsers.add_parser("backfill", help="Bulk-load football-data.co.uk history")
    backfill_parser.add_argument("--from", dest="year_from", type=int, required=True)
    backfill_parser.add_argument("--to", dest="year_to", type=int, default=datetime.now(UTC).year)
    backfill_parser.add_argument(
        "--divisions",
        type=lambda value: [part.strip() for part in value.split(",") if part.strip()],
        default=DEFAULT_DIVISIONS,
    )

    subparsers.add_parser("seed-leagues", help="Insert whitelisted leagues")

    args = parser.parse_args(argv)
    if args.command == "backfill":
        asyncio.run(_run_backfill(args))
    elif args.command == "seed-leagues":
        asyncio.run(_run_seed_leagues())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_cli_backfill.py -v`

Expected: `2 passed`.

- [ ] **Step 5: Run the full suite and the linter**

Run:

```bash
uv run pytest -v
uv run ruff check .
```

Expected: all tests pass (`live` deselected); ruff reports no errors.

- [ ] **Step 6: Commit**

```bash
git add app/cli.py tests/test_cli_backfill.py
git commit -m "feat: 新增歷史回填與聯賽種子 CLI"
```

---

## Self-Review

### 1. Spec coverage checklist

| Spec section / requirement | Covered by |
|---|---|
| §5 `leagues` table | Task 3 (`League`), Task 4 (migration), Task 11 (seed) |
| §5 `seasons` table | Task 3 (`Season`), Task 4, Task 12 (`season_label_for`/`season_bounds`) |
| §5 `teams` table (`aliases text[]`, `external_ids jsonb`) | Task 3 (`_string_array_type`/`_json_type` variants), Task 4 |
| §5 `matches` table (`hkjc_match_id` UNIQUE, status enum) | Task 3, Task 4, Task 12 |
| §5 `odds_snapshots` (`snapshot_bucket` UNIQUE, `payload jsonb`) | Task 3, Task 4, Task 13 (`snapshot_bucket`) |
| §5 `results` (`match_id` UNIQUE, HKJC wins on conflict) | Task 3, Task 4, Task 14 |
| §5 `ingestion_runs` | Task 3, Task 4, Task 11 (`track_run`, `flag_manual_review`) |
| §5 timezones (timestamptz UTC) | Task 2 (`UtcDateTime`), Global Constraints |
| §5 retention job | Task 13 (`prune_odds_snapshots`), Task 16 (`prune_odds` cron) |
| §6 Provider Protocol + record types | Task 5 |
| §6 `HkjcProvider` (GraphQL, two-batch odds, `matchResult`, payout details) | Tasks 6, 7, 8 |
| §6 `FootballDataProvider` (CSV, `fetch_historical`) | Task 9 |
| §7 `sync_odds` (fixtures → matches → snapshots) | Task 12, Task 13, Task 16 |
| §7 `settle_results` (HKJC-first → fallback → 48h flag) | Task 14, Task 16 |
| §7 `backfill_history` CLI | Task 17 |
| §8 request hygiene (four headers), throttle, backoff, raw audit, isolation, observability | Task 7 (headers/throttle/retry), Task 8 (raw payloads), Task 11 (runs), Global Constraints |
| §9 provider contract tests (recorded fixtures) | Tasks 8, 9 |
| §9 reconciliation tests (hit / fallback / both-miss / never-overwrite) | Task 14 |
| §9 idempotency tests | Tasks 12, 13, 17 |
| §9 alias-matching tests (曼聯/Man Utd/Manchester United) | Task 10 |
| §9 opt-in live smoke test (`pytest -m live`) | Tasks 8, 9 (`@pytest.mark.live`), `pyproject.toml` marker |
| §10 config env vars | Task 1 (`Settings`, `.env.example`) |
| §12 FastAPI read endpoints `/matches`, `/matches/{id}/odds`, `/results` | Task 15 |
| §3 exact HKJC query documents (no ad-hoc queries) | Task 6 |
| §3/§11 `matchResult` with explicit `startIndex`/`endIndex` | Task 6 (document), Task 8 (`RESULT_PAGE_SIZE`) |
| §3 football-data URL + Big-5 only, UCL absent | Task 9 (`DIVISIONS`, `_download` 404 → `[]`) |

### 2. Placeholder scan

This plan contains no `TBD`, `TODO`, `FIXME`, "add error handling", "write tests for the above", or "similar to Task N" placeholders. Every code step contains the complete file body. To confirm before starting, run:

```bash
grep -nE "TBD|TODO|FIXME|fill in|similar to Task|\.\.\.$" docs/superpowers/plans/2026-10-12-football-agent-data-layer.md
```

Expected: no matches (the only `...` occurrences are inside the verbatim GraphQL documents and Python `Protocol` method stubs, which are intentional).

### 3. Type consistency

Cross-task symbols and their single definitions (verify each is imported from the same module everywhere it is used):

| Symbol | Defined in | Used by |
|---|---|---|
| `Settings`, `get_settings` | `app/config.py` (Task 1) | Tasks 12, 13, 14, 15, 16, 17 |
| `Base`, `UtcDateTime` | `app/db/base.py` (Task 2) | Tasks 3, 4, 5–17 tests |
| `Database` | `app/db/session.py` (Task 2) | Tasks 11–17 |
| `League`, `Season`, `Team`, `Match`, `OddsSnapshot`, `Result`, `IngestionRun` | `app/db/models.py` (Task 3) | Tasks 11–17 |
| `Provider`, `LeagueRecord`, `FixtureRecord`, `OddsRecord`, `ResultRecord` | `app/providers/base.py` (Task 5) | Tasks 8, 9, 12, 13, 14, 16 |
| `FOOTBALL_MATCHES_QUERY`, `HISTORIC_FOOTBALL_MATCHES_QUERY`, `HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY`, `ODDS_TYPE_BATCHES`, `DEFAULT_ODDS_TYPES` | `app/providers/hkjc/queries.py` (Task 6) | Task 8 |
| `HkjcGraphQLClient`, `HkjcGraphQLError` | `app/providers/hkjc/client.py` (Task 7) | Tasks 8, 15 |
| `HkjcProvider` | `app/providers/hkjc/provider.py` (Task 8) | Tasks 15, 16 |
| `FootballDataProvider`, `HistoricalMatchRecord`, `season_code`, `DIVISIONS` | `app/providers/football_data/provider.py` (Task 9) | Tasks 15, 16, 17 |
| `normalize_team_name`, `load_alias_map`, `TeamMatcher`, `FUZZY_THRESHOLD` | `app/services/alias.py` (Task 10) | Tasks 12, 14, 17 |
| `track_run`, `flag_manual_review` | `app/services/runs.py` (Task 11) | Tasks 12, 13, 14, 17 |
| `LEAGUE_SEED`, `seed_leagues` | `app/data/leagues.py` (Task 11) | Tasks 15, 17 |
| `FixtureSync`, `season_label_for`, `season_bounds` | `app/services/fixtures.py` (Task 12) | Tasks 13, 17 |
| `OddsSync`, `snapshot_bucket`, `prune_odds_snapshots` | `app/services/odds.py` (Task 13) | Task 16 |
| `ResultReconciler` | `app/services/results.py` (Task 14) | Task 16 |
| `create_app` | `app/api/main.py` (Task 15) | Task 15 tests |
| `build_scheduler` | `app/scheduler.py` (Task 16) | `app/api/main.py` (Task 16) |
| `backfill`, `main` | `app/cli.py` (Task 17) | Task 17 tests |

Naming notes: the provider record for a league is `LeagueRecord` (not `League`) to avoid colliding with the ORM `League` model; the spec's `Provider` method names (`fetch_leagues`, `fetch_fixtures`, `fetch_odds`, `fetch_results`) are used verbatim. `HkjcProvider.fetch_result_details` is the spec's optional payout-detail method and is intentionally outside the `Provider` Protocol.

### 4. Definition of done

- `uv run pytest -v` → all tests pass, `live` tests deselected.
- `uv run pytest -m live -v` → opt-in smoke tests pass against the real HKJC + football-data endpoints (manual).
- `uv run ruff check .` → clean.
- `uv run alembic upgrade head` → applies `0001` to PostgreSQL.
- `uv run python -m app.cli seed-leagues` then `uv run python -m app.cli backfill --from 2010` → populates the training corpus.
- `uv run uvicorn app.api.main:create_app --factory` → serves `/matches`, `/matches/{id}/odds`, `/results`, `/health`.



