# Foundation, Data, and Paper Ledger (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 vertical slice: a runnable data ingestion pipeline for football-data.org, Understat, FotMob, PL pulselive, FPL, HKJC GraphQL, football-data.co.uk, RSS and Open-Meteo, plus canonical normalization, a data quality gate, an HKJC regulation-time settlement engine, a paper ledger, and scheduler/worker/API scaffolding.

**Architecture:** A modular monolith. Domain types live in `packages/domain`, persistence in `packages/db`, external sources in `packages/adapters`, canonical ingestion in `packages/ingest`, and paper betting in `packages/ledger`. `apps/api`, `apps/worker`, and `apps/scheduler` are thin runtimes over these packages. Phase 1 exposes only `/healthz` and `/readyz`; prediction, agent, ensemble, value, risk and dashboard modules are later phases.

**Tech Stack:** Python 3.12, uv, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, Postgres 16, Redis 7, RQ, APScheduler, httpx, selectolax, feedparser, pytest, respx. All odds and money use `Decimal`.

## Global Constraints

- Competitions: EPL, La Liga, Bundesliga, Serie A, Ligue 1, plus UEFA Champions League. No other leagues.
- Markets: `HAD` (主客和), `HDC` (讓球), `HIL` (入球大細) only. `HHA` (讓球主客和) is out of scope.
- Paper only. Initial paper bankroll is HK$10,000. Never place real money, never log in to HKJC, never auto-bet.
- Free data only. No paid data providers. DeepSeek Flash belongs to a later phase.
- Modular monolith: FastAPI + Postgres + Redis/RQ + APScheduler. No microservices.
- HKJC settlement uses regulation time only: 90 minutes plus stoppage time. Extra time, penalties and replays never count.
- HKJC payouts round the final payout to the nearest HK$0.10 with `ROUND_HALF_UP`. Never round odds first.
- Odds and money are stored and computed as `Decimal`. Never use `float` for money or odds.
- Every source observation must carry `source_name`, `source_url`, `fetched_at`, `schema_version`, and `payload_hash`.
- Raw payloads are immutable. Normalized rows must be rebuildable from raw payloads.
- Match results must store `home_goals_90` / `away_goals_90` separately from `home_goals_final` / `away_goals_final`. A final-only source cannot settle a regulation-time market.
- Coverage flags are `ucl_xg_missing`, `lineup_unconfirmed`, `odds_stale`, `news_missing`, `source_degraded`.
- HKJC odds older than 10 minutes are stale. A stale snapshot cannot support a bet.
- Scheduler timezone is `Asia/Hong_Kong`. All database timestamps are UTC.
- Secrets live in `.env` only and must never enter git.
- Rate limits: football-data.org at most 10 requests per minute, HKJC no faster than the site's 60 second pre-match refresh, FotMob upcoming match details at most every 10 minutes, RSS every 15 minutes, Open-Meteo daily batches.
- Do not modify the design spec in `docs/superpowers/specs/2026-10-31-data-multiagent-betting-design.md`.

## Phase Boundary

Phase 1 implements foundation, adapters, canonical normalization, HKJC odds and result ingestion, the paper ledger, settlement, and a runnable data plus ledger pipeline. It does not implement Dixon-Coles, Elo, GBM, calibration, backtesting, LLM agents, ensemble voting, value/Kelly sizing, risk veto policy, the Next.js dashboard, or real-money workflows. Interfaces needed by Phase 1 are limited to the types defined in this plan.

## Revision 2 (v2.1) — mandatory plan amendments

This section is normative. Every task below is read through this section. If any task text conflicts with this section, this section wins.

### Scope and phase gates

- Phase 1 is **G0 + G1 only**.
- The first validated decision slice is **EPL + HAD**.
- The full target remains 5 leagues plus UCL with HAD, HDC and HIL, but HDC/HIL production paper bets are **G4** and are not part of G1.
- LLM production weights are **0** in Phase 1. LLM shadow work is **G2**.
- `packages/payoff` may implement and test HDC/HIL in G0/G1, but no HDC/HIL paper bet, no HDC/HIL market baseline, and no split-line de-vig may run in G1.
- `run_dry_run` is engineering and settlement validation only. It is not LLM predictive evidence.
- The single `run_key` is deleted. Only `analysis_run_key`, `decision_slot_key`, and unique `bet_intent_key` remain.
- Binary `p * odds - 1` and binary Kelly are allowed only for HAD. HDC/HIL must use the shared payoff engine and return distributions.
- Global `[0.01, 0.99]` probability clipping is banned. Probabilities are finite, in `[0, 1]`, sum to 1 within tolerance, and impossible outcomes are exactly `0`.
- HDC/HIL de-vig is `unavailable`. No task may infer component-line probabilities from one split-line quote.

#### G0 checklist

- [ ] Lock the payoff and distribution contract in `packages/payoff`.
- [ ] Lock market semantics and temporal field names.
- [ ] Record the source verification plan: source list, allowed-usage check, real-fixture check.
- [ ] Prepare HAD settlement fixtures and split-line payoff fixtures.
- [ ] Prove the distribution contract: 121-cell score support, impossible outcomes exactly `0`, sum tolerance, no global clipping, tail mass recorded.
- [ ] Confirm no paid source is required to start G1.

#### G1 checklist

- [ ] EPL + HAD core sources have explicit `verified`, `conditional`, or `blocked` status and evidence records.
- [ ] HAD payoff and settlement property tests pass, including void and 10-cent rounding.
- [ ] Prospective decision gate passes: `first_seen_at <= decision_at`.
- [ ] `paper_bets.bet_intent_key` has a database unique constraint.
- [ ] Bankroll check, reservation insert, and paper bet insert run in one transaction.
- [ ] `cash_available = bankroll_balance - reserved_stake` never goes negative.
- [ ] All eligible EPL matches have saved predictions, including no-bet matches.
- [ ] 30-match dry run has no duplicate bet and no negative bankroll; it is engineering evidence only.
- [ ] G1 does not depend on LLM shadow, HDC/HIL, UCL, or split-line de-vig.

### Mandatory override table

| Old text below | v2.1 replacement |
|---|---|
| Phase 1 covers full HAD/HDC/HIL pipeline | Phase 1 decision path is EPL + HAD only; HDC/HIL production is G4 |
| Task 3 allows odds exactly `1.01` to be rejected | Reject only odds `< 1.01`; `1.01` is valid |
| Task 3 accepts signed HIL conditions | HIL total lines must be unsigned |
| Task 3 settlement is the only payoff logic | `packages/payoff` is the shared payoff engine; settlement cross-checks it |
| Task 4 `paper_bets.run_key` | Replace with `analysis_run_key`, `decision_slot_key`, `bet_intent_key` UNIQUE, `decision_at` |
| Task 4 has no bankroll tables | Add `bankroll_accounts` and `bankroll_reservations` |
| Task 10 quality gate uses kickoff freshness only | Add prospective and retrospective decision-time gates |
| Task 11 uses one ledger run key | Use three-layer idempotency and bankroll reservation transaction |
| Task 11 metrics are bet-only and point estimates | Add eligible-prediction metrics, match clustering, intervals, strategy version, decision-time versus closing comparison |
| Task 12 runs all markets | Run only EPL + HAD decision path; HDC/HIL ingestion may exist but cannot create paper bets |
| Task 12 dry run is evidence | Dry run is engineering and settlement validation only |

---

### Task 1: Bootstrap Repository, Tooling, Docker, and Test Harness

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `packages/__init__.py`
- Create: `packages/shared/__init__.py`
- Create: `packages/shared/config.py`
- Create: `packages/shared/logging.py`
- Create: `packages/shared/time.py`
- Test: `tests/test_bootstrap.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings` with `database_url`, `redis_url`, `football_data_org_api_key`, `initial_bankroll`, `fee_rate`; `get_settings()`; `configure_logging()`; `JsonFormatter`; `utc_now()`, `ensure_utc(value)`, `parse_iso_utc(value)`.

- [ ] **Step 1: Write the failing bootstrap test**

Create `tests/test_bootstrap.py`:

```python
import json
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal

from packages.shared.config import Settings
from packages.shared.logging import JsonFormatter
from packages.shared.time import ensure_utc, parse_iso_utc, utc_now


def test_settings_defaults_without_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("FP_"):
            monkeypatch.delenv(key)
    settings = Settings(_env_file=None)
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.redis_url.startswith("redis://")
    assert settings.initial_bankroll == Decimal("10000.00")
    assert settings.fee_rate == Decimal("0")


def test_json_formatter_emits_structured_record():
    record = logging.LogRecord("test.logger", logging.INFO, __file__, 1, "hello", (), None)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"


def test_time_helpers_normalize_to_utc():
    parsed = parse_iso_utc("2026-08-15T14:00:00Z")
    assert parsed == datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
    assert ensure_utc(datetime(2026, 8, 15, 14, 0)) == datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
    assert utc_now().tzinfo is UTC
    assert parse_iso_utc(None) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_bootstrap.py -v`

Expected: collection error because `pyproject.toml` and `packages.shared.config` do not exist.

- [ ] **Step 3: Create project metadata and environment files**

Create `pyproject.toml`:

```toml
[project]
name = "football-pred"
version = "0.1.0"
description = "Paper-only football research system built on free data"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "sqlalchemy>=2.0.36",
  "alembic>=1.14",
  "psycopg[binary]>=3.2",
  "redis>=5.2",
  "rq>=2.1",
  "apscheduler>=3.11",
  "httpx>=0.28",
  "selectolax>=0.3.27",
  "feedparser>=6.0.11",
]

[dependency-groups]
dev = [
  "pytest>=8.3",
  "respx>=0.22",
  "ruff>=0.8",
  "playwright>=1.49",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["packages"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py312"
```

Create `.python-version`:

```text
3.12
```

Create `.gitignore`:

```text
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.env
.env.local
.env.*.local
node_modules/
.next/
dist/
.DS_Store
backups/
artifacts/
dry_run.db
```

Create `.env.example`:

```text
FP_DATABASE_URL=postgresql+psycopg://football:football@localhost:5432/football_pred
FP_REDIS_URL=redis://localhost:6379/0
FP_FOOTBALL_DATA_ORG_API_KEY=
FP_INITIAL_BANKROLL=10000.00
FP_FEE_RATE=0
```

- [ ] **Step 4: Create Docker and Compose files**

Create `Dockerfile`:

```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: football
      POSTGRES_PASSWORD: football
      POSTGRES_DB: football_pred
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U football -d football_pred"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  api:
    build: .
    command: uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    ports:
      - "8000:8000"

  worker:
    build: .
    command: uv run python -m apps.worker.main
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  scheduler:
    build: .
    command: uv run python -m apps.scheduler.main
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

volumes:
  pgdata:
```

- [ ] **Step 5: Create configuration, logging, and time helpers**

Create `packages/__init__.py` and `packages/shared/__init__.py` as empty files.

Create `packages/shared/config.py`:

```python
from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FP_", extra="ignore")

    database_url: str = "postgresql+psycopg://football:football@localhost:5432/football_pred"
    redis_url: str = "redis://localhost:6379/0"
    football_data_org_api_key: str | None = None
    initial_bankroll: Decimal = Decimal("10000.00")
    fee_rate: Decimal = Decimal("0")
    http_timeout_seconds: float = 20.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Create `packages/shared/logging.py`:

```python
import json
import logging
import sys
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    extra_fields = ("run_id", "match_id", "trigger", "source_name")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.extra_fields:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
```

Create `packages/shared/time.py`:

```python
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ensure_utc(parsed)
```

- [ ] **Step 6: Install dependencies and run the test**

Run: `uv lock && uv sync`

Expected: uv reports resolved dependencies and creates `.venv` without error.

Run: `uv run pytest tests/test_bootstrap.py -v`

Expected: `3 passed`.

- [ ] **Step 7: Verify Docker services start**

Run: `docker compose up -d postgres redis`

Expected: both containers report `Started` or `Healthy`.

Run: `docker compose ps`

Expected: `postgres` and `redis` show `running`.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock .python-version .gitignore .env.example Dockerfile docker-compose.yml packages tests/test_bootstrap.py
git commit -m "chore: bootstrap python project, docker services, and test harness"
```

---

### Task 2: Domain Enums, Errors, and HKJC Condition Parser

**Files:**
- Create: `packages/domain/__init__.py`
- Create: `packages/domain/enums.py`
- Create: `packages/domain/errors.py`
- Create: `packages/domain/markets.py`
- Test: `tests/domain/test_markets.py`

**Interfaces:**
- Consumes: nothing from earlier tasks beyond the package root.
- Produces: enums `MarketType`, `Side`, `LineupType`, `AvailabilityStatus`, `MatchStatus`, `CoverageFlag`, `BetStatus`, `SettlementSource`, `FetchRunStatus`, `HkjcResultSemantics`, `SnapshotKind`; errors `DomainError`, `InvalidConditionRaw`, `UnsupportedMarket`, `SettlementError`, `SettlementInputError`, `DuplicateBetError`, `AlreadySettledError`, `InsufficientBankrollError`, `UnresolvedTeamError`; functions `parse_condition_raw(raw) -> tuple[Decimal, ...]`, `canonical_line_key(raw) -> str`, `is_split_line(halves) -> bool`, `validate_side(market, side) -> None`.

- [ ] **Step 1: Write the failing parser tests**

Create `tests/domain/test_markets.py`:

```python
from decimal import Decimal

import pytest

from packages.domain.enums import MarketType, Side
from packages.domain.errors import InvalidConditionRaw, UnsupportedMarket
from packages.domain.markets import (
    canonical_line_key,
    is_split_line,
    parse_condition_raw,
    validate_side,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.0", (Decimal("0.0"),)),
        ("+0.5", (Decimal("+0.5"),)),
        ("-1", (Decimal("-1"),)),
        ("1.0/1.5", (Decimal("1.0"), Decimal("1.5"))),
        ("-0.25/0", (Decimal("-0.25"), Decimal("0"))),
        (" 2.5 ", (Decimal("2.5"),)),
    ],
)
def test_parse_condition_raw_accepts_valid_lines(raw, expected):
    assert parse_condition_raw(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "1/2/3", "1.0//1.5", "1,5", "1.0/", "/1.0"])
def test_parse_condition_raw_rejects_invalid_lines(raw):
    with pytest.raises(InvalidConditionRaw):
        parse_condition_raw(raw)


def test_split_line_detection():
    assert is_split_line(parse_condition_raw("1.0/1.5")) is True
    assert is_split_line(parse_condition_raw("1.5")) is False


def test_line_key_preserves_source_condition_string():
    assert canonical_line_key(" 1.0/1.5 ") == "1.0/1.5"


def test_validate_side_enforces_market_outcomes():
    validate_side(MarketType.HAD, Side.D)
    validate_side(MarketType.HDC, Side.A)
    validate_side(MarketType.HIL, Side.L)
    with pytest.raises(UnsupportedMarket):
        validate_side(MarketType.HAD, Side.L)
    with pytest.raises(UnsupportedMarket):
        validate_side(MarketType.HIL, Side.D)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/domain/test_markets.py -v`

Expected: collection error because `packages.domain` does not exist.

- [ ] **Step 3: Create the enums**

Create `packages/domain/__init__.py` as an empty file.

Create `packages/domain/enums.py`:

```python
from enum import StrEnum


class MarketType(StrEnum):
    HAD = "HAD"
    HDC = "HDC"
    HIL = "HIL"


class Side(StrEnum):
    H = "H"
    D = "D"
    A = "A"
    L = "L"


class LineupType(StrEnum):
    PREDICTED = "predicted"
    STANDARD = "standard"


class AvailabilityStatus(StrEnum):
    INJURY = "injury"
    SUSPENSION = "suspension"
    DOUBTFUL = "doubtful"
    AVAILABLE = "available"


class MatchStatus(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class CoverageFlag(StrEnum):
    UCL_XG_MISSING = "ucl_xg_missing"
    LINEUP_UNCONFIRMED = "lineup_unconfirmed"
    ODDS_STALE = "odds_stale"
    NEWS_MISSING = "news_missing"
    SOURCE_DEGRADED = "source_degraded"


class BetStatus(StrEnum):
    PENDING = "pending"
    WON = "won"
    LOST = "lost"
    HALF_WON_HALF_PUSH = "half_won_half_push"
    HALF_LOST_HALF_PUSH = "half_lost_half_push"
    PUSH = "push"
    VOID = "void"


class SettlementSource(StrEnum):
    HKJC_CONFIRMED = "hkjc_confirmed"
    HKJC_PROVISIONAL = "hkjc_provisional"
    EXTERNAL_PROVISIONAL = "external_provisional"
    PENDING = "pending"


class FetchRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class HkjcResultSemantics(StrEnum):
    UNVERIFIED = "unverified"
    REGULATION_TIME = "regulation_time"


class SnapshotKind(StrEnum):
    T24H = "t-24h"
    T3H = "t-3h"
    T30M = "t-30m"
    T5M = "t-5m"
    MANUAL = "manual"
```

- [ ] **Step 4: Create the error hierarchy**

Create `packages/domain/errors.py`:

```python
class DomainError(Exception):
    """Base class for domain failures."""


class InvalidConditionRaw(DomainError):
    pass


class UnsupportedMarket(DomainError):
    pass


class SettlementError(DomainError):
    pass


class SettlementInputError(SettlementError):
    pass


class DuplicateBetError(DomainError):
    pass


class AlreadySettledError(DomainError):
    pass


class InsufficientBankrollError(DomainError):
    pass


class UnresolvedTeamError(DomainError):
    pass
```

- [ ] **Step 5: Create the condition parser**

Create `packages/domain/markets.py`:

```python
import re
from decimal import Decimal

from packages.domain.enums import MarketType, Side
from packages.domain.errors import InvalidConditionRaw, UnsupportedMarket

CONDITION_RAW_PATTERN = re.compile(r"^[+-]?\d+(\.\d+)?(/[+-]?\d+(\.\d+)?)?$")
MAX_HALVES = 2

_ALLOWED_SIDES: dict[MarketType, set[Side]] = {
    MarketType.HAD: {Side.H, Side.D, Side.A},
    MarketType.HDC: {Side.H, Side.A},
    MarketType.HIL: {Side.H, Side.L},
}


def parse_condition_raw(raw: str) -> tuple[Decimal, ...]:
    candidate = raw.strip()
    if not CONDITION_RAW_PATTERN.fullmatch(candidate):
        raise InvalidConditionRaw(raw)
    halves = tuple(Decimal(part) for part in candidate.split("/"))
    if len(halves) == 0 or len(halves) > MAX_HALVES:
        raise InvalidConditionRaw(raw)
    return halves


def canonical_line_key(raw: str) -> str:
    parse_condition_raw(raw)
    return raw.strip()


def is_split_line(halves: tuple[Decimal, ...]) -> bool:
    return len(halves) == MAX_HALVES


def validate_side(market: MarketType, side: Side) -> None:
    allowed = _ALLOWED_SIDES.get(market)
    if allowed is None or side not in allowed:
        raise UnsupportedMarket(f"{side.value} is not a valid outcome for {market.value}")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/domain/test_markets.py -v`

Expected: `16 passed`.

- [ ] **Step 7: Commit**

```bash
git add packages/domain tests/domain/test_markets.py
git commit -m "feat: add domain enums and hkjc condition parser"
```

---

### Task 3: Regulation-Time Settlement Engine

**Files:**
- Create: `packages/ledger/__init__.py`
- Create: `packages/ledger/settlement.py`
- Test: `tests/ledger/test_settlement.py`

**Interfaces:**
- Consumes: `MarketType`, `Side`, `BetStatus`, `parse_condition_raw`, `is_split_line`, `validate_side`, `InvalidConditionRaw`.
- Produces: `SettlementOutcome(result_status, payout, payout_unrounded, void_reason)`; `round_payout(amount)`; `settle_had(selection, home_goals_90, away_goals_90, odds, stake)`; `settle_hdc(selection, home_goals_90, away_goals_90, condition_raw, odds, stake)`; `settle_hil(...)`; `settle_void(stake)`; `settle_market(market, selection, home_goals_90, away_goals_90, condition_raw, odds, stake)`.

- [ ] **Step 1: Write the failing settlement tests**

Create `tests/ledger/test_settlement.py`:

```python
from decimal import Decimal

import pytest

from packages.domain.enums import BetStatus, MarketType, Side
from packages.domain.errors import SettlementInputError
from packages.ledger.settlement import (
    round_payout,
    settle_had,
    settle_hdc,
    settle_hil,
    settle_market,
    settle_void,
)

D = Decimal


def test_had_home_win():
    outcome = settle_had(Side.H, 2, 1, D("2.00"), D("10.00"))
    assert outcome.result_status is BetStatus.WON
    assert outcome.payout == D("20.00")


def test_had_draw_and_away():
    draw = settle_had(Side.D, 1, 1, D("3.40"), D("10.00"))
    away = settle_had(Side.A, 0, 1, D("3.80"), D("10.00"))
    assert draw.result_status is BetStatus.WON
    assert draw.payout == D("34.00")
    assert away.result_status is BetStatus.WON
    assert away.payout == D("38.00")


def test_had_losing_selection_returns_zero():
    outcome = settle_had(Side.H, 0, 2, D("2.00"), D("10.00"))
    assert outcome.result_status is BetStatus.LOST
    assert outcome.payout == D("0.00")


def test_hdc_single_line_win_and_push():
    win = settle_hdc(Side.H, 2, 1, "-0.5", D("1.95"), D("10.00"))
    push = settle_hdc(Side.H, 2, 1, "-1.0", D("1.95"), D("10.00"))
    assert win.result_status is BetStatus.WON
    assert push.result_status is BetStatus.PUSH
    assert push.payout == D("10.00")


def test_hdc_split_line_half_win_half_push():
    outcome = settle_hdc(Side.H, 1, 0, "0.0/-1.0", D("1.95"), D("10.00"))
    assert outcome.result_status is BetStatus.HALF_WON_HALF_PUSH
    assert outcome.payout_unrounded == D("14.75")
    assert outcome.payout == D("14.80")


def test_hdc_split_line_half_lose_half_push():
    outcome = settle_hdc(Side.H, 1, 1, "0.0/-1.0", D("1.95"), D("10.00"))
    assert outcome.result_status is BetStatus.HALF_LOST_HALF_PUSH
    assert outcome.payout == D("5.00")


def test_hdc_split_line_both_lose():
    away_wins = settle_hdc(Side.A, 0, 1, "0.0/-1.0", D("1.95"), D("10.00"))
    assert away_wins.result_status is BetStatus.WON
    home_loses = settle_hdc(Side.H, 0, 1, "0.0/-1.0", D("1.95"), D("10.00"))
    assert home_loses.result_status is BetStatus.LOST


def test_hil_single_line_push_and_win():
    push = settle_hil(Side.H, 2, 1, "3.0", D("1.90"), D("10.00"))
    over = settle_hil(Side.H, 2, 2, "3.5", D("1.90"), D("10.00"))
    under = settle_hil(Side.L, 1, 0, "2.5", D("1.90"), D("10.00"))
    assert push.result_status is BetStatus.PUSH
    assert over.result_status is BetStatus.WON
    assert under.result_status is BetStatus.WON


def test_hil_split_line_half_win_half_push():
    outcome = settle_hil(Side.H, 2, 1, "2.5/3.0", D("1.90"), D("10.00"))
    assert outcome.result_status is BetStatus.HALF_WON_HALF_PUSH
    assert outcome.payout_unrounded == D("14.50")
    assert outcome.payout == D("14.50")


def test_rounding_uses_half_up_to_ten_cents():
    assert round_payout(D("20.15")) == D("20.20")
    assert round_payout(D("20.14")) == D("20.10")
    assert round_payout(D("0")) == D("0.00")


def test_void_returns_stake_and_rounds():
    outcome = settle_void(D("10.04"))
    assert outcome.result_status is BetStatus.VOID
    assert outcome.payout == D("10.00")


def test_market_dispatcher_routes_hdc_and_hil():
    hdc = settle_market(MarketType.HDC, Side.H, 1, 0, "0.0/-1.0", D("1.95"), D("10.00"))
    hil = settle_market(MarketType.HIL, Side.H, 2, 1, "2.5/3.0", D("1.90"), D("10.00"))
    assert hdc.result_status is BetStatus.HALF_WON_HALF_PUSH
    assert hil.result_status is BetStatus.HALF_WON_HALF_PUSH


def test_ucl_match_settles_on_ninety_minute_score_not_final():
    outcome = settle_had(Side.D, 1, 1, D("3.40"), D("10.00"))
    assert outcome.result_status is BetStatus.WON


def test_rejects_invalid_inputs():
    with pytest.raises(SettlementInputError):
        settle_had(Side.H, 1, 0, D("1.00"), D("10.00"))
    with pytest.raises(SettlementInputError):
        settle_had(Side.H, 1, 0, D("2.00"), D("0"))
    with pytest.raises(SettlementInputError):
        settle_hdc(Side.H, 1, 0, "bad", D("1.95"), D("10.00"))


def test_odds_exactly_one_point_zero_one_is_allowed():
    outcome = settle_had(Side.H, 1, 0, D("1.01"), D("10.00"))
    assert outcome.result_status is BetStatus.WON
    assert outcome.payout == D("10.10")


def test_signed_hil_condition_is_rejected():
    with pytest.raises(SettlementInputError):
        settle_hil(Side.H, 2, 1, "-0.5", D("1.90"), D("10.00"))
    with pytest.raises(SettlementInputError):
        settle_hil(Side.L, 2, 1, "2.5/-3.0", D("1.90"), D("10.00"))


def test_settlement_api_accepts_only_ninety_minute_goals():
    import inspect

    parameters = inspect.signature(settle_market).parameters
    assert "home_goals_90" in parameters
    assert "away_goals_90" in parameters
    assert "home_goals_final" not in parameters
    draw = settle_market(MarketType.HAD, Side.D, 1, 1, "0.0", D("3.40"), D("10.00"))
    assert draw.result_status is BetStatus.WON
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/ledger/test_settlement.py -v`

Expected: collection error because `packages.ledger` does not exist.

- [ ] **Step 3: Implement the settlement engine**

Create `packages/ledger/__init__.py` as an empty file.

Create `packages/ledger/settlement.py`:

```python
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from packages.domain.enums import BetStatus, MarketType, Side
from packages.domain.errors import InvalidConditionRaw, SettlementInputError
from packages.domain.markets import parse_condition_raw, validate_side

PAYOUT_STEP = Decimal("0.10")
PAYOUT_ROUNDING = ROUND_HALF_UP
MIN_ODDS = Decimal("1.01")


class _HalfOutcome(StrEnum):
    WIN = "win"
    LOSE = "lose"
    PUSH = "push"


@dataclass(frozen=True)
class SettlementOutcome:
    result_status: BetStatus
    payout: Decimal
    payout_unrounded: Decimal
    void_reason: str | None = None


def round_payout(amount: Decimal) -> Decimal:
    return amount.quantize(PAYOUT_STEP, rounding=PAYOUT_ROUNDING)


def _validate_common(odds: Decimal, stake: Decimal) -> None:
    if odds < MIN_ODDS:
        raise SettlementInputError(f"odds must be at least {MIN_ODDS}, got {odds}")
    if stake <= Decimal("0"):
        raise SettlementInputError(f"stake must be positive, got {stake}")


def _validate_goals(home_goals_90: int, away_goals_90: int) -> None:
    if home_goals_90 < 0 or away_goals_90 < 0:
        raise SettlementInputError("goals cannot be negative")


def _payout_for_half(half_stake: Decimal, odds: Decimal, outcome: _HalfOutcome) -> Decimal:
    if outcome is _HalfOutcome.WIN:
        return half_stake * odds
    if outcome is _HalfOutcome.PUSH:
        return half_stake
    return Decimal("0")


def _single_status(outcome: _HalfOutcome) -> BetStatus:
    if outcome is _HalfOutcome.WIN:
        return BetStatus.WON
    if outcome is _HalfOutcome.PUSH:
        return BetStatus.PUSH
    return BetStatus.LOST


def _split_status(outcomes: tuple[_HalfOutcome, ...]) -> BetStatus:
    ordered = sorted(outcomes, key=lambda item: item.value)
    pair = (ordered[0], ordered[1])
    if pair == (_HalfOutcome.WIN, _HalfOutcome.WIN):
        return BetStatus.WON
    if pair == (_HalfOutcome.LOSE, _HalfOutcome.LOSE):
        return BetStatus.LOST
    if pair == (_HalfOutcome.PUSH, _HalfOutcome.PUSH):
        return BetStatus.PUSH
    if pair == (_HalfOutcome.PUSH, _HalfOutcome.WIN):
        return BetStatus.HALF_WON_HALF_PUSH
    if pair == (_HalfOutcome.LOSE, _HalfOutcome.PUSH):
        return BetStatus.HALF_LOST_HALF_PUSH
    raise SettlementInputError(f"unsupported half outcome pair {pair}")


def _build_outcome(
    stake: Decimal,
    odds: Decimal,
    half_outcomes: tuple[_HalfOutcome, ...],
) -> SettlementOutcome:
    if len(half_outcomes) == 1:
        outcome = half_outcomes[0]
        if outcome is _HalfOutcome.WIN:
            unrounded = stake * odds
        elif outcome is _HalfOutcome.PUSH:
            unrounded = stake
        else:
            unrounded = Decimal("0")
        return SettlementOutcome(
            result_status=_single_status(outcome),
            payout=round_payout(unrounded),
            payout_unrounded=unrounded,
        )
    half_stake = stake / Decimal("2")
    unrounded = sum(
        (_payout_for_half(half_stake, odds, outcome) for outcome in half_outcomes),
        Decimal("0"),
    )
    return SettlementOutcome(
        result_status=_split_status(half_outcomes),
        payout=round_payout(unrounded),
        payout_unrounded=unrounded,
    )


def _handicap_half(home_goals_90: int, away_goals_90: int, handicap: Decimal) -> _HalfOutcome:
    adjusted = Decimal(home_goals_90 - away_goals_90) + handicap
    if adjusted > 0:
        return _HalfOutcome.WIN
    if adjusted < 0:
        return _HalfOutcome.LOSE
    return _HalfOutcome.PUSH


def _total_half(selection: Side, total_goals: int, line: Decimal) -> _HalfOutcome:
    if total_goals == line:
        return _HalfOutcome.PUSH
    over_wins = total_goals > line
    if selection is Side.H:
        return _HalfOutcome.WIN if over_wins else _HalfOutcome.LOSE
    return _HalfOutcome.WIN if not over_wins else _HalfOutcome.LOSE


def settle_had(
    selection: Side,
    home_goals_90: int,
    away_goals_90: int,
    odds: Decimal,
    stake: Decimal,
) -> SettlementOutcome:
    _validate_common(odds, stake)
    _validate_goals(home_goals_90, away_goals_90)
    validate_side(MarketType.HAD, selection)
    if home_goals_90 > away_goals_90:
        winner = Side.H
    elif home_goals_90 < away_goals_90:
        winner = Side.A
    else:
        winner = Side.D
    result = _HalfOutcome.WIN if selection is winner else _HalfOutcome.LOSE
    return _build_outcome(stake, odds, (result,))


def settle_hdc(
    selection: Side,
    home_goals_90: int,
    away_goals_90: int,
    condition_raw: str,
    odds: Decimal,
    stake: Decimal,
) -> SettlementOutcome:
    _validate_common(odds, stake)
    _validate_goals(home_goals_90, away_goals_90)
    validate_side(MarketType.HDC, selection)
    try:
        halves = parse_condition_raw(condition_raw)
    except InvalidConditionRaw as exc:
        raise SettlementInputError(f"invalid HDC condition {condition_raw}") from exc
    outcomes: list[_HalfOutcome] = []
    for handicap in halves:
        home_outcome = _handicap_half(home_goals_90, away_goals_90, handicap)
        if selection is Side.H:
            outcomes.append(home_outcome)
        elif home_outcome is _HalfOutcome.WIN:
            outcomes.append(_HalfOutcome.LOSE)
        elif home_outcome is _HalfOutcome.LOSE:
            outcomes.append(_HalfOutcome.WIN)
        else:
            outcomes.append(_HalfOutcome.PUSH)
    return _build_outcome(stake, odds, tuple(outcomes))


def settle_hil(
    selection: Side,
    home_goals_90: int,
    away_goals_90: int,
    condition_raw: str,
    odds: Decimal,
    stake: Decimal,
) -> SettlementOutcome:
    _validate_common(odds, stake)
    _validate_goals(home_goals_90, away_goals_90)
    validate_side(MarketType.HIL, selection)
    try:
        halves = parse_condition_raw(condition_raw)
    except InvalidConditionRaw as exc:
        raise SettlementInputError(f"invalid HIL condition {condition_raw}") from exc
    if any(line < 0 for line in halves):
        raise SettlementInputError(f"HIL total line must be unsigned, got {condition_raw}")
    total_goals = home_goals_90 + away_goals_90
    outcomes = tuple(_total_half(selection, total_goals, line) for line in halves)
    return _build_outcome(stake, odds, outcomes)


def settle_void(stake: Decimal) -> SettlementOutcome:
    if stake <= Decimal("0"):
        raise SettlementInputError(f"stake must be positive, got {stake}")
    return SettlementOutcome(
        result_status=BetStatus.VOID,
        payout=round_payout(stake),
        payout_unrounded=stake,
        void_reason="hkjc_refund_pool",
    )


def settle_market(
    market: MarketType,
    selection: Side,
    home_goals_90: int,
    away_goals_90: int,
    condition_raw: str,
    odds: Decimal,
    stake: Decimal,
) -> SettlementOutcome:
    if market is MarketType.HAD:
        return settle_had(selection, home_goals_90, away_goals_90, odds, stake)
    if market is MarketType.HDC:
        return settle_hdc(selection, home_goals_90, away_goals_90, condition_raw, odds, stake)
    if market is MarketType.HIL:
        return settle_hil(selection, home_goals_90, away_goals_90, condition_raw, odds, stake)
    raise SettlementInputError(f"unsupported market {market}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/ledger/test_settlement.py -v`

Expected: `17 passed`.

- [ ] **Step 5: Commit**

```bash
git add packages/ledger tests/ledger/test_settlement.py
git commit -m "feat: add regulation-time settlement engine with split lines and rounding"
```

---

#### Task 3 v2.1 amendments

These amendments supersede the old Task 3 boundary behavior.

1. `MIN_ODDS` rejects only `odds < 1.01`; exactly `1.01` is valid.
2. HIL conditions must be unsigned. Reject any HIL `condition_raw` that starts with `+` or `-` before parsing.
3. Remove the non-discriminating `test_ucl_match_settles_on_ninety_minute_score_not_final`; the function only accepts 90-minute goals, so that test cannot distinguish final-score behavior. UCL result semantics are tested at the adapter/settlement integration gate with a captured match.
4. Add a cross-check test against `packages.payoff` in Task 3.5.

**Implementation delta for `packages/ledger/settlement.py`:**

```python
def _validate_common(odds: Decimal, stake: Decimal) -> None:
    if odds < MIN_ODDS:
        raise SettlementInputError(f"odds must be at least {MIN_ODDS}, got {odds}")
    if stake <= Decimal(0):
        raise SettlementInputError(f"stake must be positive, got {stake}")
```

In `settle_hil`, before `parse_condition_raw`:

```python
if condition_raw.strip().startswith(("+", "-")):
    raise SettlementInputError(f"HIL condition must be unsigned, got {condition_raw}")
```

**Required tests:**

```python
def test_odds_of_exactly_one_point_zero_one_is_allowed():
    outcome = settle_had(Side.H, 2, 1, D("1.01"), D("10.00"))
    assert outcome.result_status is BetStatus.WON


def test_hil_rejects_signed_condition():
    with pytest.raises(SettlementInputError):
        settle_hil(Side.H, 2, 1, "-0.5", D("1.90"), D("10.00"))
```

Run: `uv run pytest tests/ledger/test_settlement.py -v`
Expected: all settlement tests pass, including the two new boundary tests.

---

### Task 3.5: Shared Payoff Engine

**Files:**
- Create: `packages/payoff/__init__.py`
- Create: `packages/payoff/returns.py`
- Create: `packages/payoff/kelly.py`
- Test: `tests/payoff/test_returns.py`
- Test: `tests/payoff/test_kelly.py`

**Interfaces:**
- Consumes: `MarketType`, `Side`, `parse_condition_raw`, `validate_side`, `InvalidConditionRaw`.
- Produces: `ReturnOutcome` (`WIN`, `HALF_WIN_HALF_PUSH`, `PUSH`, `HALF_LOSE_HALF_PUSH`, `LOSS`); `ReturnDistribution = Mapping[ReturnOutcome, Decimal]`; `Score = tuple[int, int]`; `return_multiple(outcome, odds)`; `settle_return(market, selection, condition_raw, score, odds)`; `return_distribution(score_distribution, market, selection, condition_raw, odds)`; `expected_value(distribution, odds)`; `kelly_fraction(distribution, odds, max_fraction, tolerance)`.

- [ ] **Step 1: Write the failing payoff return tests**

Create `tests/payoff/test_returns.py`:

```python
from decimal import Decimal

import pytest

from packages.domain.enums import BetStatus, MarketType, Side
from packages.domain.errors import SettlementInputError
from packages.ledger.settlement import settle_market
from packages.payoff.returns import (
    ReturnOutcome,
    expected_value,
    return_distribution,
    return_multiple,
    settle_return,
)

D = Decimal

RETURN_TO_STATUS = {
    ReturnOutcome.WIN: BetStatus.WON,
    ReturnOutcome.HALF_WIN_HALF_PUSH: BetStatus.HALF_WON_HALF_PUSH,
    ReturnOutcome.PUSH: BetStatus.PUSH,
    ReturnOutcome.HALF_LOSE_HALF_PUSH: BetStatus.HALF_LOST_HALF_PUSH,
    ReturnOutcome.LOSS: BetStatus.LOST,
}


def test_return_multiple_values():
    assert return_multiple(ReturnOutcome.WIN, D("2.00")) == D("1.00")
    assert return_multiple(ReturnOutcome.HALF_WIN_HALF_PUSH, D("2.00")) == D("0.50")
    assert return_multiple(ReturnOutcome.PUSH, D("2.00")) == D("0.00")
    assert return_multiple(ReturnOutcome.HALF_LOSE_HALF_PUSH, D("2.00")) == D("-0.50")
    assert return_multiple(ReturnOutcome.LOSS, D("2.00")) == D("-1.00")


def test_had_distribution_matches_binary_ev():
    scores = {(2, 0): D("0.45"), (1, 1): D("0.30"), (0, 1): D("0.25")}
    distribution = return_distribution(scores, MarketType.HAD, Side.H, "0.0", D("2.00"))
    assert distribution[ReturnOutcome.WIN] == D("0.45")
    assert distribution[ReturnOutcome.LOSS] == D("0.55")
    assert expected_value(distribution, D("2.00")) == D("-0.10")
    binary = D("0.45") * (D("2.00") - D("1")) + D("0.55") * D("-1")
    assert expected_value(distribution, D("2.00")) == binary


def test_hdc_push_outcome():
    score = settle_return(MarketType.HDC, Side.H, "1.0", (2, 1), D("1.95"))
    assert score is ReturnOutcome.PUSH
    distribution = return_distribution(
        {(2, 1): D("1.0")},
        MarketType.HDC,
        Side.H,
        "1.0",
        D("1.95"),
    )
    assert distribution[ReturnOutcome.PUSH] == D("1.0")


def test_hdc_split_half_win_half_push():
    outcome = settle_return(MarketType.HDC, Side.H, "0.0/1.0", (2, 1), D("1.95"))
    assert outcome is ReturnOutcome.HALF_WIN_HALF_PUSH
    assert return_multiple(outcome, D("1.95")) == D("0.475")


def test_hil_split_outcomes():
    over = settle_return(MarketType.HIL, Side.H, "2.5/3.0", (2, 1), D("1.90"))
    under = settle_return(MarketType.HIL, Side.L, "2.5/3.0", (2, 1), D("1.90"))
    assert over is ReturnOutcome.HALF_WIN_HALF_PUSH
    assert under is ReturnOutcome.HALF_LOSE_HALF_PUSH


def test_distribution_sums_to_one():
    scores = {(2, 0): D("0.5"), (0, 0): D("0.5")}
    distribution = return_distribution(scores, MarketType.HIL, Side.H, "2.5", D("1.90"))
    assert sum(distribution.values(), D("0")) == D("1.0")


def test_impossible_outcome_is_exactly_zero():
    scores = {(2, 1): D("0.6"), (1, 0): D("0.4")}
    distribution = return_distribution(scores, MarketType.HDC, Side.H, "0.5", D("1.95"))
    assert distribution[ReturnOutcome.PUSH] == D("0")
    assert distribution[ReturnOutcome.HALF_WIN_HALF_PUSH] == D("0")


def test_signed_hil_condition_is_rejected():
    with pytest.raises(SettlementInputError):
        settle_return(MarketType.HIL, Side.H, "-0.5", (2, 1), D("1.90"))


def test_return_distribution_rejects_bad_total():
    with pytest.raises(SettlementInputError):
        return_distribution(
            {(1, 0): D("0.5")},
            MarketType.HAD,
            Side.H,
            "0.0",
            D("2.00"),
        )


@pytest.mark.parametrize(
    ("market", "selection", "condition", "score", "odds"),
    [
        (MarketType.HAD, Side.H, "0.0", (2, 1), "2.00"),
        (MarketType.HAD, Side.D, "0.0", (1, 1), "3.40"),
        (MarketType.HAD, Side.A, "0.0", (0, 1), "3.80"),
        (MarketType.HDC, Side.H, "1.0", (2, 1), "1.95"),
        (MarketType.HDC, Side.H, "0.0/1.0", (2, 1), "1.95"),
        (MarketType.HIL, Side.H, "2.5/3.0", (2, 1), "1.90"),
        (MarketType.HIL, Side.L, "2.5/3.0", (2, 1), "1.90"),
    ],
)
def test_settle_return_matches_settlement_engine(market, selection, condition, score, odds):
    decimal_odds = D(odds)
    payoff_outcome = settle_return(market, selection, condition, score, decimal_odds)
    settlement = settle_market(
        market,
        selection,
        score[0],
        score[1],
        condition,
        decimal_odds,
        D("10.00"),
    )
    assert settlement.result_status is RETURN_TO_STATUS[payoff_outcome]
```

- [ ] **Step 2: Run the return tests to verify they fail**

Run: `uv run pytest tests/payoff/test_returns.py -v`

Expected: collection error because `packages.payoff` does not exist.

- [ ] **Step 3: Implement return distributions**

Create `packages/payoff/__init__.py`:

```python
from packages.payoff.kelly import kelly_fraction
from packages.payoff.returns import (
    ReturnDistribution,
    ReturnOutcome,
    Score,
    expected_value,
    return_distribution,
    return_multiple,
    settle_return,
)

__all__ = [
    "ReturnDistribution",
    "ReturnOutcome",
    "Score",
    "expected_value",
    "kelly_fraction",
    "return_distribution",
    "return_multiple",
    "settle_return",
]
```

Create `packages/payoff/returns.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum

from packages.domain.enums import MarketType, Side
from packages.domain.errors import InvalidConditionRaw, SettlementInputError
from packages.domain.markets import parse_condition_raw, validate_side

MIN_ODDS = Decimal("1.01")
DISTRIBUTION_TOLERANCE = Decimal("1e-6")


class ReturnOutcome(StrEnum):
    WIN = "win"
    HALF_WIN_HALF_PUSH = "half_win_half_push"
    PUSH = "push"
    HALF_LOSE_HALF_PUSH = "half_lose_half_push"
    LOSS = "loss"


ReturnDistribution = Mapping[ReturnOutcome, Decimal]
Score = tuple[int, int]

RETURN_OUTCOMES = (
    ReturnOutcome.WIN,
    ReturnOutcome.HALF_WIN_HALF_PUSH,
    ReturnOutcome.PUSH,
    ReturnOutcome.HALF_LOSE_HALF_PUSH,
    ReturnOutcome.LOSS,
)


def _validate_odds(odds: Decimal) -> None:
    if odds < MIN_ODDS:
        raise SettlementInputError(f"odds must be at least {MIN_ODDS}, got {odds}")


def return_multiple(outcome: ReturnOutcome, odds: Decimal) -> Decimal:
    _validate_odds(odds)
    if outcome is ReturnOutcome.WIN:
        return odds - Decimal("1")
    if outcome is ReturnOutcome.HALF_WIN_HALF_PUSH:
        return (odds - Decimal("1")) / Decimal("2")
    if outcome is ReturnOutcome.PUSH:
        return Decimal("0")
    if outcome is ReturnOutcome.HALF_LOSE_HALF_PUSH:
        return Decimal("-0.5")
    if outcome is ReturnOutcome.LOSS:
        return Decimal("-1")
    raise SettlementInputError(f"unsupported return outcome {outcome}")


def _invert(outcome: ReturnOutcome) -> ReturnOutcome:
    if outcome is ReturnOutcome.WIN:
        return ReturnOutcome.LOSS
    if outcome is ReturnOutcome.LOSS:
        return ReturnOutcome.WIN
    return ReturnOutcome.PUSH


def _combine(outcomes: tuple[ReturnOutcome, ...]) -> ReturnOutcome:
    if len(outcomes) == 1:
        return outcomes[0]
    if len(outcomes) != 2:
        raise SettlementInputError("split lines must contain exactly two halves")
    pair = tuple(sorted(outcomes, key=lambda item: item.value))
    if pair == (ReturnOutcome.WIN, ReturnOutcome.WIN):
        return ReturnOutcome.WIN
    if pair == (ReturnOutcome.LOSS, ReturnOutcome.LOSS):
        return ReturnOutcome.LOSS
    if pair == (ReturnOutcome.PUSH, ReturnOutcome.PUSH):
        return ReturnOutcome.PUSH
    if pair == (ReturnOutcome.PUSH, ReturnOutcome.WIN):
        return ReturnOutcome.HALF_WIN_HALF_PUSH
    if pair == (ReturnOutcome.LOSS, ReturnOutcome.PUSH):
        return ReturnOutcome.HALF_LOSE_HALF_PUSH
    raise SettlementInputError(f"split line produced unsupported pair {pair}")


def settle_return(
    market: MarketType,
    selection: Side,
    condition_raw: str,
    score: Score,
    odds: Decimal,
) -> ReturnOutcome:
    _validate_odds(odds)
    home_goals, away_goals = score
    if home_goals < 0 or away_goals < 0:
        raise SettlementInputError("goals cannot be negative")
    validate_side(market, selection)
    if market is MarketType.HAD:
        if home_goals > away_goals:
            winner = Side.H
        elif home_goals < away_goals:
            winner = Side.A
        else:
            winner = Side.D
        return ReturnOutcome.WIN if selection is winner else ReturnOutcome.LOSS
    try:
        halves = parse_condition_raw(condition_raw)
    except InvalidConditionRaw as exc:
        raise SettlementInputError(f"invalid condition {condition_raw}") from exc
    if market is MarketType.HIL and any(line < 0 for line in halves):
        raise SettlementInputError(f"HIL total line must be unsigned, got {condition_raw}")
    outcomes: list[ReturnOutcome] = []
    if market is MarketType.HDC:
        for handicap in halves:
            adjusted = Decimal(home_goals - away_goals) + handicap
            home_outcome = (
                ReturnOutcome.WIN
                if adjusted > 0
                else ReturnOutcome.LOSS
                if adjusted < 0
                else ReturnOutcome.PUSH
            )
            outcomes.append(home_outcome if selection is Side.H else _invert(home_outcome))
    elif market is MarketType.HIL:
        total_goals = home_goals + away_goals
        for line in halves:
            if total_goals == line:
                outcomes.append(ReturnOutcome.PUSH)
            else:
                over_wins = total_goals > line
                selection_wins = (selection is Side.H and over_wins) or (
                    selection is Side.L and not over_wins
                )
                outcomes.append(
                    ReturnOutcome.WIN if selection_wins else ReturnOutcome.LOSS
                )
    else:
        raise SettlementInputError(f"unsupported market {market}")
    return _combine(tuple(outcomes))


def return_distribution(
    score_distribution: Mapping[Score, Decimal],
    market: MarketType,
    selection: Side,
    condition_raw: str,
    odds: Decimal,
) -> ReturnDistribution:
    if not score_distribution:
        raise SettlementInputError("score distribution cannot be empty")
    total = sum(score_distribution.values(), Decimal("0"))
    if abs(total - Decimal("1")) > DISTRIBUTION_TOLERANCE:
        raise SettlementInputError(f"score distribution must sum to 1, got {total}")
    distribution = {outcome: Decimal("0") for outcome in RETURN_OUTCOMES}
    for score, probability in score_distribution.items():
        if probability < 0:
            raise SettlementInputError("probabilities cannot be negative")
        outcome = settle_return(market, selection, condition_raw, score, odds)
        distribution[outcome] += probability
    return distribution


def expected_value(distribution: ReturnDistribution, odds: Decimal) -> Decimal:
    return sum(
        (
            probability * return_multiple(outcome, odds)
            for outcome, probability in distribution.items()
        ),
        Decimal("0"),
    )
```

- [ ] **Step 4: Write the failing Kelly tests**

Create `tests/payoff/test_kelly.py`:

```python
from decimal import Decimal

from packages.domain.enums import MarketType, Side
from packages.payoff.kelly import kelly_fraction
from packages.payoff.returns import ReturnOutcome, return_distribution

D = Decimal


def test_kelly_is_zero_at_zero_edge():
    distribution = {ReturnOutcome.WIN: D("0.5"), ReturnOutcome.LOSS: D("0.5")}
    assert kelly_fraction(distribution, D("2.00"), D("0.99")) == D("0")


def test_kelly_is_positive_for_known_positive_edge():
    distribution = {ReturnOutcome.WIN: D("0.6"), ReturnOutcome.LOSS: D("0.4")}
    fraction = kelly_fraction(distribution, D("2.00"), D("0.99"))
    assert abs(fraction - D("0.2")) < D("0.001")


def test_kelly_never_exceeds_max_fraction():
    distribution = {ReturnOutcome.WIN: D("0.9"), ReturnOutcome.LOSS: D("0.1")}
    fraction = kelly_fraction(distribution, D("3.00"), D("0.25"))
    assert fraction <= D("0.25")
    assert fraction > D("0")


def test_negative_edge_returns_zero():
    distribution = {ReturnOutcome.WIN: D("0.4"), ReturnOutcome.LOSS: D("0.6")}
    assert kelly_fraction(distribution, D("2.00"), D("0.99")) == D("0")


def test_had_matches_binary_closed_form():
    probability = D("0.6")
    odds = D("2.00")
    distribution = {
        ReturnOutcome.WIN: probability,
        ReturnOutcome.LOSS: D("1") - probability,
    }
    closed_form = (probability * (odds - D("1")) - (D("1") - probability)) / (
        odds - D("1")
    )
    fraction = kelly_fraction(distribution, odds, D("0.99"))
    assert abs(fraction - closed_form) < D("0.001")


def test_hdc_split_distribution_gets_positive_kelly():
    scores = {(1, 0): D("0.6"), (0, 0): D("0.4")}
    distribution = return_distribution(scores, MarketType.HDC, Side.H, "0.5", D("2.00"))
    fraction = kelly_fraction(distribution, D("2.00"), D("0.99"))
    assert fraction > D("0")
    assert fraction <= D("0.99")
```

- [ ] **Step 5: Run the Kelly tests to verify they fail**

Run: `uv run pytest tests/payoff/test_kelly.py -v`

Expected: collection error because `packages.payoff.kelly` does not exist.

- [ ] **Step 6: Implement numerical Kelly**

Create `packages/payoff/kelly.py`:

```python
from __future__ import annotations

import math
from decimal import Decimal

from packages.payoff.returns import (
    ReturnDistribution,
    expected_value,
    return_multiple,
)

DEFAULT_MAX_FRACTION = Decimal("0.99")
DEFAULT_TOLERANCE = Decimal("1e-9")


def _objective(returns: list[tuple[float, float]], fraction: float) -> float:
    return sum(
        probability * math.log(1.0 + fraction * return_value)
        for probability, return_value in returns
    )


def kelly_fraction(
    distribution: ReturnDistribution,
    odds: Decimal,
    max_fraction: Decimal = DEFAULT_MAX_FRACTION,
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> Decimal:
    if max_fraction < Decimal("0") or max_fraction >= Decimal("1"):
        raise ValueError("max_fraction must be in [0, 1)")
    if expected_value(distribution, odds) <= Decimal("0"):
        return Decimal("0")
    returns = [
        (float(probability), float(return_multiple(outcome, odds)))
        for outcome, probability in distribution.items()
        if probability > 0
    ]
    if not returns:
        return Decimal("0")
    low = 0.0
    high = float(max_fraction)
    if high <= 0.0:
        return Decimal("0")
    for _ in range(160):
        third = (high - low) / 3.0
        left = low + third
        right = high - third
        if _objective(returns, left) < _objective(returns, right):
            low = left
        else:
            high = right
    fraction = Decimal(str((low + high) / 2.0))
    if fraction <= tolerance:
        return Decimal("0")
    return min(fraction, max_fraction)
```

- [ ] **Step 7: Run all payoff tests**

Run: `uv run pytest tests/payoff -v`

Expected: `22 passed`.

- [ ] **Step 8: Commit**

```bash
git add packages/payoff tests/payoff
git commit -m "feat: add shared payoff engine with return distributions and numerical kelly"
```

---

### Task 4: Database Schema, Models, and Migrations

**Files:**
- Create: `packages/db/__init__.py`
- Create: `packages/db/base.py`
- Create: `packages/db/session.py`
- Create: `packages/db/models/__init__.py`
- Create: `packages/db/models/catalog.py`
- Create: `packages/db/models/squads.py`
- Create: `packages/db/models/odds.py`
- Create: `packages/db/models/ledger.py`
- Create: `packages/db/models/sources.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `tests/conftest.py`
- Test: `tests/db/test_schema.py`

**Interfaces:**
- Consumes: domain enums from Task 2.
- Produces: `Base`, `build_engine(url)`, `build_session_factory(engine)`, `session_scope(factory)`, `enum_type(enum_cls, length)`, `json_type()`; ORM models `Competition`, `Team`, `Player`, `Match`, `Lineup`, `Availability`, `OddsSnapshot`, `MarketLine`, `PaperBet`, `Settlement`, `RawPayload`, `SourceFetchRun`.

- [ ] **Step 1: Write the failing schema tests**

Create `tests/conftest.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import packages.db.models  # noqa: F401
from packages.db.base import Base


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
```

Create `tests/db/test_schema.py`:

```python
from sqlalchemy import inspect

from packages.db.models import (
    Competition,
    Match,
    OddsSnapshot,
    PaperBet,
    Player,
    RawPayload,
    Settlement,
    Team,
    MarketLine,
)

PHASE1_TABLES = {
    "competitions",
    "teams",
    "players",
    "matches",
    "lineups",
    "availability",
    "odds_snapshots",
    "market_lines",
    "paper_bets",
    "settlements",
    "raw_payloads",
    "source_fetch_runs",
}


def test_phase1_tables_exist(engine):
    assert PHASE1_TABLES <= set(inspect(engine).get_table_names())


def test_match_keeps_regulation_and_final_scores_separate():
    columns = {column.name for column in Match.__table__.columns}
    assert {
        "home_goals_90",
        "away_goals_90",
        "home_goals_final",
        "away_goals_final",
    } <= columns


def test_provenance_columns_exist():
    raw_columns = {column.name for column in RawPayload.__table__.columns}
    assert {"source_name", "source_url", "fetched_at", "schema_version", "payload_hash"} <= raw_columns
    settlement_columns = {column.name for column in Settlement.__table__.columns}
    assert {"hk_result_ref", "provisional", "source"} <= settlement_columns


def test_paper_bet_has_three_layer_idempotency_keys():
    assert PaperBet.__table__.c.bet_intent_key.unique is True
    assert PaperBet.__table__.c.analysis_run_key.index is True
    assert PaperBet.__table__.c.decision_slot_key.index is True
    assert "decision_at" in {column.name for column in PaperBet.__table__.columns}


def test_odds_snapshot_and_market_line_links():
    assert OddsSnapshot.__table__.c.match_id.foreign_keys
    assert MarketLine.__table__.c.snapshot_id.foreign_keys
    assert Competition.__table__.c.code.unique is True
    assert Team.__table__.c.slug.unique is True
    assert Player.__table__.c.fotmob_id.unique is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/db/test_schema.py -v`

Expected: collection error because `packages.db` does not exist.

- [ ] **Step 3: Create the database base and session helpers**

Create `packages/db/__init__.py` as an empty file.

Create `packages/db/base.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TypeVar

from sqlalchemy import DateTime, JSON, MetaData, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

EnumT = TypeVar("EnumT", bound=Enum)


def json_type() -> JSON:
    return JSON().with_variant(JSONB(astext_type="text"), "postgresql")


def enum_type(enum_cls: type[EnumT], length: int = 32) -> SAEnum:
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda members: [member.value for member in members],
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

Create `packages/db/session.py`:

```python
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def build_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, future=True, connect_args=connect_args)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 4: Create the catalog models**

Create `packages/db/models/catalog.py`:

```python
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
    json_type,
)
from packages.domain.enums import MatchStatus


class Competition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitions"

    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(64), nullable=False)
    is_cup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    understat_slug: Mapped[str | None] = mapped_column(String(32))
    football_data_code: Mapped[str] = mapped_column(String(8), nullable=False)


class Team(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "teams"

    slug: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    short_name: Mapped[str] = mapped_column(String(48), nullable=False)
    country: Mapped[str] = mapped_column(String(64), nullable=False)
    understat_id: Mapped[str | None] = mapped_column(String(32))
    fotmob_id: Mapped[int | None] = mapped_column(Integer)
    football_data_id: Mapped[int | None] = mapped_column(Integer)


class Player(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "players"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL")
    )
    position: Mapped[str | None] = mapped_column(String(32))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    fotmob_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    understat_id: Mapped[str | None] = mapped_column(String(32))
    fpl_id: Mapped[int | None] = mapped_column(Integer, unique=True)


class Match(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint(
            "competition_id",
            "season",
            "home_team_id",
            "away_team_id",
            "kickoff_at",
            name="uq_matches_natural_key",
        ),
    )

    competition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitions.id", ondelete="RESTRICT"), nullable=False
    )
    season: Mapped[str] = mapped_column(String(9), nullable=False)
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    home_team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    away_team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[MatchStatus] = mapped_column(enum_type(MatchStatus, 24), nullable=False)
    matchday: Mapped[int | None] = mapped_column(Integer)
    home_goals_90: Mapped[int | None] = mapped_column(Integer)
    away_goals_90: Mapped[int | None] = mapped_column(Integer)
    home_goals_final: Mapped[int | None] = mapped_column(Integer)
    away_goals_final: Mapped[int | None] = mapped_column(Integer)
    source_match_ids: Mapped[dict[str, str]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    coverage_flags: Mapped[list[str]] = mapped_column(
        json_type(), default=list, nullable=False
    )
```

- [ ] **Step 5: Create the squad models**

Create `packages/db/models/squads.py`:

```python
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
    json_type,
)
from packages.domain.enums import AvailabilityStatus, LineupType


class Lineup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lineups"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "team_id",
            "lineup_type",
            "source",
            name="uq_lineups_match_team_type_source",
        ),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    lineup_type: Mapped[LineupType] = mapped_column(
        enum_type(LineupType, 16), nullable=False
    )
    formation: Mapped[str | None] = mapped_column(String(16))
    starters: Mapped[list[dict]] = mapped_column(json_type(), default=list, nullable=False)
    subs: Mapped[list[dict]] = mapped_column(json_type(), default=list, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(512))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Availability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "availability"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "team_id",
            "player_id",
            "source",
            name="uq_availability_match_team_player_source",
        ),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    player_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL")
    )
    status: Mapped[AvailabilityStatus] = mapped_column(
        enum_type(AvailabilityStatus, 16), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(256))
    expected_return: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(512))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 6: Create the odds models**

Create `packages/db/models/odds.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
)
from packages.domain.enums import MarketType, Side, SnapshotKind


class OddsSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "odds_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "market",
            "snapshot_kind",
            "snapshot_at",
            name="uq_odds_snapshots_match_market_kind_at",
        ),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    market: Mapped[MarketType] = mapped_column(enum_type(MarketType, 16), nullable=False)
    snapshot_kind: Mapped[SnapshotKind] = mapped_column(
        enum_type(SnapshotKind, 16), nullable=False
    )
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    query_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("raw_payloads.id", ondelete="SET NULL")
    )
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)


class MarketLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "market_lines"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "condition_raw",
            "side",
            name="uq_market_lines_snapshot_condition_side",
        ),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("odds_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    odds_type: Mapped[MarketType] = mapped_column(
        enum_type(MarketType, 16), nullable=False
    )
    condition_raw: Mapped[str] = mapped_column(String(24), nullable=False)
    line_index: Mapped[int] = mapped_column(Integer, nullable=False)
    side: Mapped[Side] = mapped_column(enum_type(Side, 8), nullable=False)
    odds_decimal: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    pool_status: Mapped[str] = mapped_column(String(32), nullable=False)
    line_status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_main: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    offer_early_settlement: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    source_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 7: Create the ledger models**

Create `packages/db/models/ledger.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
)
from packages.domain.enums import BetStatus, MarketType, SettlementSource, Side


class PaperBet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paper_bets"

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="RESTRICT"), nullable=False
    )
    market: Mapped[MarketType] = mapped_column(enum_type(MarketType, 16), nullable=False)
    line_key: Mapped[str] = mapped_column(String(24), nullable=False)
    selection: Mapped[Side] = mapped_column(enum_type(Side, 8), nullable=False)
    odds_decimal: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    stake: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    bankroll_before: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    odds_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("odds_snapshots.id", ondelete="SET NULL")
    )
    closing_odds_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("odds_snapshots.id", ondelete="SET NULL")
    )
    status: Mapped[BetStatus] = mapped_column(enum_type(BetStatus, 32), nullable=False)
    analysis_run_key: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
    decision_slot_key: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
    bet_intent_key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Settlement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "settlements"

    paper_bet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper_bets.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    result_status: Mapped[BetStatus] = mapped_column(
        enum_type(BetStatus, 32), nullable=False
    )
    payout: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payout_unrounded: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    clv: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    brier_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hk_result_ref: Mapped[str | None] = mapped_column(String(128))
    provisional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[SettlementSource] = mapped_column(
        enum_type(SettlementSource, 32), nullable=False
    )
```

- [ ] **Step 8: Create the source provenance models**

Create `packages/db/models/sources.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
    json_type,
)
from packages.domain.enums import FetchRunStatus


class RawPayload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "raw_payloads"

    source_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    body: Mapped[dict] = mapped_column(json_type(), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(64))
    http_status: Mapped[int | None] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(String(64))


class SourceFetchRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_fetch_runs"

    run_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[FetchRunStatus] = mapped_column(
        enum_type(FetchRunStatus, 16), nullable=False
    )
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(String(1024))
    params: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
```

- [ ] **Step 9: Export all models**

Create `packages/db/models/__init__.py`:

```python
from packages.db.models.catalog import Competition, Match, Player, Team
from packages.db.models.ledger import PaperBet, Settlement
from packages.db.models.odds import MarketLine, OddsSnapshot
from packages.db.models.sources import RawPayload, SourceFetchRun
from packages.db.models.squads import Availability, Lineup

__all__ = [
    "Availability",
    "Competition",
    "Lineup",
    "MarketLine",
    "Match",
    "OddsSnapshot",
    "PaperBet",
    "Player",
    "RawPayload",
    "Settlement",
    "SourceFetchRun",
    "Team",
]
```

- [ ] **Step 10: Configure Alembic**

Create `alembic.ini`:

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
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

Create `alembic/env.py`:

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import packages.db.models  # noqa: F401
from packages.db.base import Base
from packages.shared.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    return configured or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url().replace("%", "%%")
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Create `alembic/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
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

- [ ] **Step 11: Run the schema tests**

Run: `uv run pytest tests/db/test_schema.py -v`

Expected: `5 passed`.

- [ ] **Step 12: Generate and apply the initial migration**

Run: `docker compose up -d postgres`

Expected: Postgres is running and healthy.

Run: `uv run alembic revision --autogenerate -m "phase1 foundation schema"`

Expected: Alembic writes a new file under `alembic/versions/` and prints `Generating ... done`.

Run: `uv run alembic upgrade head`

Expected: Alembic prints `Running upgrade -> <revision>, phase1 foundation schema`.

Run: `docker compose exec postgres psql -U football -d football_pred -c "\dt"`

Expected: the table list includes `competitions`, `matches`, `odds_snapshots`, `market_lines`, `paper_bets`, `settlements`, `raw_payloads`, and `source_fetch_runs`.

- [ ] **Step 13: Verify the migration round trip on a disposable database**

Run: `docker compose exec postgres psql -U football -d postgres -c "CREATE DATABASE football_pred_test;"`

Expected: `CREATE DATABASE`.

Run: `FP_DATABASE_URL=postgresql+psycopg://football:football@localhost:5432/football_pred_test uv run alembic upgrade head`

Expected: migration applies with no error.

Run: `FP_DATABASE_URL=postgresql+psycopg://football:football@localhost:5432/football_pred_test uv run alembic downgrade base`

Expected: all Phase 1 tables are dropped with no error.

- [ ] **Step 14: Commit**

```bash
git add packages/db alembic alembic.ini tests/conftest.py tests/db/test_schema.py
git commit -m "feat: add phase 1 database schema and alembic migration"
```

---

#### Task 4 v2.1 amendments

These steps are mandatory. They add the temporal, news, and bankroll schema required by G1.

- [ ] **Step 15: Add the v2.1 enums**

Append to `packages/domain/enums.py`:

```python
class AvailabilityBasis(StrEnum):
    OBSERVED_SNAPSHOT = "observed_snapshot"
    PROVIDER_POINT_IN_TIME = "provider_point_in_time"
    AVAILABILITY_ASSUMED = "availability_assumed"
    UNAVAILABLE = "unavailable"


class SourceStatus(StrEnum):
    VERIFIED = "verified"
    CONDITIONAL = "conditional"
    BLOCKED = "blocked"


class UclCoverageLevel(StrEnum):
    FULL = "full"
    REDUCED = "reduced_coverage"
    INSUFFICIENT = "insufficient_coverage"


class ReservationStatus(StrEnum):
    HELD = "held"
    COMMITTED = "committed"
    RELEASED = "released"
```

- [ ] **Step 16: Add temporal fields to existing models**

Modify `packages/db/models/catalog.py`. Change the enum import to:

```python
from packages.domain.enums import AvailabilityBasis, MatchStatus
```

Add these columns to `Match` after `kickoff_at`:

```python
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

Add these columns to `Match` after `away_goals_final`:

```python
    result_available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_availability_basis: Mapped[AvailabilityBasis | None] = mapped_column(
        enum_type(AvailabilityBasis, 32)
    )
    result_evidence_grade: Mapped[AvailabilityBasis | None] = mapped_column(
        enum_type(AvailabilityBasis, 32)
    )
```

Modify `packages/db/models/squads.py`. Change the enum import to:

```python
from packages.domain.enums import AvailabilityBasis, AvailabilityStatus, LineupType
```

Add these columns to both `Lineup` and `Availability`:

```python
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability_basis: Mapped[AvailabilityBasis | None] = mapped_column(
        enum_type(AvailabilityBasis, 32)
    )
    evidence_grade: Mapped[AvailabilityBasis | None] = mapped_column(
        enum_type(AvailabilityBasis, 32)
    )
```

Modify `packages/db/models/odds.py`. Change the enum import to:

```python
from packages.domain.enums import AvailabilityBasis, MarketType, Side, SnapshotKind
```

Add these columns to `MarketLine` after `source_update_at`:

```python
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability_basis: Mapped[AvailabilityBasis | None] = mapped_column(
        enum_type(AvailabilityBasis, 32)
    )
```

Modify `packages/db/models/sources.py`. Change imports to:

```python
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
    json_type,
)
from packages.domain.enums import FetchRunStatus, SourceStatus
```

Add these columns to `SourceFetchRun` after `params`:

```python
    source_status: Mapped[SourceStatus] = mapped_column(
        enum_type(SourceStatus, 16), default=SourceStatus.CONDITIONAL, nullable=False
    )
    verification_date: Mapped[date | None] = mapped_column(Date)
    schema_scope: Mapped[str | None] = mapped_column(String(256))
    field_scope: Mapped[str | None] = mapped_column(String(256))
    test_evidence_ref: Mapped[str | None] = mapped_column(String(512))
    licensing_check: Mapped[str | None] = mapped_column(String(512))
```

- [ ] **Step 17: Add news and bankroll models**

Create `packages/db/models/news.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
)
from packages.domain.enums import AvailabilityBasis


class NewsSignal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "news_signals"

    source_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability_basis: Mapped[AvailabilityBasis] = mapped_column(
        enum_type(AvailabilityBasis, 32), nullable=False
    )
    evidence_grade: Mapped[AvailabilityBasis] = mapped_column(
        enum_type(AvailabilityBasis, 32), nullable=False
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
```

Append to `packages/db/models/ledger.py`:

```python
class BankrollAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bankroll_accounts"

    account_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    bankroll_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    reserved_stake: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )


class BankrollReservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bankroll_reservations"

    bet_intent_key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        enum_type(ReservationStatus, 16), nullable=False
    )
```

Change the ledger enum import to:

```python
from packages.domain.enums import (
    BetStatus,
    MarketType,
    ReservationStatus,
    SettlementSource,
    Side,
)
```

- [ ] **Step 18: Export the new models**

Modify `packages/db/models/__init__.py` to:

```python
from packages.db.models.catalog import Competition, Match, Player, Team
from packages.db.models.ledger import (
    BankrollAccount,
    BankrollReservation,
    PaperBet,
    Settlement,
)
from packages.db.models.news import NewsSignal
from packages.db.models.odds import MarketLine, OddsSnapshot
from packages.db.models.sources import RawPayload, SourceFetchRun
from packages.db.models.squads import Availability, Lineup

__all__ = [
    "Availability",
    "BankrollAccount",
    "BankrollReservation",
    "Competition",
    "Lineup",
    "MarketLine",
    "Match",
    "NewsSignal",
    "OddsSnapshot",
    "PaperBet",
    "Player",
    "RawPayload",
    "Settlement",
    "SourceFetchRun",
    "Team",
]
```

- [ ] **Step 19: Add schema tests and run them**

Modify `tests/db/test_schema.py` so `PHASE1_TABLES` also contains:

```python
    "bankroll_accounts",
    "bankroll_reservations",
    "news_signals",
```

Add these imports to the model import block:

```python
    BankrollAccount,
    BankrollReservation,
    Lineup,
    Availability,
    NewsSignal,
    SourceFetchRun,
```

Append these tests:

```python
def test_v21_temporal_fields_present():
    assert {"event_time", "first_seen_at", "result_available_at"} <= {
        column.name for column in Match.__table__.columns
    }
    assert {"available_at", "availability_basis", "evidence_grade"} <= {
        column.name for column in Lineup.__table__.columns
    }
    assert {"available_at", "availability_basis", "evidence_grade"} <= {
        column.name for column in Availability.__table__.columns
    }
    assert {"available_at", "availability_basis"} <= {
        column.name for column in NewsSignal.__table__.columns
    }


def test_source_verification_fields_present():
    assert {
        "source_status",
        "verification_date",
        "schema_scope",
        "field_scope",
        "test_evidence_ref",
        "licensing_check",
    } <= {column.name for column in SourceFetchRun.__table__.columns}


def test_bankroll_tables_have_required_columns():
    assert {"bankroll_balance", "reserved_stake"} <= {
        column.name for column in BankrollAccount.__table__.columns
    }
    assert {"bet_intent_key", "amount", "status"} <= {
        column.name for column in BankrollReservation.__table__.columns
    }
    assert BankrollReservation.__table__.c.bet_intent_key.unique is True
```

Run: `uv run pytest tests/db/test_schema.py -v`

Expected: `8 passed`.

- [ ] **Step 20: Generate the v2.1 migration**

Run: `uv run alembic revision --autogenerate -m "v2.1 temporal news bankroll"`

Expected: Alembic writes a second migration file under `alembic/versions/` and prints `Generating ... done`.

Run: `uv run alembic upgrade head`

Expected: Alembic prints `Running upgrade <previous_revision> -> <new_revision>, v2.1 temporal news bankroll`.

Run: `docker compose exec postgres psql -U football -d football_pred -c "\dt"`

Expected: the table list includes `bankroll_accounts`, `bankroll_reservations`, and `news_signals`.

- [ ] **Step 21: Commit**

```bash
git add packages/domain/enums.py packages/db tests/db/test_schema.py alembic/versions
git commit -m "feat: add v2.1 temporal, news, and bankroll schema"
```

---

### Task 5: Adapter Base and football-data.org Adapter

**Files:**
- Create: `packages/adapters/__init__.py`
- Create: `packages/adapters/base.py`
- Create: `packages/adapters/football_data_org.py`
- Test: `tests/adapters/test_football_data_org.py`

**Interfaces:**
- Consumes: `MatchStatus`, `parse_iso_utc`, `utc_now`.
- Produces: `BaseAdapter`, `FetchResult`, `AdapterError`, `AdapterHTTPError`, `AdapterSchemaError`, `AdapterRateLimitedError`, `CoverageGapError`, `MinIntervalRateLimiter`, `hash_text(raw_text)`; `FootballDataOrgAdapter`, `FootballDataMatch`, `StandingRow`, `COMPETITION_CODE_MAP`.

- [ ] **Step 1: Write the failing adapter tests**

Create `tests/adapters/test_football_data_org.py`:

```python
import httpx
import respx

from packages.adapters.base import MinIntervalRateLimiter, hash_text
from packages.adapters.football_data_org import FootballDataOrgAdapter
from packages.domain.enums import MatchStatus

MATCHES_PAYLOAD = {
    "competition": {"code": "PL"},
    "filters": {"season": "2025"},
    "matches": [
        {
            "id": 1001,
            "utcDate": "2026-08-15T14:00:00Z",
            "status": "FINISHED",
            "matchday": 1,
            "homeTeam": {"id": 10, "name": "Arsenal"},
            "awayTeam": {"id": 20, "name": "Chelsea"},
            "score": {
                "duration": "REGULAR",
                "fullTime": {"home": 2, "away": 1},
                "halfTime": {"home": 1, "away": 0},
            },
        },
        {
            "id": 1002,
            "utcDate": "2026-08-19T19:00:00Z",
            "status": "FINISHED",
            "matchday": 2,
            "homeTeam": {"id": 30, "name": "Real Madrid"},
            "awayTeam": {"id": 40, "name": "Bayern Munich"},
            "score": {
                "duration": "EXTRA_TIME",
                "fullTime": {"home": 3, "away": 2},
                "halfTime": {"home": 1, "away": 1},
            },
        },
    ],
}

STANDINGS_PAYLOAD = {
    "standings": [
        {
            "table": [
                {
                    "position": 1,
                    "team": {"id": 10, "name": "Arsenal"},
                    "playedGames": 1,
                    "won": 1,
                    "draw": 0,
                    "lost": 0,
                    "goalsFor": 2,
                    "goalsAgainst": 1,
                    "points": 3,
                }
            ]
        }
    ]
}

NO_LIMIT = MinIntervalRateLimiter(0.0)


@respx.mock
def test_fetch_matches_sends_api_key_and_returns_provenance():
    route = respx.get("https://api.football-data.org/v4/competitions/PL/matches").mock(
        return_value=httpx.Response(200, json=MATCHES_PAYLOAD)
    )
    adapter = FootballDataOrgAdapter(api_key="secret", limiter=NO_LIMIT)
    try:
        result = adapter.fetch_matches("EPL", 2025)
    finally:
        adapter.close()
    assert result.payload_hash == hash_text(result.raw_text)
    assert route.calls[0].request.headers["X-Auth-Token"] == "secret"
    assert route.calls[0].request.url.params["season"] == "2025"
    assert result.source_name == "football-data.org"


def test_parse_matches_keeps_regulation_and_final_scores_separate():
    matches = FootballDataOrgAdapter.parse_matches(MATCHES_PAYLOAD)
    regular = matches[0]
    extra_time = matches[1]
    assert regular.home_goals_90 == 2
    assert regular.away_goals_90 == 1
    assert regular.home_goals_final == 2
    assert regular.status is MatchStatus.FINISHED
    assert extra_time.home_goals_90 is None
    assert extra_time.away_goals_90 is None
    assert extra_time.home_goals_final == 3
    assert extra_time.away_goals_final == 2


def test_parse_standings():
    rows = FootballDataOrgAdapter.parse_standings(STANDINGS_PAYLOAD)
    assert len(rows) == 1
    assert rows[0].team_name == "Arsenal"
    assert rows[0].points == 3


@respx.mock
def test_fetch_standings_uses_competition_code():
    route = respx.get("https://api.football-data.org/v4/competitions/CL/standings").mock(
        return_value=httpx.Response(200, json=STANDINGS_PAYLOAD)
    )
    adapter = FootballDataOrgAdapter(api_key="secret", limiter=NO_LIMIT)
    try:
        result = adapter.fetch_standings("UCL", 2025)
    finally:
        adapter.close()
    assert result.http_status == 200
    assert route.called
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/adapters/test_football_data_org.py -v`

Expected: collection error because `packages.adapters` does not exist.

- [ ] **Step 3: Implement the adapter base**

Create `packages/adapters/__init__.py` as an empty file.

Create `packages/adapters/base.py`:

```python
from __future__ import annotations

import hashlib
import time
from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from packages.shared.time import utc_now


class AdapterError(Exception):
    """Base class for source adapter failures."""


class AdapterHTTPError(AdapterError):
    pass


class AdapterSchemaError(AdapterError):
    pass


class AdapterRateLimitedError(AdapterError):
    pass


class CoverageGapError(AdapterError):
    pass


def hash_text(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


class MinIntervalRateLimiter:
    def __init__(
        self,
        min_interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval = min_interval_seconds
        self._clock = clock
        self._last_at: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_at is not None:
            remaining = self._min_interval - (now - self._last_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_at = self._clock()


@dataclass(frozen=True)
class FetchResult:
    source_name: str
    source_url: str
    fetched_at: datetime
    http_status: int
    payload: Any
    payload_hash: str
    raw_text: str


class BaseAdapter(ABC):
    name = "base"
    tos_risk = "low"
    schema_version = "v1"
    default_headers = {"User-Agent": "football-pred/0.1 (personal research)"}

    def __init__(
        self,
        client: httpx.Client | None = None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=20.0,
            headers=self.default_headers,
        )
        self._owns_client = client is None
        self._limiter = limiter

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "BaseAdapter":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._limiter is not None:
            self._limiter.wait()
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise AdapterHTTPError(f"{method} {url} failed: {exc}") from exc
        if response.status_code == 429:
            raise AdapterRateLimitedError(f"{method} {url} returned 429")
        if response.status_code >= 400:
            raise AdapterHTTPError(f"{method} {url} returned {response.status_code}")
        return response

    def _get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        response = self._request("GET", url, params=params, headers=headers)
        text = response.text
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterSchemaError(f"{url} did not return JSON") from exc
        return FetchResult(
            source_name=self.name,
            source_url=str(response.request.url),
            fetched_at=utc_now(),
            http_status=response.status_code,
            payload=payload,
            payload_hash=hash_text(text),
            raw_text=text,
        )

    def _get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        response = self._request("GET", url, params=params, headers=headers)
        text = response.text
        return FetchResult(
            source_name=self.name,
            source_url=str(response.request.url),
            fetched_at=utc_now(),
            http_status=response.status_code,
            payload=text,
            payload_hash=hash_text(text),
            raw_text=text,
        )

    def _post_json(
        self,
        url: str,
        *,
        json_body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        response = self._request("POST", url, json=json_body, headers=headers)
        text = response.text
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterSchemaError(f"{url} did not return JSON") from exc
        return FetchResult(
            source_name=self.name,
            source_url=str(response.request.url),
            fetched_at=utc_now(),
            http_status=response.status_code,
            payload=payload,
            payload_hash=hash_text(text),
            raw_text=text,
        )
```

- [ ] **Step 4: Implement the football-data.org adapter**

Create `packages/adapters/football_data_org.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
)
from packages.domain.enums import MatchStatus
from packages.shared.time import parse_iso_utc

COMPETITION_CODE_MAP = {
    "EPL": "PL",
    "LALIGA": "PD",
    "BUNDESLIGA": "BL1",
    "SERIEA": "SA",
    "LIGUE1": "FL1",
    "UCL": "CL",
}

_STATUS_MAP = {
    "SCHEDULED": MatchStatus.SCHEDULED,
    "TIMED": MatchStatus.SCHEDULED,
    "IN_PLAY": MatchStatus.LIVE,
    "PAUSED": MatchStatus.LIVE,
    "FINISHED": MatchStatus.FINISHED,
    "AWARDED": MatchStatus.FINISHED,
    "POSTPONED": MatchStatus.POSTPONED,
    "CANCELLED": MatchStatus.CANCELLED,
    "SUSPENDED": MatchStatus.CANCELLED,
}


@dataclass(frozen=True)
class FootballDataMatch:
    source_match_id: int
    competition_code: str
    season_start_year: int
    kickoff_at: datetime
    status: MatchStatus
    matchday: int | None
    home_team_source_id: int
    home_team_name: str
    away_team_source_id: int
    away_team_name: str
    home_goals_90: int | None
    away_goals_90: int | None
    home_goals_final: int | None
    away_goals_final: int | None


@dataclass(frozen=True)
class StandingRow:
    position: int
    team_source_id: int
    team_name: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points: int


class FootballDataOrgAdapter(BaseAdapter):
    name = "football-data.org"
    tos_risk = "low"
    schema_version = "v4"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.football-data.org/v4",
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else MinIntervalRateLimiter(6.0),
        )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"X-Auth-Token": self._api_key}

    def fetch_matches(
        self,
        competition_code: str,
        season_start_year: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> FetchResult:
        code = COMPETITION_CODE_MAP.get(competition_code)
        if code is None:
            raise AdapterSchemaError(f"unknown competition code {competition_code}")
        params = {"season": str(season_start_year)}
        if date_from is not None:
            params["dateFrom"] = date_from
        if date_to is not None:
            params["dateTo"] = date_to
        return self._get_json(
            f"{self._base_url}/competitions/{code}/matches",
            params=params,
            headers=self._headers(),
        )

    def fetch_standings(self, competition_code: str, season_start_year: int) -> FetchResult:
        code = COMPETITION_CODE_MAP.get(competition_code)
        if code is None:
            raise AdapterSchemaError(f"unknown competition code {competition_code}")
        return self._get_json(
            f"{self._base_url}/competitions/{code}/standings",
            params={"season": str(season_start_year)},
            headers=self._headers(),
        )

    @staticmethod
    def parse_matches(payload: dict) -> list[FootballDataMatch]:
        competition = (payload.get("competition") or {}).get("code")
        if not competition:
            raise AdapterSchemaError("missing competition.code")
        filters = payload.get("filters") or {}
        season = filters.get("season")
        if season is None:
            raise AdapterSchemaError("missing filters.season")
        season_start = int(season)
        parsed: list[FootballDataMatch] = []
        for row in payload.get("matches") or []:
            score = row.get("score") or {}
            duration = score.get("duration") or "REGULAR"
            full_time = score.get("fullTime") or {}
            home_final = full_time.get("home")
            away_final = full_time.get("away")
            if duration == "REGULAR":
                home_90 = home_final
                away_90 = away_final
            else:
                home_90 = None
                away_90 = None
            kickoff = parse_iso_utc(row.get("utcDate"))
            if kickoff is None:
                raise AdapterSchemaError("missing utcDate")
            raw_status = str(row.get("status") or "SCHEDULED").upper()
            parsed.append(
                FootballDataMatch(
                    source_match_id=int(row["id"]),
                    competition_code=competition,
                    season_start_year=season_start,
                    kickoff_at=kickoff,
                    status=_STATUS_MAP.get(raw_status, MatchStatus.SCHEDULED),
                    matchday=row.get("matchday"),
                    home_team_source_id=int(row["homeTeam"]["id"]),
                    home_team_name=str(row["homeTeam"]["name"]),
                    away_team_source_id=int(row["awayTeam"]["id"]),
                    away_team_name=str(row["awayTeam"]["name"]),
                    home_goals_90=home_90,
                    away_goals_90=away_90,
                    home_goals_final=home_final,
                    away_goals_final=away_final,
                )
            )
        return parsed

    @staticmethod
    def parse_standings(payload: dict) -> list[StandingRow]:
        standings = payload.get("standings") or []
        if not standings:
            raise AdapterSchemaError("missing standings")
        rows: list[StandingRow] = []
        for entry in standings[0].get("table") or []:
            team = entry.get("team") or {}
            rows.append(
                StandingRow(
                    position=int(entry["position"]),
                    team_source_id=int(team["id"]),
                    team_name=str(team["name"]),
                    played=int(entry.get("playedGames") or 0),
                    won=int(entry.get("won") or 0),
                    drawn=int(entry.get("draw") or 0),
                    lost=int(entry.get("lost") or 0),
                    goals_for=int(entry.get("goalsFor") or 0),
                    goals_against=int(entry.get("goalsAgainst") or 0),
                    points=int(entry.get("points") or 0),
                )
            )
        return rows
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/adapters/test_football_data_org.py -v`

Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
git add packages/adapters tests/adapters/test_football_data_org.py
git commit -m "feat: add adapter base and football-data.org adapter"
```

---

### Task 6: Understat Adapter

**Files:**
- Create: `packages/adapters/understat.py`
- Test: `tests/adapters/test_understat.py`

**Interfaces:**
- Consumes: `BaseAdapter`, `FetchResult`, `MinIntervalRateLimiter`, `CoverageGapError`, `AdapterSchemaError`.
- Produces: `UnderstatAdapter`, `UnderstatTeamSeason`, `LEAGUE_SLUGS`.

- [ ] **Step 1: Write the failing Understat tests**

Create `tests/adapters/test_understat.py`:

```python
import json
from decimal import Decimal

import httpx
import pytest
import respx

from packages.adapters.base import CoverageGapError, MinIntervalRateLimiter
from packages.adapters.understat import UnderstatAdapter

TEAMS_PAYLOAD = {
    "1": {
        "id": "1",
        "title": "Arsenal",
        "history": [
            {
                "xG": "2.10",
                "xGA": "0.80",
                "npxG": "1.90",
                "scored": 2,
                "deep": 12,
                "ppda": {"att": 8.5, "def": 13.2},
            },
            {
                "xG": "1.40",
                "xGA": "1.20",
                "npxG": "1.30",
                "scored": 1,
                "deep": 9,
                "ppda": {"att": 9.5, "def": 12.0},
            },
        ],
    }
}

NO_LIMIT = MinIntervalRateLimiter(0.0)


def _encode_understat(payload: dict) -> str:
    return json.dumps(payload).replace('"', "\\x22")


def _league_html(payload: dict) -> str:
    return (
        "<html><script>"
        f"var teamsData = JSON.parse('{_encode_understat(payload)}');"
        "</script></html>"
    )


def test_parse_team_seasons_aggregates_history():
    rows = UnderstatAdapter.parse_team_seasons(_league_html(TEAMS_PAYLOAD))
    assert len(rows) == 1
    row = rows[0]
    assert row.team_name == "Arsenal"
    assert row.matches == 2
    assert row.goals == 3
    assert row.xg == Decimal("3.50")
    assert row.xga == Decimal("2.00")
    assert row.npxg == Decimal("3.20")
    assert row.ppda == Decimal("9.0")
    assert row.deep == 21


def test_ucl_is_a_coverage_gap_without_http_call():
    adapter = UnderstatAdapter(limiter=NO_LIMIT)
    try:
        with pytest.raises(CoverageGapError):
            adapter.fetch_league("UCL", 2025)
    finally:
        adapter.close()


@respx.mock
def test_fetch_league_uses_competition_slug():
    route = respx.get("https://understat.com/league/La_liga/2025").mock(
        return_value=httpx.Response(200, text=_league_html(TEAMS_PAYLOAD))
    )
    adapter = UnderstatAdapter(limiter=NO_LIMIT)
    try:
        result = adapter.fetch_league("LALIGA", 2025)
    finally:
        adapter.close()
    assert route.called
    assert result.source_name == "understat"
    assert "teamsData" in result.raw_text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/adapters/test_understat.py -v`

Expected: collection error because `packages.adapters.understat` does not exist.

- [ ] **Step 3: Implement the Understat adapter**

Create `packages/adapters/understat.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    CoverageGapError,
    FetchResult,
    MinIntervalRateLimiter,
)

LEAGUE_SLUGS = {
    "EPL": "EPL",
    "LALIGA": "La_liga",
    "BUNDESLIGA": "Bundesliga",
    "SERIEA": "Serie_A",
    "LIGUE1": "Ligue_1",
}

_JS_ESCAPE = re.compile(r"\\x[0-9a-fA-F]{2}|\\u[0-9a-fA-F]{4}|\\.", re.S)


def _decode_js_string(raw: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("\\x"):
            return chr(int(token[2:], 16))
        if token.startswith("\\u"):
            return chr(int(token[2:], 16))
        mapping = {"\\'": "'", '\\"': '"', "\\\\": "\\", "\\n": "\n", "\\t": "\t"}
        return mapping.get(token, token)

    return _JS_ESCAPE.sub(replace, raw)


def _extract_js_payload(html: str, variable: str) -> dict:
    pattern = re.compile(
        rf"var\s+{re.escape(variable)}\s*=\s*JSON\.parse\('(.*?)'\);",
        re.S,
    )
    match = pattern.search(html)
    if match is None:
        raise AdapterSchemaError(f"missing {variable} payload")
    decoded = _decode_js_string(match.group(1))
    try:
        return json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise AdapterSchemaError(f"invalid {variable} JSON") from exc


@dataclass(frozen=True)
class UnderstatTeamSeason:
    understat_team_id: str
    team_name: str
    matches: int
    goals: int
    xg: Decimal
    xga: Decimal
    npxg: Decimal
    ppda: Decimal
    deep: int


class UnderstatAdapter(BaseAdapter):
    name = "understat"
    tos_risk = "medium"
    schema_version = "html-v1"

    def __init__(
        self,
        base_url: str = "https://understat.com",
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else MinIntervalRateLimiter(30.0),
        )
        self._base_url = base_url.rstrip("/")

    def fetch_league(self, competition_code: str, season_start_year: int) -> FetchResult:
        slug = LEAGUE_SLUGS.get(competition_code)
        if slug is None:
            raise CoverageGapError(f"understat has no coverage for {competition_code}")
        return self._get_text(f"{self._base_url}/league/{slug}/{season_start_year}")

    @staticmethod
    def parse_team_seasons(html: str) -> list[UnderstatTeamSeason]:
        teams = _extract_js_payload(html, "teamsData")
        rows: list[UnderstatTeamSeason] = []
        for team in teams.values():
            history = team.get("history") or []
            if not history:
                continue
            xg = sum(
                (Decimal(str(entry.get("xG") or 0)) for entry in history),
                Decimal("0"),
            )
            xga = sum(
                (Decimal(str(entry.get("xGA") or 0)) for entry in history),
                Decimal("0"),
            )
            npxg = sum(
                (Decimal(str(entry.get("npxG") or 0)) for entry in history),
                Decimal("0"),
            )
            goals = sum(int(entry.get("scored") or 0) for entry in history)
            deep = sum(int(entry.get("deep") or 0) for entry in history)
            ppda_values = [
                Decimal(str(entry["ppda"]["att"]))
                for entry in history
                if entry.get("ppda") and entry["ppda"].get("att") is not None
            ]
            ppda = (
                sum(ppda_values, Decimal("0")) / Decimal(len(ppda_values))
                if ppda_values
                else Decimal("0")
            )
            rows.append(
                UnderstatTeamSeason(
                    understat_team_id=str(team.get("id")),
                    team_name=str(team.get("title")),
                    matches=len(history),
                    goals=goals,
                    xg=xg,
                    xga=xga,
                    npxg=npxg,
                    ppda=ppda,
                    deep=deep,
                )
            )
        return rows
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/adapters/test_understat.py -v`

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add packages/adapters/understat.py tests/adapters/test_understat.py
git commit -m "feat: add understat league adapter with ucl coverage gap"
```

---

### Task 7: FotMob, PL pulselive, and FPL Adapters

**Files:**
- Create: `packages/adapters/fotmob.py`
- Create: `packages/adapters/pl_pulselive.py`
- Create: `packages/adapters/fpl.py`
- Test: `tests/adapters/test_fotmob.py`
- Test: `tests/adapters/test_pl_fpl.py`

**Interfaces:**
- Consumes: `BaseAdapter`, `FetchResult`, `AdapterSchemaError`, `MinIntervalRateLimiter`, `LineupType`, `AvailabilityStatus`.
- Produces: `LineupPlayer`, `LineupDTO`, `UnavailableDTO`, `FotMobAdapter`; `PlPulseliveAdapter`; `FplPlayerStatus`, `FplAdapter`.

- [ ] **Step 1: Write the failing FotMob tests**

Create `tests/adapters/test_fotmob.py`:

```python
from datetime import date

import pytest

from packages.adapters.base import AdapterSchemaError, MinIntervalRateLimiter
from packages.adapters.fotmob import FotMobAdapter
from packages.domain.enums import AvailabilityStatus, LineupType

FOTMOB_PAYLOAD = {
    "content": {
        "lineup": {
            "homeTeam": {
                "formation": "4-3-3",
                "starters": [{"id": 1, "name": "Home GK", "position": "GK"}],
                "subs": [{"id": 2, "name": "Home Sub", "position": "DF"}],
            },
            "awayTeam": {
                "formation": "4-2-3-1",
                "starters": [{"id": 3, "name": "Away GK", "position": "GK"}],
                "subs": [],
            },
        },
        "unavailable": {
            "homeTeam": [
                {
                    "id": 9,
                    "name": "Injured Player",
                    "type": "injury",
                    "reason": "Hamstring",
                    "expectedReturn": "2026-09-01",
                }
            ],
            "awayTeam": [
                {
                    "id": 10,
                    "name": "Banned Player",
                    "type": "suspension",
                    "reason": "Red card",
                }
            ],
        },
    }
}

NO_LIMIT = MinIntervalRateLimiter(0.0)


def test_parse_predicted_lineup_marks_inferred():
    rows = FotMobAdapter.parse_lineups(FOTMOB_PAYLOAD, LineupType.PREDICTED)
    assert len(rows) == 2
    home = rows[0]
    assert home.team_side == "home"
    assert home.formation == "4-3-3"
    assert home.inferred is True
    assert home.starters[0].name == "Home GK"
    assert home.subs[0].source_player_id == 2


def test_parse_standard_lineup_is_not_inferred():
    rows = FotMobAdapter.parse_lineups(FOTMOB_PAYLOAD, LineupType.STANDARD)
    assert all(row.inferred is False for row in rows)
    assert all(row.lineup_type is LineupType.STANDARD for row in rows)


def test_parse_unavailable_maps_injury_and_suspension():
    rows = FotMobAdapter.parse_unavailable(FOTMOB_PAYLOAD)
    assert rows[0].status is AvailabilityStatus.INJURY
    assert rows[0].expected_return == date(2026, 9, 1)
    assert rows[1].status is AvailabilityStatus.SUSPENSION


def test_parse_lineup_rejects_missing_payload():
    with pytest.raises(AdapterSchemaError):
        FotMobAdapter.parse_lineups({"content": {}}, LineupType.STANDARD)


def test_adapter_metadata_is_high_tos_risk():
    adapter = FotMobAdapter(limiter=NO_LIMIT)
    try:
        assert adapter.tos_risk == "high"
        assert adapter.name == "fotmob"
    finally:
        adapter.close()
```

- [ ] **Step 2: Write the failing PL and FPL tests**

Create `tests/adapters/test_pl_fpl.py`:

```python
from packages.adapters.base import MinIntervalRateLimiter
from packages.adapters.fpl import FplAdapter
from packages.adapters.pl_pulselive import PlPulseliveAdapter
from packages.domain.enums import AvailabilityStatus, LineupType

PL_PAYLOAD = {
    "homeTeam": {
        "formation": "4-3-3",
        "startingXI": [{"id": 11, "name": "Home GK", "position": "GK"}],
        "substitutes": [{"id": 12, "name": "Home Sub", "position": "DF"}],
    },
    "awayTeam": {
        "formation": "3-4-3",
        "startingXI": [{"id": 21, "name": "Away GK", "position": "GK"}],
        "substitutes": [],
    },
}

FPL_PAYLOAD = {
    "teams": [{"id": 1, "name": "Arsenal"}],
    "elements": [
        {
            "id": 101,
            "web_name": "Saka",
            "team": 1,
            "status": "a",
            "news": "",
            "chance_of_playing_next_round": None,
        },
        {
            "id": 102,
            "web_name": "Injured",
            "team": 1,
            "status": "i",
            "news": "Knee injury",
            "chance_of_playing_next_round": 0,
        },
        {
            "id": 103,
            "web_name": "Banned",
            "team": 1,
            "status": "s",
            "news": "Suspended",
            "chance_of_playing_next_round": 0,
        },
    ],
}

NO_LIMIT = MinIntervalRateLimiter(0.0)


def test_pulselive_lineups_map_to_standard_dto():
    rows = PlPulseliveAdapter.parse_lineups(PL_PAYLOAD)
    assert len(rows) == 2
    assert rows[0].lineup_type is LineupType.STANDARD
    assert rows[0].starters[0].source_player_id == 11
    assert rows[0].subs[0].source_player_id == 12
    assert rows[1].formation == "3-4-3"


def test_fpl_availability_maps_known_statuses():
    rows = FplAdapter.parse_availability(FPL_PAYLOAD)
    assert rows[0].status is AvailabilityStatus.AVAILABLE
    assert rows[1].status is AvailabilityStatus.INJURY
    assert rows[1].news == "Knee injury"
    assert rows[2].status is AvailabilityStatus.SUSPENSION
    assert rows[1].team_name == "Arsenal"


def test_adapters_keep_low_tos_risk_metadata():
    pl = PlPulseliveAdapter(limiter=NO_LIMIT)
    fpl = FplAdapter(limiter=NO_LIMIT)
    try:
        assert pl.tos_risk == "low"
        assert fpl.tos_risk == "low"
    finally:
        pl.close()
        fpl.close()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/adapters/test_fotmob.py tests/adapters/test_pl_fpl.py -v`

Expected: collection errors because the adapter modules do not exist.

- [ ] **Step 4: Implement the FotMob adapter**

Create `packages/adapters/fotmob.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
)
from packages.domain.enums import AvailabilityStatus, LineupType

_UNAVAILABLE_STATUS = {
    "injury": AvailabilityStatus.INJURY,
    "suspension": AvailabilityStatus.SUSPENSION,
    "doubtful": AvailabilityStatus.DOUBTFUL,
    "available": AvailabilityStatus.AVAILABLE,
}


@dataclass(frozen=True)
class LineupPlayer:
    source_player_id: int
    name: str
    position: str | None


@dataclass(frozen=True)
class LineupDTO:
    team_side: str
    lineup_type: LineupType
    formation: str | None
    starters: tuple[LineupPlayer, ...]
    subs: tuple[LineupPlayer, ...]
    inferred: bool


@dataclass(frozen=True)
class UnavailableDTO:
    team_side: str
    source_player_id: int | None
    name: str
    status: AvailabilityStatus
    reason: str | None
    expected_return: date | None


def _lineup_player(raw: dict) -> LineupPlayer:
    return LineupPlayer(
        source_player_id=int(raw["id"]),
        name=str(raw.get("name") or ""),
        position=raw.get("position"),
    )


class FotMobAdapter(BaseAdapter):
    name = "fotmob"
    tos_risk = "high"
    schema_version = "api-v1"

    def __init__(
        self,
        base_url: str = "https://www.fotmob.com/api/data",
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else MinIntervalRateLimiter(600.0),
        )
        self._base_url = base_url.rstrip("/")

    def fetch_match_details(self, match_id: int) -> FetchResult:
        return self._get_json(
            f"{self._base_url}/matchDetails",
            params={"matchId": str(match_id)},
        )

    @staticmethod
    def parse_lineups(payload: dict, lineup_type: LineupType) -> list[LineupDTO]:
        lineup = (payload.get("content") or {}).get("lineup") or {}
        if not lineup:
            raise AdapterSchemaError("missing content.lineup")
        rows: list[LineupDTO] = []
        for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
            team = lineup.get(key) or {}
            starters = tuple(
                _lineup_player(raw) for raw in team.get("starters") or []
            )
            subs = tuple(_lineup_player(raw) for raw in team.get("subs") or [])
            rows.append(
                LineupDTO(
                    team_side=side,
                    lineup_type=lineup_type,
                    formation=team.get("formation"),
                    starters=starters,
                    subs=subs,
                    inferred=lineup_type is LineupType.PREDICTED,
                )
            )
        return rows

    @staticmethod
    def parse_unavailable(payload: dict) -> list[UnavailableDTO]:
        unavailable = (payload.get("content") or {}).get("unavailable") or {}
        rows: list[UnavailableDTO] = []
        for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
            for raw in unavailable.get(key) or []:
                raw_status = str(raw.get("type") or "").lower()
                status = _UNAVAILABLE_STATUS.get(raw_status)
                if status is None:
                    raise AdapterSchemaError(f"unknown unavailable type {raw_status}")
                expected = raw.get("expectedReturn")
                expected_return = date.fromisoformat(expected) if expected else None
                player_id = int(raw["id"]) if raw.get("id") is not None else None
                rows.append(
                    UnavailableDTO(
                        team_side=side,
                        source_player_id=player_id,
                        name=str(raw.get("name") or ""),
                        status=status,
                        reason=raw.get("reason"),
                        expected_return=expected_return,
                    )
                )
        return rows
```

- [ ] **Step 5: Implement the PL pulselive adapter**

Create `packages/adapters/pl_pulselive.py`:

```python
from __future__ import annotations

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
)
from packages.adapters.fotmob import LineupDTO, LineupPlayer
from packages.domain.enums import LineupType


class PlPulseliveAdapter(BaseAdapter):
    name = "pl-pulselive"
    tos_risk = "low"
    schema_version = "v1"

    def __init__(
        self,
        base_url: str = "https://footballapi.pulselive.com/football",
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else MinIntervalRateLimiter(10.0),
        )
        self._base_url = base_url.rstrip("/")

    def fetch_lineups(self, fixture_id: int) -> FetchResult:
        headers = {
            "Origin": "https://www.premierleague.com",
            "Referer": "https://www.premierleague.com/",
        }
        return self._get_json(
            f"{self._base_url}/fixtures/{fixture_id}/lineups",
            headers=headers,
        )

    @staticmethod
    def parse_lineups(payload: dict) -> list[LineupDTO]:
        rows: list[LineupDTO] = []
        for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
            team = payload.get(key) or {}
            if not team:
                raise AdapterSchemaError(f"missing {key}")
            starters = tuple(
                LineupPlayer(
                    source_player_id=int(raw["id"]),
                    name=str(raw.get("name") or ""),
                    position=raw.get("position"),
                )
                for raw in team.get("startingXI") or []
            )
            subs = tuple(
                LineupPlayer(
                    source_player_id=int(raw["id"]),
                    name=str(raw.get("name") or ""),
                    position=raw.get("position"),
                )
                for raw in team.get("substitutes") or []
            )
            rows.append(
                LineupDTO(
                    team_side=side,
                    lineup_type=LineupType.STANDARD,
                    formation=team.get("formation"),
                    starters=starters,
                    subs=subs,
                    inferred=False,
                )
            )
        return rows
```

- [ ] **Step 6: Implement the FPL adapter**

Create `packages/adapters/fpl.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from packages.adapters.base import (
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
)
from packages.domain.enums import AvailabilityStatus

_FPL_STATUS = {
    "a": AvailabilityStatus.AVAILABLE,
    "d": AvailabilityStatus.DOUBTFUL,
    "i": AvailabilityStatus.INJURY,
    "s": AvailabilityStatus.SUSPENSION,
    "u": AvailabilityStatus.DOUBTFUL,
}


@dataclass(frozen=True)
class FplPlayerStatus:
    fpl_id: int
    web_name: str
    team_name: str
    status: AvailabilityStatus
    news: str | None
    chance_of_playing: int | None


class FplAdapter(BaseAdapter):
    name = "fpl"
    tos_risk = "low"
    schema_version = "v1"

    def __init__(
        self,
        base_url: str = "https://fantasy.premierleague.com/api",
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else MinIntervalRateLimiter(10.0),
        )
        self._base_url = base_url.rstrip("/")

    def fetch_bootstrap(self) -> FetchResult:
        return self._get_json(f"{self._base_url}/bootstrap-static/")

    @staticmethod
    def parse_availability(payload: dict) -> list[FplPlayerStatus]:
        teams = {
            int(team["id"]): str(team.get("name") or "")
            for team in payload.get("teams") or []
        }
        rows: list[FplPlayerStatus] = []
        for element in payload.get("elements") or []:
            raw_status = str(element.get("status") or "u").lower()
            status = _FPL_STATUS.get(raw_status, AvailabilityStatus.DOUBTFUL)
            rows.append(
                FplPlayerStatus(
                    fpl_id=int(element["id"]),
                    web_name=str(element.get("web_name") or ""),
                    team_name=teams.get(int(element.get("team") or 0), ""),
                    status=status,
                    news=element.get("news") or None,
                    chance_of_playing=element.get("chance_of_playing_next_round"),
                )
            )
        return rows
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/adapters/test_fotmob.py tests/adapters/test_pl_fpl.py -v`

Expected: `8 passed`.

- [ ] **Step 8: Commit**

```bash
git add packages/adapters/fotmob.py packages/adapters/pl_pulselive.py packages/adapters/fpl.py tests/adapters/test_fotmob.py tests/adapters/test_pl_fpl.py
git commit -m "feat: add fotmob, pl pulselive, and fpl adapters"
```

---

### Task 8: HKJC GraphQL Adapter, Query Capture, and Verification Gates

**Files:**
- Create: `packages/adapters/hkjc_queries/__init__.py`
- Create: `packages/adapters/hkjc_queries/loader.py`
- Create: `packages/adapters/hkjc_queries/README.md`
- Create: `packages/adapters/hkjc.py`
- Create: `scripts/capture_hkjc_queries.py`
- Modify: `packages/shared/config.py`
- Modify: `tests/test_bootstrap.py`
- Test: `tests/adapters/test_hkjc.py`

**Interfaces:**
- Consumes: `BaseAdapter`, `FetchResult`, `AdapterSchemaError`, `MinIntervalRateLimiter`, `MarketType`, `Side`, `HkjcResultSemantics`, `parse_condition_raw`, `validate_side`, `InvalidConditionRaw`, `UnsupportedMarket`.
- Produces: `load_query(queries_dir, key)`, `HkjcQueryMissingError`, `HkjcWhitelistError`, `HkjcResultSemanticsUnverifiedError`, `HkjcMarketLine`, `HkjcOddsPayload`, `HkjcMatchResult`, `HkjcAdapter` with `fetch_market_odds`, `fetch_match_results`, `parse_market_odds`, `parse_match_results`, `goals_90_from_result`, `refunded_markets`, and public attributes `query_version`, `schema_version`.

- [ ] **Step 1: Write the failing HKJC tests**

Create `tests/adapters/test_hkjc.py`:

```python
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from packages.adapters.base import MinIntervalRateLimiter
from packages.adapters.hkjc import (
    HkjcAdapter,
    HkjcResultSemanticsUnverifiedError,
    HkjcWhitelistError,
)
from packages.adapters.hkjc_queries.loader import HkjcQueryMissingError, load_query
from packages.domain.enums import HkjcResultSemantics, MarketType, Side

HAD_PAYLOAD = {
    "data": {
        "match": {
            "id": "HK-1001",
            "poolInfo": [
                {
                    "poolCode": "HAD",
                    "status": "SELLINGSTARTED",
                    "updateAt": "2026-08-15T12:29:00Z",
                    "lines": [
                        {
                            "condition": "0.0",
                            "status": "AVAILABLE",
                            "isMain": True,
                            "offerEarlySettlement": False,
                            "updateAt": "2026-08-15T12:29:00Z",
                            "odds": [
                                {"side": "H", "currentOdds": "2.05"},
                                {"side": "D", "currentOdds": "3.40"},
                                {"side": "A", "currentOdds": "3.80"},
                            ],
                        }
                    ],
                }
            ],
        }
    }
}

HDC_PAYLOAD = {
    "data": {
        "match": {
            "id": "HK-1001",
            "poolInfo": [
                {
                    "poolCode": "HDC",
                    "status": "SELLINGSTARTED",
                    "updateAt": "2026-08-15T12:29:00Z",
                    "lines": [
                        {
                            "condition": "1.0/1.5",
                            "status": "AVAILABLE",
                            "isMain": True,
                            "odds": [
                                {"side": "H", "currentOdds": "1.95"},
                                {"side": "A", "currentOdds": "1.95"},
                            ],
                        },
                        {
                            "condition": "0.5",
                            "status": "SUSPENDED",
                            "isMain": False,
                            "odds": [
                                {"side": "H", "currentOdds": "1.90"},
                                {"side": "A", "currentOdds": "1.90"},
                            ],
                        },
                    ],
                }
            ],
        }
    }
}

RESULT_PAYLOAD = {
    "data": {
        "matchResult": {
            "id": "HK-1001",
            "payoutConfirmed": True,
            "homeResult": 2,
            "awayResult": 1,
            "payoutRefundPools": [{"poolCode": "HIL"}],
            "refundPools": ["HDC"],
            "updateAt": "2026-08-15T16:00:00Z",
        }
    }
}

NO_LIMIT = MinIntervalRateLimiter(0.0)


def _write_query(tmp_path: Path, key: str, filename: str) -> None:
    (tmp_path / filename).write_text(
        f"query {key}($matchId: String!) {{ match(id: $matchId) {{ id }} }}",
        encoding="utf-8",
    )


def test_query_loader_requires_captured_file(tmp_path):
    with pytest.raises(HkjcQueryMissingError):
        load_query(tmp_path, "HAD")
    _write_query(tmp_path, "HAD", "had.graphql")
    assert "query HAD" in load_query(tmp_path, "HAD")


def test_parse_had_odds_keeps_string_odds_as_decimal():
    payload = HkjcAdapter.parse_market_odds(HAD_PAYLOAD, MarketType.HAD)
    assert payload.pool_status == "SELLINGSTARTED"
    assert len(payload.lines) == 3
    home = next(line for line in payload.lines if line.side is Side.H)
    assert home.odds_decimal == Decimal("2.05")
    assert home.condition_raw == "0.0"
    assert home.is_main is True


def test_parse_hdc_preserves_split_line_and_filters_suspended_line():
    payload = HkjcAdapter.parse_market_odds(HDC_PAYLOAD, MarketType.HDC)
    assert len(payload.lines) == 2
    assert {line.condition_raw for line in payload.lines} == {"1.0/1.5"}
    assert all(line.line_status == "AVAILABLE" for line in payload.lines)


def test_pool_not_selling_returns_no_bettable_lines():
    payload = {
        "data": {
            "match": {
                "id": "HK-1001",
                "poolInfo": [
                    {
                        "poolCode": "HAD",
                        "status": "CLOSED",
                        "lines": [
                            {
                                "condition": "0.0",
                                "status": "AVAILABLE",
                                "odds": [{"side": "H", "currentOdds": "2.00"}],
                            }
                        ],
                    }
                ],
            }
        }
    }
    parsed = HkjcAdapter.parse_market_odds(payload, MarketType.HAD)
    assert parsed.pool_status == "CLOSED"
    assert parsed.lines == ()


def test_whitelist_error_is_explicit():
    payload = {"errors": [{"message": "not allowed", "extensions": {"code": "WHITELIST_ERROR"}}]}
    with pytest.raises(HkjcWhitelistError):
        HkjcAdapter.parse_market_odds(payload, MarketType.HAD)


def test_parse_results_reads_both_refund_shapes():
    result = HkjcAdapter.parse_match_results(RESULT_PAYLOAD)
    assert result.payout_confirmed is True
    assert result.raw_home_result == 2
    assert result.raw_away_result == 1
    assert result.refund_pool_codes == ("HDC", "HIL")
    assert HkjcAdapter.refunded_markets(result) == frozenset(
        {MarketType.HDC, MarketType.HIL}
    )


def test_ucl_result_semantics_gate_blocks_unverified_settlement():
    result = HkjcAdapter.parse_match_results(RESULT_PAYLOAD)
    with pytest.raises(HkjcResultSemanticsUnverifiedError):
        HkjcAdapter.goals_90_from_result(
            result,
            HkjcResultSemantics.UNVERIFIED,
            is_ucl=True,
        )
    assert HkjcAdapter.goals_90_from_result(
        result,
        HkjcResultSemantics.UNVERIFIED,
        is_ucl=False,
    ) == (2, 1)
    assert HkjcAdapter.goals_90_from_result(
        result,
        HkjcResultSemantics.REGULATION_TIME,
        is_ucl=True,
    ) == (2, 1)


@respx.mock
def test_fetch_market_odds_replays_captured_query(tmp_path):
    _write_query(tmp_path, "HAD", "had.graphql")
    route = respx.post("https://info.cld.hkjc.com/graphql/base/").mock(
        return_value=httpx.Response(200, json=HAD_PAYLOAD)
    )
    adapter = HkjcAdapter(
        queries_dir=tmp_path,
        query_version="test-v1",
        limiter=NO_LIMIT,
    )
    try:
        result = adapter.fetch_market_odds(MarketType.HAD, "HK-1001")
    finally:
        adapter.close()
    body = json.loads(route.calls[0].request.content)
    assert body["query"].startswith("query HAD")
    assert body["variables"]["oddsType"] == "HAD"
    assert result.source_name == "hkjc"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/adapters/test_hkjc.py -v`

Expected: collection error because `packages.adapters.hkjc` does not exist.

- [ ] **Step 3: Implement the query loader**

Create `packages/adapters/hkjc_queries/__init__.py` as an empty file.

Create `packages/adapters/hkjc_queries/loader.py`:

```python
from pathlib import Path

from packages.adapters.base import AdapterSchemaError

QUERY_FILES = {
    "HAD": "had.graphql",
    "HDC": "hdc.graphql",
    "HIL": "hil.graphql",
    "matchResults": "match_results.graphql",
}


class HkjcQueryMissingError(AdapterSchemaError):
    pass


def load_query(queries_dir: Path, key: str) -> str:
    filename = QUERY_FILES.get(key)
    if filename is None:
        raise KeyError(f"unknown HKJC query key {key}")
    path = Path(queries_dir) / filename
    if not path.is_file():
        raise HkjcQueryMissingError(f"missing captured query {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise HkjcQueryMissingError(f"empty captured query {path}")
    if not text.lstrip().startswith(("query", "mutation", "fragment")):
        raise HkjcQueryMissingError(f"captured query is not GraphQL: {path}")
    return text
```

- [ ] **Step 4: Implement the HKJC adapter**

Create `packages/adapters/hkjc.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
)
from packages.adapters.hkjc_queries.loader import load_query
from packages.domain.enums import HkjcResultSemantics, MarketType, Side
from packages.domain.errors import InvalidConditionRaw, UnsupportedMarket
from packages.domain.markets import parse_condition_raw, validate_side
from packages.shared.time import parse_iso_utc


class HkjcWhitelistError(AdapterSchemaError):
    pass


class HkjcResultSemanticsUnverifiedError(AdapterSchemaError):
    pass


@dataclass(frozen=True)
class HkjcMarketLine:
    odds_type: MarketType
    condition_raw: str
    line_index: int
    side: Side
    odds_decimal: Decimal
    pool_status: str
    line_status: str
    is_main: bool
    offer_early_settlement: bool
    source_update_at: datetime | None


@dataclass(frozen=True)
class HkjcOddsPayload:
    match_source_id: str
    pool_status: str
    lines: tuple[HkjcMarketLine, ...]
    source_update_at: datetime | None


@dataclass(frozen=True)
class HkjcMatchResult:
    match_source_id: str
    payout_confirmed: bool
    raw_home_result: int | None
    raw_away_result: int | None
    refund_pool_codes: tuple[str, ...]
    source_update_at: datetime | None


def _raise_on_graphql_errors(payload: dict) -> None:
    errors = payload.get("errors")
    if not errors:
        return
    first = errors[0] or {}
    code = (first.get("extensions") or {}).get("code")
    if code == "WHITELIST_ERROR":
        raise HkjcWhitelistError(f"HKJC rejected query: {first.get('message')}")
    raise AdapterSchemaError(f"HKJC GraphQL error: {first.get('message')}")


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _extract_refund_codes(raw: dict) -> tuple[str, ...]:
    codes: set[str] = set()
    for key in ("payoutRefundPools", "refundPools"):
        for item in raw.get(key) or []:
            if isinstance(item, str):
                codes.add(item)
            elif isinstance(item, dict):
                code = item.get("poolCode") or item.get("oddsType") or item.get("code")
                if code:
                    codes.add(str(code))
    return tuple(sorted(codes))


class HkjcAdapter(BaseAdapter):
    name = "hkjc"
    tos_risk = "medium"
    schema_version = "graphql-v1"

    def __init__(
        self,
        queries_dir: Path,
        query_version: str,
        graphql_url: str = "https://info.cld.hkjc.com/graphql/base/",
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else MinIntervalRateLimiter(60.0),
        )
        self._queries_dir = Path(queries_dir)
        self._graphql_url = graphql_url
        self.query_version = query_version

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Origin": "https://bet.hkjc.com",
            "Referer": "https://bet.hkjc.com/football",
        }

    def fetch_market_odds(
        self,
        market: MarketType,
        match_source_id: str,
    ) -> FetchResult:
        query = load_query(self._queries_dir, market.value)
        body = {
            "operationName": None,
            "variables": {"matchId": match_source_id, "oddsType": market.value},
            "query": query,
        }
        return self._post_json(
            self._graphql_url,
            json_body=body,
            headers=self._headers(),
        )

    def fetch_match_results(self, match_source_id: str) -> FetchResult:
        query = load_query(self._queries_dir, "matchResults")
        body = {
            "operationName": None,
            "variables": {"matchId": match_source_id},
            "query": query,
        }
        return self._post_json(
            self._graphql_url,
            json_body=body,
            headers=self._headers(),
        )

    @staticmethod
    def parse_market_odds(
        payload: dict,
        expected_market: MarketType,
    ) -> HkjcOddsPayload:
        _raise_on_graphql_errors(payload)
        match = (payload.get("data") or {}).get("match") or {}
        if not match:
            raise AdapterSchemaError("missing data.match")
        pools = match.get("poolInfo") or []
        pool = next(
            (item for item in pools if item.get("poolCode") == expected_market.value),
            None,
        )
        if pool is None and len(pools) == 1:
            pool = pools[0]
        if pool is None:
            raise AdapterSchemaError(f"missing pool {expected_market.value}")
        pool_status = str(pool.get("status") or "UNKNOWN")
        pool_update = parse_iso_utc(pool.get("updateAt"))
        if pool_status != "SELLINGSTARTED":
            return HkjcOddsPayload(
                match_source_id=str(match.get("id") or ""),
                pool_status=pool_status,
                lines=(),
                source_update_at=pool_update,
            )
        lines: list[HkjcMarketLine] = []
        for index, raw_line in enumerate(pool.get("lines") or []):
            condition_raw = str(raw_line.get("condition") or "").strip()
            try:
                parse_condition_raw(condition_raw)
            except InvalidConditionRaw:
                continue
            line_status = str(raw_line.get("status") or "UNKNOWN")
            if line_status != "AVAILABLE":
                continue
            line_update = parse_iso_utc(raw_line.get("updateAt")) or pool_update
            for raw_odds in raw_line.get("odds") or []:
                try:
                    side = Side(str(raw_odds.get("side") or ""))
                except ValueError:
                    continue
                try:
                    validate_side(expected_market, side)
                except UnsupportedMarket:
                    continue
                odds = Decimal(str(raw_odds.get("currentOdds") or "0"))
                if odds <= Decimal("1"):
                    continue
                lines.append(
                    HkjcMarketLine(
                        odds_type=expected_market,
                        condition_raw=condition_raw,
                        line_index=index,
                        side=side,
                        odds_decimal=odds,
                        pool_status=pool_status,
                        line_status=line_status,
                        is_main=bool(raw_line.get("isMain")),
                        offer_early_settlement=bool(
                            raw_line.get("offerEarlySettlement")
                        ),
                        source_update_at=line_update,
                    )
                )
        return HkjcOddsPayload(
            match_source_id=str(match.get("id") or ""),
            pool_status=pool_status,
            lines=tuple(lines),
            source_update_at=pool_update,
        )

    @staticmethod
    def parse_match_results(payload: dict) -> HkjcMatchResult:
        _raise_on_graphql_errors(payload)
        data = payload.get("data") or {}
        raw = data.get("matchResult") or data.get("matchResults") or {}
        if isinstance(raw, list):
            if not raw:
                raise AdapterSchemaError("empty matchResults")
            raw = raw[0]
        if not raw:
            raise AdapterSchemaError("missing matchResult")
        return HkjcMatchResult(
            match_source_id=str(raw.get("id") or raw.get("matchId") or ""),
            payout_confirmed=bool(raw.get("payoutConfirmed")),
            raw_home_result=_int_or_none(raw.get("homeResult")),
            raw_away_result=_int_or_none(raw.get("awayResult")),
            refund_pool_codes=_extract_refund_codes(raw),
            source_update_at=parse_iso_utc(raw.get("updateAt")),
        )

    @staticmethod
    def goals_90_from_result(
        result: HkjcMatchResult,
        semantics: HkjcResultSemantics,
        *,
        is_ucl: bool,
    ) -> tuple[int, int] | None:
        if result.raw_home_result is None or result.raw_away_result is None:
            return None
        if is_ucl and semantics is HkjcResultSemantics.UNVERIFIED:
            raise HkjcResultSemanticsUnverifiedError(
                "UCL result semantics are unverified; do not settle UCL "
                "with homeResult and awayResult"
            )
        return result.raw_home_result, result.raw_away_result

    @staticmethod
    def refunded_markets(result: HkjcMatchResult) -> frozenset[MarketType]:
        markets: set[MarketType] = set()
        for code in result.refund_pool_codes:
            try:
                markets.add(MarketType(code))
            except ValueError:
                continue
        return frozenset(markets)
```

- [ ] **Step 5: Extend configuration for HKJC**

Modify `packages/shared/config.py` so the full file is:

```python
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from packages.domain.enums import HkjcResultSemantics


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FP_", extra="ignore")

    database_url: str = "postgresql+psycopg://football:football@localhost:5432/football_pred"
    redis_url: str = "redis://localhost:6379/0"
    football_data_org_api_key: str | None = None
    initial_bankroll: Decimal = Decimal("10000.00")
    fee_rate: Decimal = Decimal("0")
    http_timeout_seconds: float = 20.0
    hkjc_graphql_url: str = "https://info.cld.hkjc.com/graphql/base/"
    hkjc_queries_dir: Path = Path("packages/adapters/hkjc_queries")
    hkjc_query_version: str = "captured-2026-10"
    hkjc_result_semantics: HkjcResultSemantics = HkjcResultSemantics.UNVERIFIED


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Update `tests/test_bootstrap.py` by adding this import at the top:

```python
from packages.domain.enums import HkjcResultSemantics
```

Then add this assertion to `test_settings_defaults_without_env` after the `fee_rate` assertion:

```python
    assert settings.hkjc_result_semantics is HkjcResultSemantics.UNVERIFIED
```

- [ ] **Step 6: Add the capture script and queries README**

Create `scripts/capture_hkjc_queries.py`:

```python
"""Capture the official HKJC GraphQL query strings once, then store them as fixtures."""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

TARGET = "https://info.cld.hkjc.com/graphql/base/"
OUT = Path("packages/adapters/hkjc_queries")
MARKET_KEYS = ("HAD", "HDC", "HIL", "matchResults")
FILENAMES = {
    "HAD": "had.graphql",
    "HDC": "hdc.graphql",
    "HIL": "hil.graphql",
    "matchResults": "match_results.graphql",
}


def main() -> int:
    captured: dict[str, str] = {}

    def on_request(request) -> None:
        if request.url != TARGET or request.method != "POST":
            return
        body = request.post_data
        if not body:
            return
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            return
        query = decoded.get("query") or ""
        operation = decoded.get("operationName") or ""
        variables = json.dumps(decoded.get("variables") or {})
        haystack = f"{operation} {query} {variables}"
        for key in MARKET_KEYS:
            if key.lower() in haystack.lower() and key not in captured:
                captured[key] = query

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()
        page.on("request", on_request)
        page.goto("https://bet.hkjc.com/football", wait_until="domcontentloaded")
        input(
            "Open one football match with HAD, HDC and HIL odds, plus a finished "
            "result if available, then press Enter here."
        )
        browser.close()

    OUT.mkdir(parents=True, exist_ok=True)
    for key in MARKET_KEYS:
        if key not in captured:
            print(f"missing capture for {key}", file=sys.stderr)
            return 1
        path = OUT / FILENAMES[key]
        path.write_text(captured[key], encoding="utf-8")
        print(f"wrote {path} ({len(captured[key])} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `packages/adapters/hkjc_queries/README.md`:

```markdown
# HKJC captured GraphQL queries

HKJC accepts only query strings that its own website sends. These files are
captured from the official site once and replayed byte for byte.

## Capture procedure

1. Run `uv run playwright install chromium`.
2. Run `uv run python scripts/capture_hkjc_queries.py`.
3. In the opened browser, visit one football match that has HAD, HDC and HIL
   markets open. If a finished match is available, open its result page too.
4. Press Enter in the terminal. The script writes `had.graphql`, `hdc.graphql`,
   `hil.graphql`, and `match_results.graphql`.

## Rules

- Never hand write or edit these query strings. If HKJC changes its whitelist,
  re-run the capture and update `FP_HKJC_QUERY_VERSION`.
- Keep `FP_HKJC_RESULT_SEMANTICS` at `unverified` until a known UCL extra-time
  match has been checked against the live `matchResults` response.
- `payoutRefundPools` and `refundPools` have both appeared as strings and as
  objects. The adapter accepts both shapes. Re-run the capture if the live
  response uses a third shape.
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/adapters/test_hkjc.py tests/test_bootstrap.py -v`

Expected: `11 passed`.

- [ ] **Step 8: Capture the live queries and record the verification gates**

Run: `uv run playwright install chromium`

Expected: Chromium is installed for Playwright.

Run: `uv run python scripts/capture_hkjc_queries.py`

Expected: the script prints four `wrote packages/adapters/hkjc_queries/...` lines and exits with code 0.

Run: `uv run pytest tests/adapters/test_hkjc.py -v`

Expected: all HKJC contract tests still pass with the captured files present.

Before changing `FP_HKJC_RESULT_SEMANTICS`, complete both gates below and record the fixture evidence in `packages/adapters/hkjc_queries/README.md`.

Gate A, UCL result semantics: capture `matchResults` for one known UCL match that went to extra time. Compare `homeResult` and `awayResult` against the known 90-minute score and the known final score. Only set `FP_HKJC_RESULT_SEMANTICS=regulation_time` when the fields match the 90-minute score. Otherwise leave it unverified and UCL settlement stays blocked.

Gate B, refund shape: capture `matchResults` for one match with a refunded pool. Confirm whether `payoutRefundPools` and `refundPools` are strings, objects, or both. If neither matches the parser, add a new branch in `_extract_refund_codes` and a failing test first.

- [ ] **Step 9: Commit**

```bash
git add packages/adapters/hkjc.py packages/adapters/hkjc_queries scripts/capture_hkjc_queries.py packages/shared/config.py tests/test_bootstrap.py tests/adapters/test_hkjc.py
git commit -m "feat: add hkjc graphql adapter with captured query replay and result gates"
```

---

### Task 9: football-data.co.uk, RSS News, and Open-Meteo Adapters

**Files:**
- Create: `packages/adapters/football_data_co_uk.py`
- Create: `packages/adapters/rss_news.py`
- Create: `packages/adapters/open_meteo.py`
- Test: `tests/adapters/test_football_data_co_uk.py`
- Test: `tests/adapters/test_rss_weather.py`

**Interfaces:**
- Consumes: `BaseAdapter`, `FetchResult`, `AdapterSchemaError`, `CoverageGapError`, `MinIntervalRateLimiter`, `ensure_utc`, `parse_iso_utc`.
- Produces: `FootballDataCoUkAdapter`, `HistoricalMatchRow`, `LEAGUE_FILE_CODES`, `season_path(season_start_year)`; `RssNewsAdapter`, `NewsItem`; `OpenMeteoAdapter`, `WeatherPoint`, `WeatherSummary`.

- [ ] **Step 1: Write the failing football-data.co.uk tests**

Create `tests/adapters/test_football_data_co_uk.py`:

```python
from datetime import date, time
from decimal import Decimal

import httpx
import respx

from packages.adapters.base import MinIntervalRateLimiter
from packages.adapters.football_data_co_uk import (
    FootballDataCoUkAdapter,
    season_path,
)

CSV_TEXT = """Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,PSH,PSD,PSA
15/08/2026,14:00,Arsenal,Chelsea,2,1,H,2.05,3.40,3.80,2.10,3.50,3.90
16/08/2026,,Liverpool,Everton,0,0,D,2.20,3.30,3.50,,,
"""

NO_LIMIT = MinIntervalRateLimiter(0.0)


def test_season_path_uses_two_digit_years():
    assert season_path(2025) == "2526"


def test_parse_csv_reads_scores_and_odds_as_decimal():
    rows = FootballDataCoUkAdapter.parse_csv(CSV_TEXT, "EPL", 2025)
    assert len(rows) == 2
    first = rows[0]
    assert first.played_on == date(2026, 8, 15)
    assert first.kickoff_time == time(14, 0)
    assert first.home_goals_90 == 2
    assert first.away_goals_90 == 1
    assert first.result == "H"
    assert first.b365_home == Decimal("2.05")
    assert first.ps_away == Decimal("3.90")
    assert rows[1].kickoff_time is None
    assert rows[1].ps_home is None


@respx.mock
def test_fetch_league_csv_uses_expected_url():
    route = respx.get("https://www.football-data.co.uk/mmz4281/2526/E0.csv").mock(
        return_value=httpx.Response(200, text=CSV_TEXT)
    )
    adapter = FootballDataCoUkAdapter(limiter=NO_LIMIT)
    try:
        result = adapter.fetch_league_csv("EPL", 2025)
    finally:
        adapter.close()
    assert route.called
    assert result.source_name == "football-data.co.uk"
```

- [ ] **Step 2: Write the failing RSS and weather tests**

Create `tests/adapters/test_rss_weather.py`:

```python
from datetime import UTC, date, datetime
from decimal import Decimal

from packages.adapters.open_meteo import OpenMeteoAdapter
from packages.adapters.rss_news import RssNewsAdapter

RSS_TEXT = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Football</title>
    <item>
      <title>Team news</title>
      <link>https://example.test/a</link>
      <pubDate>Sat, 15 Aug 2026 10:00:00 GMT</pubDate>
      <description><![CDATA[<p>Hello <b>world</b></p>]]></description>
    </item>
    <item>
      <title>Second item</title>
      <link>https://example.test/b</link>
      <description>Plain text</description>
    </item>
  </channel>
</rss>
"""

WEATHER_PAYLOAD = {
    "hourly": {
        "time": [
            "2026-08-15T12:00",
            "2026-08-15T13:00",
            "2026-08-15T14:00",
        ],
        "temperature_2m": [21.5, 22.0, 22.5],
        "precipitation": [0.0, 0.2, 0.0],
        "wind_speed_10m": [10.0, 12.0, 8.0],
    }
}


def test_parse_rss_strips_html_and_reads_published_time():
    items = RssNewsAdapter.parse_feed(RSS_TEXT, "BBC")
    assert len(items) == 2
    assert items[0].title == "Team news"
    assert items[0].summary == "Hello world"
    assert items[0].published_at == datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
    assert items[1].published_at is None
    assert items[1].source_name == "BBC"


def test_parse_weather_hourly_returns_decimal_points():
    points = OpenMeteoAdapter.parse_hourly(WEATHER_PAYLOAD)
    assert len(points) == 3
    assert points[0].time_utc == datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    assert points[0].temperature_c == Decimal("21.5")
    assert points[1].precipitation_mm == Decimal("0.2")


def test_nearest_weather_point_uses_kickoff_window():
    points = OpenMeteoAdapter.parse_hourly(WEATHER_PAYLOAD)
    summary = OpenMeteoAdapter.nearest_to_kickoff(
        points,
        datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
    )
    assert summary is not None
    assert summary.delta_hours == 0.0
    assert summary.point.temperature_c == Decimal("22.5")
    missing = OpenMeteoAdapter.nearest_to_kickoff(
        points,
        datetime(2026, 8, 16, 14, 0, tzinfo=UTC),
    )
    assert missing is None
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/adapters/test_football_data_co_uk.py tests/adapters/test_rss_weather.py -v`

Expected: collection errors because the adapter modules do not exist.

- [ ] **Step 4: Implement the football-data.co.uk adapter**

Create `packages/adapters/football_data_co_uk.py`:

```python
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    CoverageGapError,
    FetchResult,
    MinIntervalRateLimiter,
)

LEAGUE_FILE_CODES = {
    "EPL": "E0",
    "LALIGA": "SP1",
    "BUNDESLIGA": "D1",
    "SERIEA": "I1",
    "LIGUE1": "F1",
}

BASE_URL = "https://www.football-data.co.uk/mmz4281"


def season_path(season_start_year: int) -> str:
    return f"{str(season_start_year)[2:]}{str(season_start_year + 1)[2:]}"


def _decimal_or_none(value: str | None) -> Decimal | None:
    if value is None or value.strip() == "":
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation as exc:
        raise AdapterSchemaError(f"invalid decimal {value}") from exc


def _time_or_none(value: str | None) -> time | None:
    if value is None or value.strip() == "":
        return None
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError as exc:
        raise AdapterSchemaError(f"invalid kickoff time {value}") from exc


@dataclass(frozen=True)
class HistoricalMatchRow:
    competition_code: str
    season_start_year: int
    played_on: date
    kickoff_time: time | None
    home_team: str
    away_team: str
    home_goals_90: int
    away_goals_90: int
    result: str
    b365_home: Decimal | None
    b365_draw: Decimal | None
    b365_away: Decimal | None
    ps_home: Decimal | None
    ps_draw: Decimal | None
    ps_away: Decimal | None


class FootballDataCoUkAdapter(BaseAdapter):
    name = "football-data.co.uk"
    tos_risk = "medium"
    schema_version = "csv-v1"

    def __init__(
        self,
        base_url: str = BASE_URL,
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else MinIntervalRateLimiter(10.0),
        )
        self._base_url = base_url.rstrip("/")

    def fetch_league_csv(
        self,
        competition_code: str,
        season_start_year: int,
    ) -> FetchResult:
        file_code = LEAGUE_FILE_CODES.get(competition_code)
        if file_code is None:
            raise CoverageGapError(
                f"football-data.co.uk has no file mapping for {competition_code}"
            )
        url = f"{self._base_url}/{season_path(season_start_year)}/{file_code}.csv"
        return self._get_text(url, headers={"Accept": "text/csv"})

    @staticmethod
    def parse_csv(
        text: str,
        competition_code: str,
        season_start_year: int,
    ) -> list[HistoricalMatchRow]:
        reader = csv.DictReader(io.StringIO(text))
        rows: list[HistoricalMatchRow] = []
        for raw in reader:
            played = (raw.get("Date") or "").strip()
            if not played:
                continue
            try:
                played_on = datetime.strptime(played, "%d/%m/%y").date()
            except ValueError as exc:
                raise AdapterSchemaError(f"invalid date {played}") from exc
            rows.append(
                HistoricalMatchRow(
                    competition_code=competition_code,
                    season_start_year=season_start_year,
                    played_on=played_on,
                    kickoff_time=_time_or_none(raw.get("Time")),
                    home_team=str(raw.get("HomeTeam") or "").strip(),
                    away_team=str(raw.get("AwayTeam") or "").strip(),
                    home_goals_90=int(raw["FTHG"]),
                    away_goals_90=int(raw["FTAG"]),
                    result=str(raw.get("FTR") or "").strip().upper(),
                    b365_home=_decimal_or_none(raw.get("B365H")),
                    b365_draw=_decimal_or_none(raw.get("B365D")),
                    b365_away=_decimal_or_none(raw.get("B365A")),
                    ps_home=_decimal_or_none(raw.get("PSH")),
                    ps_draw=_decimal_or_none(raw.get("PSD")),
                    ps_away=_decimal_or_none(raw.get("PSA")),
                )
            )
        return rows
```

- [ ] **Step 5: Implement the RSS news adapter**

Create `packages/adapters/rss_news.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser
from selectolax.parser import HTMLParser

from packages.adapters.base import (
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
)


@dataclass(frozen=True)
class NewsItem:
    source_name: str
    title: str
    link: str
    published_at: datetime | None
    summary: str


def _plain_text(html: str) -> str:
    if not html:
        return ""
    return HTMLParser(html).text(separator=" ", strip=True)


class RssNewsAdapter(BaseAdapter):
    name = "rss"
    tos_risk = "low"
    schema_version = "rss-v1"

    def __init__(
        self,
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else MinIntervalRateLimiter(900.0),
        )

    def fetch_feed(self, feed_url: str, source_name: str) -> FetchResult:
        return self._get_text(feed_url)

    @staticmethod
    def parse_feed(text: str, source_name: str) -> list[NewsItem]:
        parsed = feedparser.parse(text)
        rows: list[NewsItem] = []
        for entry in parsed.entries:
            published_at = None
            published_parsed = getattr(entry, "published_parsed", None)
            if published_parsed is not None:
                published_at = datetime(*published_parsed[:6], tzinfo=UTC)
            rows.append(
                NewsItem(
                    source_name=source_name,
                    title=str(getattr(entry, "title", "")),
                    link=str(getattr(entry, "link", "")),
                    published_at=published_at,
                    summary=_plain_text(str(getattr(entry, "summary", ""))),
                )
            )
        return rows
```

- [ ] **Step 6: Implement the Open-Meteo adapter**

Create `packages/adapters/open_meteo.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
)
from packages.shared.time import ensure_utc, parse_iso_utc


@dataclass(frozen=True)
class WeatherPoint:
    time_utc: datetime
    temperature_c: Decimal
    precipitation_mm: Decimal
    wind_speed_kmh: Decimal


@dataclass(frozen=True)
class WeatherSummary:
    point: WeatherPoint
    delta_hours: float


class OpenMeteoAdapter(BaseAdapter):
    name = "open-meteo"
    tos_risk = "low"
    schema_version = "v1"

    def __init__(
        self,
        base_url: str = "https://api.open-meteo.com/v1/forecast",
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(client=client, limiter=limiter)
        self._base_url = base_url

    def fetch_hourly(
        self,
        latitude: float,
        longitude: float,
        start_date: date,
        end_date: date,
    ) -> FetchResult:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m,precipitation,wind_speed_10m",
            "timezone": "UTC",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        return self._get_json(self._base_url, params=params)

    @staticmethod
    def parse_hourly(payload: dict) -> list[WeatherPoint]:
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        temps = hourly.get("temperature_2m") or []
        precip = hourly.get("precipitation") or []
        wind = hourly.get("wind_speed_10m") or []
        if not (len(times) == len(temps) == len(precip) == len(wind)):
            raise AdapterSchemaError("hourly arrays have different lengths")
        rows: list[WeatherPoint] = []
        for raw_time, temp, rain, speed in zip(times, temps, precip, wind):
            time_utc = parse_iso_utc(raw_time)
            if time_utc is None:
                raise AdapterSchemaError("missing hourly timestamp")
            rows.append(
                WeatherPoint(
                    time_utc=time_utc,
                    temperature_c=Decimal(str(temp)),
                    precipitation_mm=Decimal(str(rain)),
                    wind_speed_kmh=Decimal(str(speed)),
                )
            )
        return rows

    @staticmethod
    def nearest_to_kickoff(
        points: list[WeatherPoint],
        kickoff_at: datetime,
        max_delta_hours: float = 3.0,
    ) -> WeatherSummary | None:
        kickoff = ensure_utc(kickoff_at)
        best: WeatherPoint | None = None
        best_delta: float | None = None
        for point in points:
            delta = abs((point.time_utc - kickoff).total_seconds()) / 3600.0
            if best_delta is None or delta < best_delta:
                best = point
                best_delta = delta
        if best is None or best_delta is None or best_delta > max_delta_hours:
            return None
        return WeatherSummary(point=best, delta_hours=best_delta)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/adapters/test_football_data_co_uk.py tests/adapters/test_rss_weather.py -v`

Expected: `6 passed`.

- [ ] **Step 8: Commit**

```bash
git add packages/adapters/football_data_co_uk.py packages/adapters/rss_news.py packages/adapters/open_meteo.py tests/adapters/test_football_data_co_uk.py tests/adapters/test_rss_weather.py
git commit -m "feat: add historical csv, rss, and weather adapters"
```

---

### Task 10: Canonical Normalization and Data Quality Gate

**Files:**
- Create: `packages/ingest/__init__.py`
- Create: `packages/ingest/raw_store.py`
- Create: `packages/ingest/aliases.py`
- Create: `packages/ingest/normalize.py`
- Create: `packages/ingest/quality.py`
- Test: `tests/ingest/test_raw_store.py`
- Test: `tests/ingest/test_normalize.py`
- Test: `tests/ingest/test_quality.py`

**Interfaces:**
- Consumes: `FetchResult`, `FootballDataMatch`, `HkjcOddsPayload`, ORM models, domain enums, `resolve_team_id`.
- Produces: `persist_raw_payload(session, result, schema_version, run_id)`; `start_fetch_run(...)`, `finish_fetch_run(...)`; `canonical_team_slug(name)`, `resolve_team_id(session, name)`, `TEAM_ALIASES`; `seed_competitions(session)`, `get_competition(session, code)`, `season_label(year)`, `normalize_fixture(session, dto, competition_id)`, `upsert_match(session, fixture)`, `normalize_hkjc_snapshot(...)`; `QualityInput`, `QualityReport`, `evaluate_quality(input)`.

- [ ] **Step 1: Write the failing raw store tests**

Create `tests/ingest/test_raw_store.py`:

```python
from datetime import UTC, datetime

from packages.adapters.base import FetchResult, hash_text
from packages.ingest.raw_store import persist_raw_payload
from packages.shared.time import utc_now


def _result(payload) -> FetchResult:
    raw_text = str(payload)
    return FetchResult(
        source_name="test-source",
        source_url="https://example.test/data",
        fetched_at=utc_now(),
        http_status=200,
        payload=payload,
        payload_hash=hash_text(raw_text),
        raw_text=raw_text,
    )


def test_persist_raw_payload_keeps_provenance_and_json_body(session):
    result = _result({"hello": "world"})
    row = persist_raw_payload(
        session,
        result,
        schema_version="v1",
        run_id="run-1",
    )
    session.flush()
    assert row.source_name == "test-source"
    assert row.source_url == "https://example.test/data"
    assert row.schema_version == "v1"
    assert row.payload_hash == result.payload_hash
    assert row.body == {"hello": "world"}
    assert row.run_id == "run-1"


def test_persist_text_payload_wraps_text(session):
    result = _result("csv,text")
    row = persist_raw_payload(session, result, schema_version="csv-v1")
    session.flush()
    assert row.body == {"text": "csv,text"}
```

- [ ] **Step 2: Write the failing normalization tests**

Create `tests/ingest/test_normalize.py`:

```python
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from packages.adapters.football_data_org import FootballDataMatch
from packages.adapters.hkjc import HkjcAdapter
from packages.db.models import Competition, Match, MarketLine, OddsSnapshot, Team
from packages.domain.enums import (
    MarketType,
    MatchStatus,
    SnapshotKind,
)
from packages.domain.errors import UnresolvedTeamError
from packages.ingest.aliases import canonical_team_slug
from packages.ingest.normalize import (
    get_competition,
    normalize_fixture,
    normalize_hkjc_snapshot,
    season_label,
    seed_competitions,
    upsert_match,
)

HAD_PAYLOAD = {
    "data": {
        "match": {
            "id": "HK-1001",
            "poolInfo": [
                {
                    "poolCode": "HAD",
                    "status": "SELLINGSTARTED",
                    "updateAt": "2026-08-15T12:29:00Z",
                    "lines": [
                        {
                            "condition": "0.0",
                            "status": "AVAILABLE",
                            "isMain": True,
                            "odds": [
                                {"side": "H", "currentOdds": "2.05"},
                                {"side": "D", "currentOdds": "3.40"},
                                {"side": "A", "currentOdds": "3.80"},
                            ],
                        }
                    ],
                }
            ],
        }
    }
}


def _seed_teams(session):
    session.add_all(
        [
            Team(slug="arsenal", name="Arsenal", short_name="ARS", country="England"),
            Team(slug="chelsea", name="Chelsea", short_name="CHE", country="England"),
        ]
    )
    session.flush()


def test_seed_competitions_is_idempotent(session):
    seed_competitions(session)
    seed_competitions(session)
    count = session.query(Competition).count()
    assert count == 6


def test_canonical_team_slug_uses_alias_table():
    assert canonical_team_slug("Man City") == "manchester-city"
    assert canonical_team_slug("Paris SG") == "paris-saint-germain"
    assert canonical_team_slug("Some Team FC") == "some-team-fc"


def test_season_label_formats_start_and_end_years():
    assert season_label(2025) == "2025/26"


def test_normalize_and_upsert_fixture(session):
    seed_competitions(session)
    _seed_teams(session)
    competition = get_competition(session, "EPL")
    dto = FootballDataMatch(
        source_match_id=1001,
        competition_code="PL",
        season_start_year=2025,
        kickoff_at=datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
        status=MatchStatus.SCHEDULED,
        matchday=1,
        home_team_source_id=10,
        home_team_name="Arsenal",
        away_team_source_id=20,
        away_team_name="Chelsea",
        home_goals_90=None,
        away_goals_90=None,
        home_goals_final=None,
        away_goals_final=None,
    )
    fixture = normalize_fixture(session, dto, competition.id)
    match = upsert_match(session, fixture)
    assert match.season == "2025/26"
    assert match.source_match_ids == {"football-data.org": "1001"}
    again = upsert_match(session, fixture)
    assert again.id == match.id
    assert session.query(Match).count() == 1


def test_normalize_fixture_rejects_unknown_team(session):
    seed_competitions(session)
    competition = get_competition(session, "EPL")
    dto = FootballDataMatch(
        source_match_id=1002,
        competition_code="PL",
        season_start_year=2025,
        kickoff_at=datetime(2026, 8, 16, 14, 0, tzinfo=UTC),
        status=MatchStatus.SCHEDULED,
        matchday=1,
        home_team_source_id=10,
        home_team_name="Unknown FC",
        away_team_source_id=20,
        away_team_name="Chelsea",
        home_goals_90=None,
        away_goals_90=None,
        home_goals_final=None,
        away_goals_final=None,
    )
    with pytest.raises(UnresolvedTeamError):
        normalize_fixture(session, dto, competition.id)


def test_normalize_hkjc_snapshot_is_idempotent(session):
    match = Match(
        competition_id=uuid.uuid4(),
        season="2025/26",
        kickoff_at=datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
        home_team_id=uuid.uuid4(),
        away_team_id=uuid.uuid4(),
        status=MatchStatus.SCHEDULED,
        source_match_ids={"hkjc": "HK-1001"},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    parsed = HkjcAdapter.parse_market_odds(HAD_PAYLOAD, MarketType.HAD)
    snapshot, lines = normalize_hkjc_snapshot(
        session,
        match_id=match.id,
        market=MarketType.HAD,
        payload=parsed,
        snapshot_kind=SnapshotKind.T30M,
        snapshot_at=datetime(2026, 8, 15, 12, 30, tzinfo=UTC),
        query_version="test-v1",
        raw_payload_id=None,
        payload_hash="a" * 64,
        run_id="run-1",
    )
    assert len(lines) == 3
    assert snapshot.market is MarketType.HAD
    again, again_lines = normalize_hkjc_snapshot(
        session,
        match_id=match.id,
        market=MarketType.HAD,
        payload=parsed,
        snapshot_kind=SnapshotKind.T30M,
        snapshot_at=datetime(2026, 8, 15, 12, 30, tzinfo=UTC),
        query_version="test-v1",
        raw_payload_id=None,
        payload_hash="a" * 64,
        run_id="run-1",
    )
    assert again.id == snapshot.id
    assert len(again_lines) == 3
    assert session.query(OddsSnapshot).count() == 1
    assert session.query(MarketLine).count() == 3
```

- [ ] **Step 3: Write the failing quality gate tests**

Create `tests/ingest/test_quality.py`:

```python
from datetime import UTC, datetime, timedelta

from packages.domain.enums import CoverageFlag
from packages.ingest.quality import QualityInput, evaluate_quality

NOW = datetime(2026, 8, 15, 13, 0, tzinfo=UTC)


def test_complete_data_can_bet():
    report = evaluate_quality(
        QualityInput(
            competition_code="EPL",
            kickoff_at=NOW + timedelta(hours=1),
            now=NOW,
            odds_fetched_at=NOW - timedelta(minutes=2),
            has_standard_lineup=True,
            has_predicted_lineup=True,
            has_xg=True,
            news_item_count=3,
        )
    )
    assert report.can_bet is True
    assert report.flags == ()


def test_ucl_without_xg_is_vetoed():
    report = evaluate_quality(
        QualityInput(
            competition_code="UCL",
            kickoff_at=NOW + timedelta(hours=1),
            now=NOW,
            odds_fetched_at=NOW - timedelta(minutes=2),
            has_standard_lineup=True,
            has_predicted_lineup=True,
            has_xg=False,
            news_item_count=2,
        )
    )
    assert CoverageFlag.UCL_XG_MISSING in report.flags
    assert report.can_bet is False


def test_predicted_only_lineup_flags_but_does_not_veto():
    report = evaluate_quality(
        QualityInput(
            competition_code="EPL",
            kickoff_at=NOW + timedelta(hours=1),
            now=NOW,
            odds_fetched_at=NOW - timedelta(minutes=2),
            has_standard_lineup=False,
            has_predicted_lineup=True,
            has_xg=True,
            news_item_count=1,
        )
    )
    assert CoverageFlag.LINEUP_UNCONFIRMED in report.flags
    assert report.can_bet is True


def test_missing_lineup_is_vetoed():
    report = evaluate_quality(
        QualityInput(
            competition_code="EPL",
            kickoff_at=NOW + timedelta(hours=1),
            now=NOW,
            odds_fetched_at=NOW - timedelta(minutes=2),
            has_standard_lineup=False,
            has_predicted_lineup=False,
            has_xg=True,
            news_item_count=1,
        )
    )
    assert report.can_bet is False
    assert "lineup_missing" in report.veto_reasons


def test_stale_odds_are_vetoed_at_ten_minute_boundary():
    fresh = evaluate_quality(
        QualityInput(
            competition_code="EPL",
            kickoff_at=NOW + timedelta(hours=1),
            now=NOW,
            odds_fetched_at=NOW - timedelta(minutes=9),
            has_standard_lineup=True,
            has_predicted_lineup=True,
            has_xg=True,
            news_item_count=1,
        )
    )
    stale = evaluate_quality(
        QualityInput(
            competition_code="EPL",
            kickoff_at=NOW + timedelta(hours=1),
            now=NOW,
            odds_fetched_at=NOW - timedelta(minutes=11),
            has_standard_lineup=True,
            has_predicted_lineup=True,
            has_xg=True,
            news_item_count=1,
        )
    )
    assert CoverageFlag.ODDS_STALE not in fresh.flags
    assert CoverageFlag.ODDS_STALE in stale.flags
    assert stale.can_bet is False


def test_news_missing_and_degraded_source_flags():
    report = evaluate_quality(
        QualityInput(
            competition_code="EPL",
            kickoff_at=NOW + timedelta(hours=1),
            now=NOW,
            odds_fetched_at=NOW - timedelta(minutes=2),
            has_standard_lineup=True,
            has_predicted_lineup=True,
            has_xg=True,
            news_item_count=0,
            degraded_sources=("fotmob",),
        )
    )
    assert CoverageFlag.NEWS_MISSING in report.flags
    assert CoverageFlag.SOURCE_DEGRADED in report.flags
    assert report.can_bet is False
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/ingest -v`

Expected: collection errors because `packages.ingest` does not exist.

- [ ] **Step 5: Implement raw payload persistence**

Create `packages/ingest/__init__.py` as an empty file.

Create `packages/ingest/raw_store.py`:

```python
from __future__ import annotations

from sqlalchemy.orm import Session

from packages.adapters.base import FetchResult
from packages.db.models import RawPayload, SourceFetchRun
from packages.domain.enums import FetchRunStatus
from packages.shared.time import utc_now


def persist_raw_payload(
    session: Session,
    result: FetchResult,
    *,
    schema_version: str,
    run_id: str | None = None,
) -> RawPayload:
    if isinstance(result.payload, dict):
        body = result.payload
    elif isinstance(result.payload, str):
        body = {"text": result.payload}
    else:
        body = {"value": result.payload}
    row = RawPayload(
        source_name=result.source_name,
        source_url=result.source_url,
        fetched_at=result.fetched_at,
        schema_version=schema_version,
        payload_hash=result.payload_hash,
        body=body,
        http_status=result.http_status,
        run_id=run_id,
    )
    session.add(row)
    session.flush()
    return row


def start_fetch_run(
    session: Session,
    *,
    source_name: str,
    run_id: str,
    params: dict | None = None,
) -> SourceFetchRun:
    row = SourceFetchRun(
        source_name=source_name,
        run_id=run_id,
        started_at=utc_now(),
        status=FetchRunStatus.RUNNING,
        params=params or {},
    )
    session.add(row)
    session.flush()
    return row


def finish_fetch_run(
    session: Session,
    run: SourceFetchRun,
    *,
    status: FetchRunStatus,
    request_count: int,
    error_count: int,
    error_summary: str | None = None,
) -> SourceFetchRun:
    run.finished_at = utc_now()
    run.status = status
    run.request_count = request_count
    run.error_count = error_count
    run.error_summary = error_summary
    session.flush()
    return run
```

- [ ] **Step 6: Implement team aliases**

Create `packages/ingest/aliases.py`:

```python
from __future__ import annotations

import re
import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import Team
from packages.domain.errors import UnresolvedTeamError

TEAM_ALIASES: dict[str, str] = {
    "Arsenal": "arsenal",
    "Arsenal FC": "arsenal",
    "Manchester City": "manchester-city",
    "Man City": "manchester-city",
    "Manchester United": "manchester-united",
    "Man United": "manchester-united",
    "Nottingham Forest": "nottingham-forest",
    "Nott'm Forest": "nottingham-forest",
    "Paris Saint-Germain": "paris-saint-germain",
    "Paris SG": "paris-saint-germain",
    "PSG": "paris-saint-germain",
    "Bayern Munich": "bayern-munich",
    "Bayern München": "bayern-munich",
    "Borussia Dortmund": "borussia-dortmund",
    "Dortmund": "borussia-dortmund",
    "Internazionale": "inter-milan",
    "Inter": "inter-milan",
    "Inter Milan": "inter-milan",
    "AC Milan": "ac-milan",
    "Milan": "ac-milan",
    "Atletico Madrid": "atletico-madrid",
    "Atlético Madrid": "atletico-madrid",
    "Athletic Club": "athletic-bilbao",
    "Athletic Bilbao": "athletic-bilbao",
}


def canonical_team_slug(name: str) -> str:
    alias = TEAM_ALIASES.get(name)
    if alias is not None:
        return alias
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug


def resolve_team_id(session: Session, name: str) -> uuid.UUID:
    slug = canonical_team_slug(name)
    team = session.execute(select(Team).where(Team.slug == slug)).scalar_one_or_none()
    if team is None:
        raise UnresolvedTeamError(f"no team with slug {slug} for source name {name}")
    return team.id
```

- [ ] **Step 7: Implement canonical fixture and odds normalization**

Create `packages/ingest/normalize.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.adapters.football_data_org import FootballDataMatch
from packages.adapters.hkjc import HkjcOddsPayload
from packages.db.models import (
    Competition,
    MarketLine,
    Match,
    OddsSnapshot,
)
from packages.domain.enums import MarketType, MatchStatus, SnapshotKind
from packages.domain.errors import DomainError
from packages.ingest.aliases import resolve_team_id
from packages.shared.time import ensure_utc

COMPETITION_SEEDS = (
    ("EPL", "Premier League", "England", False, "EPL", "PL"),
    ("LALIGA", "La Liga", "Spain", False, "La_liga", "PD"),
    ("BUNDESLIGA", "Bundesliga", "Germany", False, "Bundesliga", "BL1"),
    ("SERIEA", "Serie A", "Italy", False, "Serie_A", "SA"),
    ("LIGUE1", "Ligue 1", "France", False, "Ligue_1", "FL1"),
    ("UCL", "UEFA Champions League", "Europe", True, None, "CL"),
)


def seed_competitions(session: Session) -> None:
    existing = {
        code for (code,) in session.execute(select(Competition.code)).all()
    }
    for code, name, country, is_cup, understat_slug, football_data_code in COMPETITION_SEEDS:
        if code in existing:
            continue
        session.add(
            Competition(
                code=code,
                name=name,
                country=country,
                is_cup=is_cup,
                understat_slug=understat_slug,
                football_data_code=football_data_code,
            )
        )
    session.flush()


def get_competition(session: Session, code: str) -> Competition:
    competition = session.execute(
        select(Competition).where(Competition.code == code)
    ).scalar_one_or_none()
    if competition is None:
        raise DomainError(f"unknown competition {code}")
    return competition


def season_label(season_start_year: int) -> str:
    return f"{season_start_year}/{str(season_start_year + 1)[2:]}"


@dataclass(frozen=True)
class NormalizedFixture:
    competition_id: uuid.UUID
    season: str
    kickoff_at: datetime
    home_team_id: uuid.UUID
    away_team_id: uuid.UUID
    status: MatchStatus
    matchday: int | None
    home_goals_90: int | None
    away_goals_90: int | None
    home_goals_final: int | None
    away_goals_final: int | None
    source_match_ids: dict[str, str]


def normalize_fixture(
    session: Session,
    dto: FootballDataMatch,
    competition_id: uuid.UUID,
) -> NormalizedFixture:
    return NormalizedFixture(
        competition_id=competition_id,
        season=season_label(dto.season_start_year),
        kickoff_at=ensure_utc(dto.kickoff_at),
        home_team_id=resolve_team_id(session, dto.home_team_name),
        away_team_id=resolve_team_id(session, dto.away_team_name),
        status=dto.status,
        matchday=dto.matchday,
        home_goals_90=dto.home_goals_90,
        away_goals_90=dto.away_goals_90,
        home_goals_final=dto.home_goals_final,
        away_goals_final=dto.away_goals_final,
        source_match_ids={"football-data.org": str(dto.source_match_id)},
    )


def upsert_match(session: Session, fixture: NormalizedFixture) -> Match:
    existing = session.execute(
        select(Match).where(
            Match.competition_id == fixture.competition_id,
            Match.season == fixture.season,
            Match.home_team_id == fixture.home_team_id,
            Match.away_team_id == fixture.away_team_id,
            Match.kickoff_at == fixture.kickoff_at,
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = Match(
            competition_id=fixture.competition_id,
            season=fixture.season,
            kickoff_at=fixture.kickoff_at,
            home_team_id=fixture.home_team_id,
            away_team_id=fixture.away_team_id,
            status=fixture.status,
            matchday=fixture.matchday,
            home_goals_90=fixture.home_goals_90,
            away_goals_90=fixture.away_goals_90,
            home_goals_final=fixture.home_goals_final,
            away_goals_final=fixture.away_goals_final,
            source_match_ids=dict(fixture.source_match_ids),
            coverage_flags=[],
        )
        session.add(existing)
        session.flush()
        return existing
    existing.status = fixture.status
    existing.matchday = fixture.matchday
    existing.home_goals_90 = fixture.home_goals_90
    existing.away_goals_90 = fixture.away_goals_90
    existing.home_goals_final = fixture.home_goals_final
    existing.away_goals_final = fixture.away_goals_final
    existing.source_match_ids = {
        **existing.source_match_ids,
        **fixture.source_match_ids,
    }
    session.flush()
    return existing


def normalize_hkjc_snapshot(
    session: Session,
    *,
    match_id: uuid.UUID,
    market: MarketType,
    payload: HkjcOddsPayload,
    snapshot_kind: SnapshotKind,
    snapshot_at: datetime,
    query_version: str,
    raw_payload_id: uuid.UUID | None,
    payload_hash: str,
    run_id: str,
) -> tuple[OddsSnapshot, list[MarketLine]]:
    snapshot_at = ensure_utc(snapshot_at)
    existing = session.execute(
        select(OddsSnapshot).where(
            OddsSnapshot.match_id == match_id,
            OddsSnapshot.market == market,
            OddsSnapshot.snapshot_kind == snapshot_kind,
            OddsSnapshot.snapshot_at == snapshot_at,
        )
    ).scalar_one_or_none()
    if existing is not None:
        lines = list(
            session.execute(
                select(MarketLine).where(MarketLine.snapshot_id == existing.id)
            ).scalars()
        )
        return existing, lines
    snapshot = OddsSnapshot(
        match_id=match_id,
        market=market,
        snapshot_kind=snapshot_kind,
        snapshot_at=snapshot_at,
        source_update_at=payload.source_update_at,
        query_version=query_version,
        payload_hash=payload_hash,
        raw_payload_id=raw_payload_id,
        run_id=run_id,
    )
    session.add(snapshot)
    session.flush()
    lines: list[MarketLine] = []
    for dto in payload.lines:
        line = MarketLine(
            snapshot_id=snapshot.id,
            odds_type=dto.odds_type,
            condition_raw=dto.condition_raw,
            line_index=dto.line_index,
            side=dto.side,
            odds_decimal=dto.odds_decimal,
            pool_status=dto.pool_status,
            line_status=dto.line_status,
            is_main=dto.is_main,
            offer_early_settlement=dto.offer_early_settlement,
            source_update_at=dto.source_update_at,
        )
        session.add(line)
        lines.append(line)
    session.flush()
    return snapshot, lines
```

- [ ] **Step 8: Implement the data quality gate**

Create `packages/ingest/quality.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from packages.domain.enums import CoverageFlag
from packages.shared.time import ensure_utc

ODDS_STALE_AFTER = timedelta(minutes=10)


@dataclass(frozen=True)
class QualityInput:
    competition_code: str
    kickoff_at: datetime
    now: datetime
    odds_fetched_at: datetime | None
    has_standard_lineup: bool
    has_predicted_lineup: bool
    has_xg: bool
    news_item_count: int
    degraded_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class QualityReport:
    flags: tuple[CoverageFlag, ...]
    veto_reasons: tuple[str, ...]

    @property
    def can_bet(self) -> bool:
        return not self.veto_reasons


def evaluate_quality(data: QualityInput) -> QualityReport:
    now = ensure_utc(data.now)
    flags: list[CoverageFlag] = []
    veto_reasons: list[str] = []

    if data.competition_code == "UCL" and not data.has_xg:
        flags.append(CoverageFlag.UCL_XG_MISSING)
        veto_reasons.append("ucl_xg_missing")

    if not data.has_standard_lineup:
        flags.append(CoverageFlag.LINEUP_UNCONFIRMED)
        if not data.has_predicted_lineup:
            veto_reasons.append("lineup_missing")

    odds_stale = (
        data.odds_fetched_at is None
        or now - ensure_utc(data.odds_fetched_at) > ODDS_STALE_AFTER
    )
    if odds_stale:
        flags.append(CoverageFlag.ODDS_STALE)
        veto_reasons.append("odds_stale")

    if data.news_item_count == 0:
        flags.append(CoverageFlag.NEWS_MISSING)

    if data.degraded_sources:
        flags.append(CoverageFlag.SOURCE_DEGRADED)
        veto_reasons.append("source_degraded:" + ",".join(sorted(data.degraded_sources)))

    return QualityReport(flags=tuple(flags), veto_reasons=tuple(veto_reasons))
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/ingest -v`

Expected: `14 passed`.

- [ ] **Step 10: Commit**

```bash
git add packages/ingest tests/ingest
git commit -m "feat: add canonical normalization, raw payload store, and data quality gate"
```

---

#### Task 10 v2.1 amendments

These steps add decision-time temporal gates, UCL coverage levels, and the source verification gate.

**Files:**
- Create: `packages/ingest/temporal.py`
- Test: `tests/ingest/test_temporal.py`

**Interfaces:**
- Produces: `DecisionMode`; `TemporalEvidence`; `TemporalGateResult`; `evaluate_temporal_gate(mode, decision_at, evidence)`; `resolve_historical_availability(observed_snapshot_at, provider_point_in_time)`; `classify_ucl_coverage(...)`; `SourceVerification`; `can_mark_verified(verification)`.

- [ ] **Step 11: Write the failing temporal gate tests**

Create `tests/ingest/test_temporal.py`:

```python
import inspect
from datetime import UTC, date, datetime

from packages.domain.enums import AvailabilityBasis, SourceStatus, UclCoverageLevel
from packages.ingest.temporal import (
    DecisionMode,
    SourceVerification,
    TemporalEvidence,
    can_mark_verified,
    classify_ucl_coverage,
    evaluate_temporal_gate,
    resolve_historical_availability,
)

DECISION = datetime(2026, 8, 15, 13, 30, tzinfo=UTC)


def test_prospective_allows_first_seen_before_decision():
    result = evaluate_temporal_gate(
        mode=DecisionMode.PROSPECTIVE,
        decision_at=DECISION,
        evidence=TemporalEvidence(
            first_seen_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
            available_at=None,
            availability_basis=AvailabilityBasis.OBSERVED_SNAPSHOT,
        ),
    )
    assert result.allowed is True


def test_prospective_rejects_first_seen_after_decision():
    result = evaluate_temporal_gate(
        mode=DecisionMode.PROSPECTIVE,
        decision_at=DECISION,
        evidence=TemporalEvidence(
            first_seen_at=datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
            available_at=None,
            availability_basis=AvailabilityBasis.OBSERVED_SNAPSHOT,
        ),
    )
    assert result.allowed is False
    assert result.reason == "first_seen_after_decision"


def test_retrospective_allows_primary_basis():
    result = evaluate_temporal_gate(
        mode=DecisionMode.RETROSPECTIVE,
        decision_at=DECISION,
        evidence=TemporalEvidence(
            first_seen_at=None,
            available_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
            availability_basis=AvailabilityBasis.PROVIDER_POINT_IN_TIME,
        ),
    )
    assert result.allowed is True


def test_retrospective_rejects_assumed_basis():
    result = evaluate_temporal_gate(
        mode=DecisionMode.RETROSPECTIVE,
        decision_at=DECISION,
        evidence=TemporalEvidence(
            first_seen_at=None,
            available_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
            availability_basis=AvailabilityBasis.AVAILABILITY_ASSUMED,
        ),
    )
    assert result.allowed is False
    assert result.reason == "non_primary_availability_basis"


def test_historical_availability_never_uses_first_seen():
    parameters = inspect.signature(resolve_historical_availability).parameters
    assert "first_seen_at" not in parameters
    available_at, basis = resolve_historical_availability(
        observed_snapshot_at=None,
        provider_point_in_time=None,
    )
    assert available_at is None
    assert basis is AvailabilityBasis.UNAVAILABLE


def test_ucl_coverage_levels():
    insufficient = classify_ucl_coverage(
        has_settleable_result=False,
        has_target_market_odds=True,
        has_xg=False,
        lineup_dependent=False,
        has_lineup_fallback=False,
    )
    reduced = classify_ucl_coverage(
        has_settleable_result=True,
        has_target_market_odds=True,
        has_xg=False,
        lineup_dependent=False,
        has_lineup_fallback=True,
    )
    assert insufficient is UclCoverageLevel.INSUFFICIENT
    assert reduced is UclCoverageLevel.REDUCED


def test_verified_source_requires_all_evidence():
    complete = SourceVerification(
        status=SourceStatus.VERIFIED,
        verification_date=date(2026, 8, 1),
        schema_scope="fixtures and results",
        field_scope="score, kickoff, teams",
        test_evidence_ref="tests/adapters/test_football_data_org.py",
        licensing_check="allowed for personal research",
    )
    incomplete = SourceVerification(
        status=SourceStatus.VERIFIED,
        verification_date=None,
        schema_scope="fixtures and results",
        field_scope="score, kickoff, teams",
        test_evidence_ref="tests/adapters/test_football_data_org.py",
        licensing_check="allowed for personal research",
    )
    assert can_mark_verified(complete) is True
    assert can_mark_verified(incomplete) is False
```

- [ ] **Step 12: Run the temporal tests to verify they fail**

Run: `uv run pytest tests/ingest/test_temporal.py -v`

Expected: collection error because `packages.ingest.temporal` does not exist.

- [ ] **Step 13: Implement the temporal gate**

Create `packages/ingest/temporal.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from packages.domain.enums import AvailabilityBasis, SourceStatus, UclCoverageLevel
from packages.shared.time import ensure_utc

PRIMARY_AVAILABILITY_BASES = frozenset(
    {
        AvailabilityBasis.OBSERVED_SNAPSHOT,
        AvailabilityBasis.PROVIDER_POINT_IN_TIME,
    }
)


class DecisionMode(StrEnum):
    PROSPECTIVE = "prospective"
    RETROSPECTIVE = "retrospective"


@dataclass(frozen=True)
class TemporalEvidence:
    first_seen_at: datetime | None
    available_at: datetime | None
    availability_basis: AvailabilityBasis


@dataclass(frozen=True)
class TemporalGateResult:
    allowed: bool
    reason: str


def evaluate_temporal_gate(
    *,
    mode: DecisionMode,
    decision_at: datetime,
    evidence: TemporalEvidence,
) -> TemporalGateResult:
    decision = ensure_utc(decision_at)
    if mode is DecisionMode.PROSPECTIVE:
        if evidence.first_seen_at is None:
            return TemporalGateResult(False, "first_seen_at_missing")
        if ensure_utc(evidence.first_seen_at) > decision:
            return TemporalGateResult(False, "first_seen_after_decision")
        return TemporalGateResult(True, "ok")
    if evidence.available_at is None:
        return TemporalGateResult(False, "available_at_missing")
    if ensure_utc(evidence.available_at) > decision:
        return TemporalGateResult(False, "available_after_decision")
    if evidence.availability_basis not in PRIMARY_AVAILABILITY_BASES:
        return TemporalGateResult(False, "non_primary_availability_basis")
    return TemporalGateResult(True, "ok")


def resolve_historical_availability(
    *,
    observed_snapshot_at: datetime | None,
    provider_point_in_time: datetime | None,
) -> tuple[datetime | None, AvailabilityBasis]:
    if observed_snapshot_at is not None:
        return ensure_utc(observed_snapshot_at), AvailabilityBasis.OBSERVED_SNAPSHOT
    if provider_point_in_time is not None:
        return (
            ensure_utc(provider_point_in_time),
            AvailabilityBasis.PROVIDER_POINT_IN_TIME,
        )
    return None, AvailabilityBasis.UNAVAILABLE


def classify_ucl_coverage(
    *,
    has_settleable_result: bool,
    has_target_market_odds: bool,
    has_xg: bool,
    lineup_dependent: bool,
    has_lineup_fallback: bool,
) -> UclCoverageLevel:
    if not has_settleable_result or not has_target_market_odds:
        return UclCoverageLevel.INSUFFICIENT
    if lineup_dependent and not has_lineup_fallback:
        return UclCoverageLevel.INSUFFICIENT
    if not has_xg or not has_lineup_fallback:
        return UclCoverageLevel.REDUCED
    return UclCoverageLevel.FULL


@dataclass(frozen=True)
class SourceVerification:
    status: SourceStatus
    verification_date: date | None
    schema_scope: str | None
    field_scope: str | None
    test_evidence_ref: str | None
    licensing_check: str | None


def can_mark_verified(verification: SourceVerification) -> bool:
    return all(
        (
            verification.verification_date is not None,
            bool(verification.schema_scope),
            bool(verification.field_scope),
            bool(verification.test_evidence_ref),
            bool(verification.licensing_check),
        )
    )
```

- [ ] **Step 14: Run the temporal and existing ingest tests**

Run: `uv run pytest tests/ingest/test_temporal.py -v`

Expected: `7 passed`.

Run: `uv run pytest tests/ingest -v`

Expected: `21 passed`.

- [ ] **Step 15: Commit**

```bash
git add packages/ingest/temporal.py tests/ingest/test_temporal.py
git commit -m "feat: add decision-time temporal gates and source verification checks"
```

---

### Task 11: Paper Ledger Service and Metrics

> **v2.1:** The `run_key` code below is superseded by “Task 11 v2.1 amendments” at the end of this task. Follow the amendment.

**Files:**
- Create: `packages/ledger/metrics.py`
- Create: `packages/ledger/service.py`
- Test: `tests/ledger/test_metrics.py`
- Test: `tests/ledger/test_service.py`

**Interfaces:**
- Consumes: `PaperBet`, `Settlement`, `BetStatus`, `MarketType`, `Side`, `SettlementSource`, `settlement` helpers, `utc_now`.
- Produces: `roi(total_stake, total_payout)`, `clv(bet_odds, closing_odds)`, `brier_score(probability, outcome)`, `max_drawdown(equity_curve)`, `bankroll_curve(initial, settled)`; `INITIAL_BANKROLL`, `PlaceBetRequest`, `LedgerSummary`, `LedgerService` with `available_bankroll`, `place_bet`, `settle_paper_bet`, `summary`.

- [ ] **Step 1: Write the failing metrics tests**

Create `tests/ledger/test_metrics.py`:

```python
from decimal import Decimal

import pytest

from packages.ledger.metrics import (
    bankroll_curve,
    brier_score,
    clv,
    max_drawdown,
    roi,
)

D = Decimal


def test_roi_uses_net_payout_over_stake():
    assert roi(D("100"), D("200")) == D("1")
    assert roi(D("100"), D("80")) == D("-0.2")
    assert roi(D("0"), D("10")) == D("0")


def test_clv_handles_missing_closing_odds():
    assert clv(D("2.0"), D("1.8")) == D("2.0") / D("1.8") - D("1")
    assert clv(D("2.0"), None) is None
    assert clv(D("2.0"), D("0")) is None


def test_brier_score_is_squared_error():
    assert brier_score(D("0.7"), 1) == D("0.09")
    assert brier_score(D("0.7"), 0) == D("0.49")
    with pytest.raises(ValueError):
        brier_score(D("0.7"), 2)


def test_max_drawdown_uses_peak_to_trough():
    curve = [D("100"), D("120"), D("90"), D("110")]
    assert max_drawdown(curve) == D("0.25")
    assert max_drawdown([D("100"), D("110")]) == D("0")
    assert max_drawdown([]) == D("0")


def test_bankroll_curve_applies_payout_minus_stake():
    curve = bankroll_curve(D("1000"), [(D("100"), D("200")), (D("50"), D("0"))])
    assert curve == [D("1000"), D("1100"), D("1050")]
```

- [ ] **Step 2: Write the failing ledger service tests**

Create `tests/ledger/test_service.py`:

```python
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from packages.db.models import Match
from packages.domain.enums import BetStatus, MarketType, Side
from packages.domain.errors import (
    AlreadySettledError,
    InsufficientBankrollError,
    SettlementInputError,
)
from packages.ledger.service import LedgerService, PlaceBetRequest

D = Decimal
KICKOFF = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)


def _match(session) -> Match:
    match = Match(
        competition_id=uuid.uuid4(),
        season="2025/26",
        kickoff_at=KICKOFF,
        home_team_id=uuid.uuid4(),
        away_team_id=uuid.uuid4(),
        status="scheduled",
        source_match_ids={"hkjc": "HK-1001"},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    return match


def _request(match_id, *, run_key="run-1", stake="100.00") -> PlaceBetRequest:
    return PlaceBetRequest(
        match_id=match_id,
        market=MarketType.HAD,
        line_key="0.0",
        selection=Side.H,
        odds_decimal=D("2.00"),
        stake=D(stake),
        run_key=run_key,
        placed_at=KICKOFF,
    )


def test_place_bet_is_idempotent_by_run_key(session):
    match = _match(session)
    ledger = LedgerService(session)
    first = ledger.place_bet(_request(match.id))
    second = ledger.place_bet(_request(match.id))
    assert first.id == second.id
    assert first.status is BetStatus.PENDING
    assert first.bankroll_before == D("10000.00")


def test_place_bet_rejects_insufficient_bankroll(session):
    match = _match(session)
    ledger = LedgerService(session, initial_bankroll=D("50.00"))
    with pytest.raises(InsufficientBankrollError):
        ledger.place_bet(_request(match.id, stake="100.00"))


def test_place_bet_rejects_odds_at_or_below_one_point_zero_one(session):
    match = _match(session)
    ledger = LedgerService(session)
    bad = PlaceBetRequest(
        match_id=match.id,
        market=MarketType.HAD,
        line_key="0.0",
        selection=Side.H,
        odds_decimal=D("1.01"),
        stake=D("10.00"),
        run_key="bad-odds",
    )
    with pytest.raises(SettlementInputError):
        ledger.place_bet(bad)


def test_settle_bet_records_payout_clv_and_brier(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    settlement = ledger.settle_paper_bet(
        bet.id,
        home_goals_90=2,
        away_goals_90=1,
        refunded_markets=frozenset(),
        payout_confirmed=True,
        hk_result_ref="HK-1001",
        closing_odds=D("1.80"),
        final_probability=D("0.55"),
    )
    assert settlement.result_status is BetStatus.WON
    assert settlement.payout == D("200.00")
    assert settlement.provisional is False
    assert abs(settlement.clv - (D("2.0") / D("1.80") - D("1"))) < D("0.000001")
    assert settlement.brier_score == D("0.2025")
    assert bet.status is BetStatus.WON


def test_settle_bet_rejects_double_settlement(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    ledger.settle_paper_bet(
        bet.id,
        home_goals_90=2,
        away_goals_90=1,
        refunded_markets=frozenset(),
        payout_confirmed=True,
        hk_result_ref="HK-1001",
        closing_odds=None,
        final_probability=None,
    )
    with pytest.raises(AlreadySettledError):
        ledger.settle_paper_bet(
            bet.id,
            home_goals_90=2,
            away_goals_90=1,
            refunded_markets=frozenset(),
            payout_confirmed=True,
            hk_result_ref="HK-1001",
            closing_odds=None,
            final_probability=None,
        )


def test_settle_refunded_market_voids_bet(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id, run_key="void-run"))
    settlement = ledger.settle_paper_bet(
        bet.id,
        home_goals_90=2,
        away_goals_90=1,
        refunded_markets=frozenset({MarketType.HAD}),
        payout_confirmed=True,
        hk_result_ref="HK-1001",
        closing_odds=None,
        final_probability=None,
    )
    assert settlement.result_status is BetStatus.VOID
    assert settlement.payout == D("100.00")


def test_summary_reports_roi_and_bankroll(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    ledger.settle_paper_bet(
        bet.id,
        home_goals_90=2,
        away_goals_90=1,
        refunded_markets=frozenset(),
        payout_confirmed=True,
        hk_result_ref="HK-1001",
        closing_odds=None,
        final_probability=None,
    )
    summary = ledger.summary()
    assert summary.total_stake == D("100.00")
    assert summary.total_payout == D("200.00")
    assert summary.roi == D("1")
    assert summary.settled_count == 1
    assert summary.pending_count == 0
    assert summary.bankroll == D("10100.00")
    assert summary.max_drawdown == D("0")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/ledger/test_metrics.py tests/ledger/test_service.py -v`

Expected: collection errors because `packages.ledger.metrics` and `packages.ledger.service` do not exist.

- [ ] **Step 4: Implement metrics**

Create `packages/ledger/metrics.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def roi(total_stake: Decimal, total_payout: Decimal) -> Decimal:
    if total_stake <= Decimal("0"):
        return Decimal("0")
    return (total_payout - total_stake) / total_stake


def clv(bet_odds: Decimal, closing_odds: Decimal | None) -> Decimal | None:
    if closing_odds is None or closing_odds <= Decimal("0"):
        return None
    return bet_odds / closing_odds - Decimal("1")


def brier_score(probability: Decimal, outcome: int) -> Decimal:
    if outcome not in (0, 1):
        raise ValueError("outcome must be 0 or 1")
    return (probability - Decimal(outcome)) ** 2


def max_drawdown(equity_curve: Sequence[Decimal]) -> Decimal:
    if not equity_curve:
        return Decimal("0")
    peak = equity_curve[0]
    worst = Decimal("0")
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > Decimal("0"):
            drawdown = (peak - value) / peak
            if drawdown > worst:
                worst = drawdown
    return worst


def bankroll_curve(
    initial: Decimal,
    settled: Sequence[tuple[Decimal, Decimal]],
) -> list[Decimal]:
    balance = initial
    curve = [balance]
    for stake, payout in settled:
        balance = balance - stake + payout
        curve.append(balance)
    return curve
```

- [ ] **Step 5: Implement the ledger service**

Create `packages/ledger/service.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.db.models import PaperBet, Settlement
from packages.domain.enums import BetStatus, MarketType, SettlementSource, Side
from packages.domain.errors import (
    AlreadySettledError,
    InsufficientBankrollError,
    SettlementInputError,
)
from packages.domain.markets import validate_side
from packages.ledger.metrics import (
    bankroll_curve,
    brier_score,
    clv,
    max_drawdown,
    roi,
)
from packages.ledger.settlement import settle_market, settle_void
from packages.shared.time import utc_now

INITIAL_BANKROLL = Decimal("10000.00")
MIN_BET_ODDS = Decimal("1.01")


@dataclass(frozen=True)
class PlaceBetRequest:
    match_id: uuid.UUID
    market: MarketType
    line_key: str
    selection: Side
    odds_decimal: Decimal
    stake: Decimal
    run_key: str
    odds_snapshot_id: uuid.UUID | None = None
    placed_at: datetime | None = None


@dataclass(frozen=True)
class LedgerSummary:
    total_stake: Decimal
    total_payout: Decimal
    roi: Decimal
    settled_count: int
    pending_count: int
    bankroll: Decimal
    max_drawdown: Decimal


class LedgerService:
    def __init__(
        self,
        session: Session,
        initial_bankroll: Decimal = INITIAL_BANKROLL,
        fee_rate: Decimal = Decimal("0"),
    ) -> None:
        self._session = session
        self._initial = initial_bankroll
        self._fee_rate = fee_rate

    def available_bankroll(self) -> Decimal:
        settled_pnl = self._session.execute(
            select(func.coalesce(func.sum(Settlement.payout - PaperBet.stake), 0))
            .select_from(Settlement)
            .join(PaperBet, Settlement.paper_bet_id == PaperBet.id)
            .where(Settlement.provisional.is_(False))
        ).scalar_one()
        open_stakes = self._session.execute(
            select(func.coalesce(func.sum(PaperBet.stake), 0)).where(
                PaperBet.status == BetStatus.PENDING
            )
        ).scalar_one()
        fee_multiplier = Decimal("1") - self._fee_rate
        settled_net = Decimal(str(settled_pnl)) * fee_multiplier
        return self._initial + settled_net - Decimal(str(open_stakes))

    def place_bet(self, request: PlaceBetRequest) -> PaperBet:
        existing = self._session.execute(
            select(PaperBet).where(PaperBet.run_key == request.run_key)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        validate_side(request.market, request.selection)
        if request.odds_decimal <= MIN_BET_ODDS:
            raise SettlementInputError(
                f"odds must be greater than {MIN_BET_ODDS}, got {request.odds_decimal}"
            )
        if request.stake <= Decimal("0"):
            raise SettlementInputError("stake must be positive")
        bankroll = self.available_bankroll()
        if request.stake > bankroll:
            raise InsufficientBankrollError(
                f"stake {request.stake} exceeds available bankroll {bankroll}"
            )
        bet = PaperBet(
            match_id=request.match_id,
            market=request.market,
            line_key=request.line_key,
            selection=request.selection,
            odds_decimal=request.odds_decimal,
            stake=request.stake,
            bankroll_before=bankroll,
            placed_at=request.placed_at or utc_now(),
            odds_snapshot_id=request.odds_snapshot_id,
            status=BetStatus.PENDING,
            run_key=request.run_key,
        )
        self._session.add(bet)
        self._session.flush()
        return bet

    def settle_paper_bet(
        self,
        bet_id: uuid.UUID,
        *,
        home_goals_90: int,
        away_goals_90: int,
        refunded_markets: frozenset[MarketType],
        payout_confirmed: bool,
        hk_result_ref: str | None,
        closing_odds: Decimal | None,
        final_probability: Decimal | None,
        settled_at: datetime | None = None,
    ) -> Settlement:
        bet = self._session.get(PaperBet, bet_id)
        if bet is None:
            raise SettlementInputError(f"unknown paper bet {bet_id}")
        if bet.status is not BetStatus.PENDING:
            raise AlreadySettledError(f"paper bet {bet_id} is already settled")
        if bet.market in refunded_markets:
            outcome = settle_void(bet.stake)
        else:
            outcome = settle_market(
                bet.market,
                bet.selection,
                home_goals_90,
                away_goals_90,
                bet.line_key,
                bet.odds_decimal,
                bet.stake,
            )
        won_indicator = 1 if outcome.result_status in (
            BetStatus.WON,
            BetStatus.HALF_WON_HALF_PUSH,
        ) else 0
        settlement = Settlement(
            paper_bet_id=bet.id,
            result_status=outcome.result_status,
            payout=outcome.payout,
            payout_unrounded=outcome.payout_unrounded,
            clv=clv(bet.odds_decimal, closing_odds),
            brier_score=(
                None
                if final_probability is None
                else brier_score(final_probability, won_indicator)
            ),
            settled_at=settled_at or utc_now(),
            hk_result_ref=hk_result_ref,
            provisional=not payout_confirmed,
            source=(
                SettlementSource.HKJC_CONFIRMED
                if payout_confirmed
                else SettlementSource.HKJC_PROVISIONAL
            ),
        )
        bet.status = outcome.result_status
        self._session.add(settlement)
        self._session.flush()
        return settlement

    def summary(self) -> LedgerSummary:
        fee_multiplier = Decimal("1") - self._fee_rate
        rows = self._session.execute(
            select(PaperBet.stake, Settlement.payout, Settlement.settled_at)
            .join(Settlement, Settlement.paper_bet_id == PaperBet.id)
            .where(Settlement.provisional.is_(False))
            .order_by(Settlement.settled_at)
        ).all()
        total_stake = sum((Decimal(str(row[0])) for row in rows), Decimal("0"))
        gross_payout = sum((Decimal(str(row[1])) for row in rows), Decimal("0"))
        total_payout = gross_payout * fee_multiplier
        curve = bankroll_curve(
            self._initial,
            [
                (Decimal(str(row[0])), Decimal(str(row[1])) * fee_multiplier)
                for row in rows
            ],
        )
        pending_count = self._session.execute(
            select(func.count())
            .select_from(PaperBet)
            .where(PaperBet.status == BetStatus.PENDING)
        ).scalar_one()
        return LedgerSummary(
            total_stake=total_stake,
            total_payout=total_payout,
            roi=roi(total_stake, total_payout),
            settled_count=len(rows),
            pending_count=int(pending_count),
            bankroll=curve[-1],
            max_drawdown=max_drawdown(curve),
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/ledger/test_metrics.py tests/ledger/test_service.py -v`

Expected: `12 passed`.

- [ ] **Step 7: Commit**

```bash
git add packages/ledger/metrics.py packages/ledger/service.py tests/ledger/test_metrics.py tests/ledger/test_service.py
git commit -m "feat: add paper ledger service with clv, brier, roi, and drawdown"
```

#### Task 11 v2.1 amendments

These amendments replace the single `run_key` design above. Do not implement `paper_bets.run_key`.

**Files (amend):**
- Modify: `packages/ledger/service.py`
- Modify: `tests/ledger/test_service.py`

**Interfaces (replace):**

```python
@dataclass(frozen=True)
class PlaceBetRequest:
    match_id: uuid.UUID
    market: MarketType
    line_key: str
    selection: Side
    odds_decimal: Decimal
    stake: Decimal
    analysis_run_key: str
    decision_slot_key: str
    bet_intent_key: str
    decision_at: datetime
    odds_snapshot_id: uuid.UUID | None = None
```

`LedgerService.place_bet` must:

1. Return the existing `PaperBet` when `bet_intent_key` already exists.
2. Lock the bankroll account row with `SELECT ... FOR UPDATE`.
3. Compute `cash_available = balance - reserved_stake`.
4. Reject `stake > cash_available`.
5. Insert a `BankrollReservation(status="held")` and increase `reserved_stake`.
6. Insert the `PaperBet` with all three keys and `decision_at`.
7. Do steps 2-6 inside one transaction/savepoint; a failure must roll back reservation and bet together.

**Implementation delta:**

```python
def place_bet(self, request: PlaceBetRequest) -> PaperBet:
    if request.odds_decimal <= MIN_ODDS:
        raise SettlementInputError(
            f"odds must be greater than {MIN_ODDS}, got {request.odds_decimal}"
        )
    with self._session.begin_nested():
        existing = self._session.execute(
            select(PaperBet).where(PaperBet.bet_intent_key == request.bet_intent_key)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        account = self._session.execute(
            select(BankrollAccount).where(BankrollAccount.name == "paper").with_for_update()
        ).scalar_one()
        cash_available = account.balance - account.reserved_stake
        if request.stake > cash_available:
            raise InsufficientBankrollError(
                f"stake {request.stake} exceeds cash available {cash_available}"
            )
        account.reserved_stake += request.stake
        reservation = BankrollReservation(
            bet_intent_key=request.bet_intent_key,
            amount=request.stake,
            status="held",
        )
        bet = PaperBet(
            match_id=request.match_id,
            market=request.market,
            line_key=request.line_key,
            selection=request.selection,
            odds_decimal=request.odds_decimal,
            stake=request.stake,
            bankroll_before=cash_available,
            placed_at=request.decision_at,
            odds_snapshot_id=request.odds_snapshot_id,
            status=BetStatus.PENDING,
            analysis_run_key=request.analysis_run_key,
            decision_slot_key=request.decision_slot_key,
            bet_intent_key=request.bet_intent_key,
            decision_at=request.decision_at,
        )
        self._session.add_all([reservation, bet])
        self._session.flush()
        return bet
```

`settle_paper_bet` must also:

```python
reservation = self._session.execute(
    select(BankrollReservation).where(
        BankrollReservation.bet_intent_key == bet.bet_intent_key,
        BankrollReservation.status == "held",
    )
).scalar_one()
account = self._session.execute(
    select(BankrollAccount).where(BankrollAccount.name == "paper").with_for_update()
).scalar_one()
account.reserved_stake -= reservation.amount
account.balance += outcome.payout - bet.stake
reservation.status = "committed"
```

**Required tests (replace `run_key` tests):**

```python
def test_duplicate_bet_intent_returns_same_bet(session):
    match = _match(session)
    ledger = LedgerService(session)
    first = ledger.place_bet(_request(match.id, bet_intent_key="bet-1"))
    second = ledger.place_bet(_request(match.id, bet_intent_key="bet-1"))
    assert first.id == second.id
    assert session.query(PaperBet).count() == 1


def test_same_decision_slot_with_different_analysis_does_not_duplicate(session):
    match = _match(session)
    ledger = LedgerService(session)
    first = ledger.place_bet(
        _request(match.id, analysis_run_key="analysis-1", bet_intent_key="bet-1")
    )
    second = ledger.place_bet(
        _request(match.id, analysis_run_key="analysis-2", bet_intent_key="bet-1")
    )
    assert first.id == second.id
    assert session.query(PaperBet).count() == 1


def test_concurrent_stakes_cannot_overspend_cash_available(session):
    match = _match(session)
    ledger = LedgerService(session, initial_bankroll=D("150.00"))
    ledger.place_bet(_request(match.id, stake="100.00", bet_intent_key="bet-1"))
    with pytest.raises(InsufficientBankrollError):
        ledger.place_bet(_request(match.id, stake="100.00", bet_intent_key="bet-2"))


def test_odds_of_exactly_one_point_zero_one_is_allowed(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(
        PlaceBetRequest(
            match_id=match.id,
            market=MarketType.HAD,
            line_key="0.0",
            selection=Side.H,
            odds_decimal=D("1.01"),
            stake=D("10.00"),
            analysis_run_key="a",
            decision_slot_key="d",
            bet_intent_key="b",
            decision_at=KICKOFF,
        )
    )
    assert bet.odds_decimal == D("1.01")
```

`_request` must have this default signature:

```python
def _request(
    match_id,
    *,
    analysis_run_key: str = "analysis-1",
    decision_slot_key: str = "slot-1",
    bet_intent_key: str = "bet-1",
    stake="100.00",
) -> PlaceBetRequest:
    return PlaceBetRequest(
        match_id=match_id,
        market=MarketType.HAD,
        line_key="0.0",
        selection=Side.H,
        odds_decimal=D("2.00"),
        stake=D(stake),
        analysis_run_key=analysis_run_key,
        decision_slot_key=decision_slot_key,
        bet_intent_key=bet_intent_key,
        decision_at=KICKOFF,
    )
```

Run: `uv run pytest tests/ledger/test_service.py -v`
Expected: all ledger service tests pass, including the four duplicate/bankroll/odds-boundary tests.

---

### Task 12: Pipeline, Scheduler, Worker, API, and End-to-End Dry Run

> **v2.1:** The full-market and `run_key` code below is superseded by “Task 12 v2.1 amendments” at the end of this task. Follow the amendment.

**Files:**
- Create: `packages/ingest/triggers.py`
- Create: `packages/ingest/pipeline.py`
- Create: `packages/ingest/dry_run.py`
- Create: `apps/__init__.py`
- Create: `apps/api/__init__.py`
- Create: `apps/api/main.py`
- Create: `apps/worker/__init__.py`
- Create: `apps/worker/jobs.py`
- Create: `apps/worker/main.py`
- Create: `apps/scheduler/__init__.py`
- Create: `apps/scheduler/main.py`
- Create: `scripts/dry_run.py`
- Test: `tests/ingest/test_triggers.py`
- Test: `tests/e2e/test_dry_run.py`
- Test: `tests/api/test_health.py`

**Interfaces:**
- Consumes: all Phase 1 adapters, `normalize_*`, `LedgerService`, `Settings`, ORM models.
- Produces: `TRIGGER_OFFSETS`, `compute_trigger_times(kickoff_at)`; `AdapterBundle`, `PipelineError`, `build_adapters(settings)`, `IngestPipeline` with `ingest_fixtures` and `ingest_hkjc_odds`; `DryRunResult`, `run_dry_run(session, initial_bankroll)`; `create_app(settings, redis_client)`; RQ job functions `run_daily_ingest`, `run_match_trigger`, `settle_match`; `build_queue()`, `build_scheduler()`.

- [ ] **Step 1: Write the failing trigger tests**

Create `tests/ingest/test_triggers.py`:

```python
from datetime import UTC, datetime, timedelta

from packages.ingest.triggers import compute_trigger_times


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
```

- [ ] **Step 2: Write the failing end-to-end and health tests**

Create `tests/e2e/test_dry_run.py`:

```python
from decimal import Decimal

from packages.db.models import Match, PaperBet
from packages.ingest.dry_run import run_dry_run


def test_dry_run_produces_a_winning_had_bet(session):
    result = run_dry_run(session)
    assert result.settlement_status == "won"
    assert result.payout == Decimal("200.00")
    assert result.roi == Decimal("1")
    assert result.clv is not None
    assert abs(result.clv - Decimal("0.111111")) < Decimal("0.000001")


def test_dry_run_is_idempotent(session):
    first = run_dry_run(session)
    second = run_dry_run(session)
    assert first.bet_id == second.bet_id
    assert first.match_id == second.match_id
    assert session.query(Match).count() == 1
    assert session.query(PaperBet).count() == 1
```

Create `tests/api/test_health.py`:

```python
from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.shared.config import Settings


def test_health_and_ready_endpoints():
    app = create_app(
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            _env_file=None,
        )
    )
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok"}
    response = client.get("/readyz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "up"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/ingest/test_triggers.py tests/e2e/test_dry_run.py tests/api/test_health.py -v`

Expected: collection errors because `packages.ingest.triggers`, `packages.ingest.dry_run`, and `apps.api.main` do not exist.

- [ ] **Step 4: Implement trigger computation**

Create `packages/ingest/triggers.py`:

```python
from datetime import datetime, timedelta

from packages.shared.time import ensure_utc

TRIGGER_OFFSETS = {
    "T-24h": timedelta(hours=24),
    "T-3h": timedelta(hours=3),
    "T-75m": timedelta(minutes=75),
    "T-30m": timedelta(minutes=30),
    "T-5m": timedelta(minutes=5),
}


def compute_trigger_times(kickoff_at: datetime) -> dict[str, datetime]:
    kickoff = ensure_utc(kickoff_at)
    return {name: kickoff - offset for name, offset in TRIGGER_OFFSETS.items()}
```

- [ ] **Step 5: Implement the ingestion pipeline and adapter factory**

Create `packages/ingest/pipeline.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from packages.adapters.football_data_co_uk import FootballDataCoUkAdapter
from packages.adapters.football_data_org import FootballDataOrgAdapter
from packages.adapters.fotmob import FotMobAdapter
from packages.adapters.hkjc import HkjcAdapter
from packages.adapters.open_meteo import OpenMeteoAdapter
from packages.adapters.rss_news import RssNewsAdapter
from packages.adapters.understat import UnderstatAdapter
from packages.db.models import MarketLine, Match, OddsSnapshot
from packages.domain.enums import MarketType, SnapshotKind
from packages.ingest.normalize import (
    get_competition,
    normalize_fixture,
    normalize_hkjc_snapshot,
    upsert_match,
)
from packages.ingest.raw_store import persist_raw_payload
from packages.shared.config import Settings


class PipelineError(Exception):
    """Raised when a pipeline run cannot proceed."""


@dataclass
class AdapterBundle:
    football_data: FootballDataOrgAdapter | None = None
    understat: UnderstatAdapter | None = None
    fotmob: FotMobAdapter | None = None
    hkjc: HkjcAdapter | None = None
    news: RssNewsAdapter | None = None
    weather: OpenMeteoAdapter | None = None
    history: FootballDataCoUkAdapter | None = None


def build_adapters(settings: Settings) -> AdapterBundle:
    return AdapterBundle(
        football_data=FootballDataOrgAdapter(
            api_key=settings.football_data_org_api_key or ""
        ),
        understat=UnderstatAdapter(),
        fotmob=FotMobAdapter(),
        hkjc=HkjcAdapter(
            queries_dir=settings.hkjc_queries_dir,
            query_version=settings.hkjc_query_version,
            graphql_url=settings.hkjc_graphql_url,
        ),
        news=RssNewsAdapter(),
        weather=OpenMeteoAdapter(),
        history=FootballDataCoUkAdapter(),
    )


class IngestPipeline:
    def __init__(self, session: Session, adapters: AdapterBundle) -> None:
        self._session = session
        self._adapters = adapters

    def ingest_fixtures(self, competition_code: str, season_start_year: int) -> int:
        if self._adapters.football_data is None:
            raise PipelineError("football-data.org adapter is not configured")
        competition = get_competition(self._session, competition_code)
        result = self._adapters.football_data.fetch_matches(
            competition_code,
            season_start_year,
        )
        persist_raw_payload(
            self._session,
            result,
            schema_version=self._adapters.football_data.schema_version,
            run_id=uuid.uuid4().hex,
        )
        matches = FootballDataOrgAdapter.parse_matches(result.payload)
        for dto in matches:
            fixture = normalize_fixture(self._session, dto, competition.id)
            upsert_match(self._session, fixture)
        return len(matches)

    def ingest_hkjc_odds(
        self,
        match: Match,
        market: MarketType,
        snapshot_kind: SnapshotKind,
        snapshot_at: datetime,
        *,
        run_id: str,
    ) -> tuple[OddsSnapshot, list[MarketLine]]:
        if self._adapters.hkjc is None:
            raise PipelineError("HKJC adapter is not configured")
        source_match_id = match.source_match_ids.get("hkjc")
        if source_match_id is None:
            raise PipelineError("match has no hkjc source id")
        result = self._adapters.hkjc.fetch_market_odds(market, source_match_id)
        raw = persist_raw_payload(
            self._session,
            result,
            schema_version=self._adapters.hkjc.schema_version,
            run_id=run_id,
        )
        payload = HkjcAdapter.parse_market_odds(result.payload, market)
        return normalize_hkjc_snapshot(
            self._session,
            match_id=match.id,
            market=market,
            payload=payload,
            snapshot_kind=snapshot_kind,
            snapshot_at=snapshot_at,
            query_version=self._adapters.hkjc.query_version,
            raw_payload_id=raw.id,
            payload_hash=result.payload_hash,
            run_id=run_id,
        )
```

- [ ] **Step 6: Implement the dry run demo**

Create `packages/ingest/dry_run.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.adapters.base import FetchResult, hash_text
from packages.db.models import MarketLine, Match, OddsSnapshot, PaperBet, Settlement, Team
from packages.domain.enums import MarketType, Side, SnapshotKind
from packages.ingest.normalize import seed_competitions
from packages.ingest.pipeline import AdapterBundle, IngestPipeline
from packages.ledger.service import INITIAL_BANKROLL, LedgerService, PlaceBetRequest

KICKOFF = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
SNAPSHOT_AT = datetime(2026, 8, 15, 13, 30, tzinfo=UTC)
SETTLED_AT = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)

DRY_RUN_FD_PAYLOAD = {
    "competition": {"code": "PL"},
    "filters": {"season": "2025"},
    "matches": [
        {
            "id": 1001,
            "utcDate": "2026-08-15T14:00:00Z",
            "status": "SCHEDULED",
            "matchday": 1,
            "homeTeam": {"id": 10, "name": "Arsenal"},
            "awayTeam": {"id": 20, "name": "Chelsea"},
            "score": {"duration": "REGULAR", "fullTime": {"home": None, "away": None}},
        }
    ],
}

DRY_RUN_HKJC_PAYLOADS = {
    MarketType.HAD: {
        "data": {
            "match": {
                "id": "HK-1001",
                "poolInfo": [
                    {
                        "poolCode": "HAD",
                        "status": "SELLINGSTARTED",
                        "updateAt": "2026-08-15T13:29:00Z",
                        "lines": [
                            {
                                "condition": "0.0",
                                "status": "AVAILABLE",
                                "isMain": True,
                                "odds": [
                                    {"side": "H", "currentOdds": "2.00"},
                                    {"side": "D", "currentOdds": "3.40"},
                                    {"side": "A", "currentOdds": "3.80"},
                                ],
                            }
                        ],
                    }
                ],
            }
        }
    },
    MarketType.HDC: {
        "data": {
            "match": {
                "id": "HK-1001",
                "poolInfo": [
                    {
                        "poolCode": "HDC",
                        "status": "SELLINGSTARTED",
                        "updateAt": "2026-08-15T13:29:00Z",
                        "lines": [
                            {
                                "condition": "-0.5",
                                "status": "AVAILABLE",
                                "isMain": True,
                                "odds": [
                                    {"side": "H", "currentOdds": "1.95"},
                                    {"side": "A", "currentOdds": "1.95"},
                                ],
                            }
                        ],
                    }
                ],
            }
        }
    },
    MarketType.HIL: {
        "data": {
            "match": {
                "id": "HK-1001",
                "poolInfo": [
                    {
                        "poolCode": "HIL",
                        "status": "SELLINGSTARTED",
                        "updateAt": "2026-08-15T13:29:00Z",
                        "lines": [
                            {
                                "condition": "2.5",
                                "status": "AVAILABLE",
                                "isMain": True,
                                "odds": [
                                    {"side": "H", "currentOdds": "1.90"},
                                    {"side": "L", "currentOdds": "1.90"},
                                ],
                            }
                        ],
                    }
                ],
            }
        }
    },
}


def _make_fetch(source_name: str, url: str, payload: dict) -> FetchResult:
    raw_text = json.dumps(payload, sort_keys=True)
    return FetchResult(
        source_name=source_name,
        source_url=url,
        fetched_at=SNAPSHOT_AT,
        http_status=200,
        payload=payload,
        payload_hash=hash_text(raw_text),
        raw_text=raw_text,
    )


class _FakeFootballData:
    schema_version = "v4"

    def fetch_matches(
        self,
        competition_code: str,
        season_start_year: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> FetchResult:
        return _make_fetch(
            "football-data.org",
            "https://fixture.local/football-data",
            DRY_RUN_FD_PAYLOAD,
        )


class _FakeHkjc:
    schema_version = "graphql-v1"
    query_version = "dry-run"

    def fetch_market_odds(
        self,
        market: MarketType,
        match_source_id: str,
    ) -> FetchResult:
        return _make_fetch(
            "hkjc",
            f"https://fixture.local/hkjc/{market.value}",
            DRY_RUN_HKJC_PAYLOADS[market],
        )


@dataclass(frozen=True)
class DryRunResult:
    match_id: str
    bet_id: str
    settlement_status: str
    payout: Decimal
    roi: Decimal
    clv: Decimal | None


def _ensure_teams(session: Session) -> None:
    existing = session.execute(
        select(Team).where(Team.slug == "arsenal")
    ).scalar_one_or_none()
    if existing is not None:
        return
    session.add_all(
        [
            Team(slug="arsenal", name="Arsenal", short_name="ARS", country="England"),
            Team(slug="chelsea", name="Chelsea", short_name="CHE", country="England"),
        ]
    )
    session.flush()


def run_dry_run(
    session: Session,
    *,
    initial_bankroll: Decimal = INITIAL_BANKROLL,
) -> DryRunResult:
    seed_competitions(session)
    _ensure_teams(session)
    pipeline = IngestPipeline(
        session,
        AdapterBundle(football_data=_FakeFootballData(), hkjc=_FakeHkjc()),
    )
    pipeline.ingest_fixtures("EPL", 2025)
    match = session.execute(select(Match)).scalar_one()
    match.source_match_ids = {**match.source_match_ids, "hkjc": "HK-1001"}
    session.flush()
    for market in (MarketType.HAD, MarketType.HDC, MarketType.HIL):
        pipeline.ingest_hkjc_odds(
            match,
            market,
            SnapshotKind.T30M,
            SNAPSHOT_AT,
            run_id=f"dry-{market.value}",
        )
    snapshot = session.execute(
        select(OddsSnapshot).where(OddsSnapshot.market == MarketType.HAD)
    ).scalar_one()
    line = session.execute(
        select(MarketLine).where(
            MarketLine.snapshot_id == snapshot.id,
            MarketLine.side == Side.H,
        )
    ).scalar_one()
    ledger = LedgerService(session, initial_bankroll=initial_bankroll)
    run_key = f"dry-run:{match.id}:HAD:H"
    existing = session.execute(
        select(PaperBet).where(PaperBet.run_key == run_key)
    ).scalar_one_or_none()
    if existing is not None:
        settlement = session.execute(
            select(Settlement).where(Settlement.paper_bet_id == existing.id)
        ).scalar_one()
        summary = ledger.summary()
        return DryRunResult(
            match_id=str(match.id),
            bet_id=str(existing.id),
            settlement_status=settlement.result_status.value,
            payout=settlement.payout,
            roi=summary.roi,
            clv=settlement.clv,
        )
    bet = ledger.place_bet(
        PlaceBetRequest(
            match_id=match.id,
            market=MarketType.HAD,
            line_key=line.condition_raw,
            selection=Side.H,
            odds_decimal=line.odds_decimal,
            stake=Decimal("100.00"),
            run_key=run_key,
            odds_snapshot_id=snapshot.id,
            placed_at=SNAPSHOT_AT,
        )
    )
    settlement = ledger.settle_paper_bet(
        bet.id,
        home_goals_90=2,
        away_goals_90=1,
        refunded_markets=frozenset(),
        payout_confirmed=True,
        hk_result_ref="dry-run-HK-1001",
        closing_odds=Decimal("1.80"),
        final_probability=Decimal("0.55"),
        settled_at=SETTLED_AT,
    )
    summary = ledger.summary()
    return DryRunResult(
        match_id=str(match.id),
        bet_id=str(bet.id),
        settlement_status=settlement.result_status.value,
        payout=settlement.payout,
        roi=summary.roi,
        clv=settlement.clv,
    )
```

- [ ] **Step 7: Implement the API, worker, and scheduler runtimes**

Create `apps/__init__.py`, `apps/api/__init__.py`, `apps/worker/__init__.py`, and `apps/scheduler/__init__.py` as empty files.

Create `apps/api/main.py`:

```python
from fastapi import FastAPI, Response
from sqlalchemy import text

from packages.db.session import build_engine
from packages.shared.config import Settings, get_settings


def create_app(
    settings: Settings | None = None,
    redis_client=None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Football Pred API", version="0.1.0")
    engine = build_engine(settings.database_url)
    app.state.engine = engine

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(response: Response) -> dict[str, str]:
        checks: dict[str, str] = {}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            checks["database"] = "up"
        except Exception:
            checks["database"] = "down"
        if redis_client is not None:
            try:
                redis_client.ping()
                checks["redis"] = "up"
            except Exception:
                checks["redis"] = "down"
        if "down" in checks.values():
            response.status_code = 503
            return {"status": "unavailable", **checks}
        return {"status": "ok", **checks}

    return app


app = create_app()
```

Create `apps/worker/main.py`:

```python
from redis import Redis
from rq import Queue, Worker

from packages.shared.config import get_settings


def build_queue() -> Queue:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    return Queue("football", connection=connection)


def main() -> None:
    Worker([build_queue()]).work()


if __name__ == "__main__":
    main()
```

Create `apps/worker/jobs.py`:

```python
from __future__ import annotations

import uuid

from sqlalchemy import select

from packages.adapters.hkjc import HkjcAdapter, HkjcMatchResult
from packages.db.models import Competition, Match, PaperBet
from packages.db.session import build_engine, build_session_factory, session_scope
from packages.domain.enums import BetStatus
from packages.ingest.pipeline import IngestPipeline, build_adapters
from packages.ledger.service import LedgerService
from packages.shared.config import Settings, get_settings
from packages.shared.time import utc_now


def run_daily_ingest() -> dict[str, int]:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        pipeline = IngestPipeline(session, build_adapters(settings))
        count = pipeline.ingest_fixtures("EPL", season_start_year=utc_now().year)
        return {"fixtures": count}


def run_match_trigger(match_id: str, trigger: str) -> dict[str, str]:
    return {"match_id": match_id, "trigger": trigger, "status": "accepted"}


def _load_hkjc_result(
    settings: Settings,
    match: Match,
) -> HkjcMatchResult | None:
    source_id = match.source_match_ids.get("hkjc")
    if source_id is None:
        return None
    adapters = build_adapters(settings)
    if adapters.hkjc is None:
        return None
    fetched = adapters.hkjc.fetch_match_results(source_id)
    return HkjcAdapter.parse_match_results(fetched.payload)


def settle_match(match_id: str) -> dict[str, int]:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        match = session.get(Match, uuid.UUID(match_id))
        if match is None:
            raise ValueError(f"unknown match {match_id}")
        result = _load_hkjc_result(settings, match)
        if result is None:
            return {"settled": 0}
        competition = session.get(Competition, match.competition_id)
        goals = HkjcAdapter.goals_90_from_result(
            result,
            settings.hkjc_result_semantics,
            is_ucl=competition.code == "UCL" if competition is not None else False,
        )
        if goals is None:
            return {"settled": 0}
        refunded = HkjcAdapter.refunded_markets(result)
        ledger = LedgerService(
            session,
            initial_bankroll=settings.initial_bankroll,
            fee_rate=settings.fee_rate,
        )
        bets = list(
            session.execute(
                select(PaperBet).where(
                    PaperBet.match_id == match.id,
                    PaperBet.status == BetStatus.PENDING,
                )
            ).scalars()
        )
        for bet in bets:
            ledger.settle_paper_bet(
                bet.id,
                home_goals_90=goals[0],
                away_goals_90=goals[1],
                refunded_markets=refunded,
                payout_confirmed=result.payout_confirmed,
                hk_result_ref=result.match_source_id,
                closing_odds=None,
                final_probability=None,
            )
        return {"settled": len(bets)}
```

Create `apps/scheduler/main.py`:

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from apps.worker.main import build_queue


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="Asia/Hong_Kong")
    queue = build_queue()

    def enqueue_daily() -> None:
        queue.enqueue("apps.worker.jobs.run_daily_ingest")

    scheduler.add_job(
        enqueue_daily,
        CronTrigger(hour=6, minute=0, timezone="Asia/Hong_Kong"),
        id="daily-ingest",
        replace_existing=True,
    )
    return scheduler


def main() -> None:
    build_scheduler().start()


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Add the dry run script**

Create `scripts/dry_run.py`:

```python
import json

from sqlalchemy import create_engine

import packages.db.models  # noqa: F401
from packages.db.base import Base
from packages.db.session import build_session_factory, session_scope
from packages.ingest.dry_run import run_dry_run


def main() -> None:
    engine = create_engine("sqlite+pysqlite:///dry_run.db")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        result = run_dry_run(session)
    print(
        json.dumps(
            {
                "match_id": result.match_id,
                "bet_id": result.bet_id,
                "settlement_status": result.settlement_status,
                "payout": str(result.payout),
                "roi": str(result.roi),
                "clv": None if result.clv is None else str(result.clv),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/ingest/test_triggers.py tests/e2e/test_dry_run.py tests/api/test_health.py -v`

Expected: `5 passed`.

- [ ] **Step 10: Run the full Phase 1 test suite**

Run: `uv run pytest -v`

Expected: all Phase 1 tests pass with no failures.

- [ ] **Step 11: Run the demo pipeline**

Run: `uv run python scripts/dry_run.py`

Expected: JSON output containing `"settlement_status": "won"`, `"payout": "200.00"`, `"roi": "1"`, and a non-null `clv` value.

- [ ] **Step 12: Verify the API and worker entry points start**

Run: `uv run python -c "from apps.api.main import create_app; app = create_app(); print(sorted(route.path for route in app.routes))"`

Expected: output includes `/healthz` and `/readyz`.

Run: `uv run python -c "from apps.worker.jobs import run_match_trigger; print(run_match_trigger('abc', 'T-30m'))"`

Expected: `{'match_id': 'abc', 'trigger': 'T-30m', 'status': 'accepted'}`.

- [ ] **Step 13: Commit**

```bash
git add packages/ingest/triggers.py packages/ingest/pipeline.py packages/ingest/dry_run.py apps scripts/dry_run.py tests/ingest/test_triggers.py tests/e2e/test_dry_run.py tests/api/test_health.py
git commit -m "feat: add scheduler, worker, api, and end-to-end dry run pipeline"
```

#### Task 12 v2.1 amendments

These amendments narrow Phase 1's decision path to EPL + HAD and replace the old `run_key` dry run.

**Pipeline decision path**

- `IngestPipeline.ingest_hkjc_odds` may still ingest HAD/HDC/HIL for data tests, but G1 only creates paper bets for `MarketType.HAD`.
- `run_dry_run` must not ingest HDC or HIL and must not create HDC/HIL bets.
- The decision snapshot is frozen at `decision_at = SNAPSHOT_AT`.
- `run_dry_run` must use the same `bet_intent_key` on every retry.

**Dry-run delta**

```python
decision_at = SNAPSHOT_AT
bet_intent_key = f"{match.id}:HAD:0.0:H"
existing = session.execute(
    select(PaperBet).where(PaperBet.bet_intent_key == bet_intent_key)
).scalar_one_or_none()
if existing is not None:
    settlement = session.execute(
        select(Settlement).where(Settlement.paper_bet_id == existing.id)
    ).scalar_one()
    summary = ledger.summary()
    return DryRunResult(
        match_id=str(match.id),
        bet_id=str(existing.id),
        settlement_status=settlement.result_status.value,
        payout=settlement.payout,
        roi=summary.roi,
        clv=settlement.clv,
    )

pipeline.ingest_hkjc_odds(
    match,
    MarketType.HAD,
    SnapshotKind.T30M,
    decision_at,
    run_id=f"dry-{MarketType.HAD.value}",
)
```

The `PlaceBetRequest` call becomes:

```python
bet = ledger.place_bet(
    PlaceBetRequest(
        match_id=match.id,
        market=MarketType.HAD,
        line_key=line.condition_raw,
        selection=Side.H,
        odds_decimal=line.odds_decimal,
        stake=Decimal("100.00"),
        analysis_run_key=f"dry-analysis:{match.id}",
        decision_slot_key=f"{match.id}:T-30m",
        bet_intent_key=bet_intent_key,
        decision_at=decision_at,
        odds_snapshot_id=snapshot.id,
    )
)
```

**Required E2E tests**

```python
def test_dry_run_produces_only_one_had_bet(session):
    result = run_dry_run(session)
    assert result.settlement_status == "won"
    assert session.query(PaperBet).count() == 1
    assert session.query(PaperBet).one().market is MarketType.HAD


def test_duplicate_worker_retry_does_not_create_second_bet(session):
    first = run_dry_run(session)
    second = run_dry_run(session)
    assert first.bet_id == second.bet_id
    assert session.query(PaperBet).count() == 1


def test_dry_run_does_not_require_llm_or_hdc_hil(session):
    result = run_dry_run(session)
    assert result.settlement_status == "won"
    assert session.query(PaperBet).one().market is MarketType.HAD
```

Run: `uv run pytest tests/e2e/test_dry_run.py -v`
Expected: 3 passed.

**G1 boundary tests**

- A worker retry with the same `bet_intent_key` returns the existing bet.
- A second decision that would exceed `cash_available` raises `InsufficientBankrollError` and leaves `paper_bets` count unchanged.
- `run_dry_run` is labelled in its docstring as engineering/settlement validation, not LLM evidence.

Run: `uv run pytest tests/e2e/test_dry_run.py tests/ledger/test_service.py -v`
Expected: all pass; no duplicate bets; no negative `cash_available`.

**Cost-cap correction**

In `packages/ingest/pipeline.py` and any future LLM shadow stub code, the cost cap stops only shadow agents. The deterministic EPL+HAD pipeline must continue.

---

## Self-Review

### Spec coverage

| Spec area | Phase 1 task |
|---|---|
| Free source inventory and provenance fields | Tasks 5 to 9, plus `raw_payloads` and `source_fetch_runs` in Task 4 |
| Canonical IDs and market semantics | Tasks 2 and 10 |
| HKJC GraphQL replay, whitelist errors, pool and line status, string odds | Task 8 |
| HKJC `condition_raw` parsing and split lines | Tasks 2 and 3 |
| HKJC regulation-time settlement, push, half win, half loss, void, 10-cent rounding | Task 3 |
| UCL result semantics gate | Task 8 |
| Refund pool shape gate | Task 8 |
| Match score separation between 90 minutes and final | Tasks 4, 5, and 10 |
| Coverage flags and stale odds | Task 10 |
| Paper bankroll, bet record, settlement record, CLV, Brier, ROI, drawdown | Task 11 |
| T-24h, T-3h, T-75m, T-30m, T-5m trigger times | Task 12 |
| Scheduler, worker, API health checks | Task 12 |
| Runnable data plus ledger demo | Task 12 |
| Rate limits and timezone rules | Tasks 1, 8, and 12 |
| Shared payoff engine and return distributions | Task 3.5 |
| Temporal fields and decision-time gates | Task 10 |
| Three-layer idempotency | Tasks 4, 11, and 12 |
| Bankroll reservation and `cash_available` | Tasks 4, 11, and 12 |
| G0/G1 phase gates and EPL+HAD first slice | Revision 2 section and Task 12 |
| Prospective vs retrospective availability | Task 10 |

### Deferred to later phases

- `features`, `models`, `agents`, `ensemble`, `value`, `risk`, `backtest` packages.
- Dixon-Coles, Elo, GBM, isotonic calibration, walk-forward validation and market baseline comparison.
- DeepSeek Flash client, LLM voters, Critic, Arbiter, prompt versions, cost caps and response caching.
- Value and Kelly sizing, exposure aggregation, hard-veto policy, and disagreement thresholds.
- Next.js dashboard, `/matches`, `/matches/[id]`, `/ledger`, `/models`, `/agents`, `/data-health`.
- `news_signals`, `model_predictions`, `agent_runs`, `calibration_metrics` tables.
- The Odds API, API-Football, FBref, Sofascore, WhoScored, and Transfermarkt adapters.
- Full news-to-match linking, weather venue lookup, and lineup inference from recent starts.
- Live query capture must still be completed by the implementer at Task 8, Step 8. UCL settlement remains blocked until the semantics gate is recorded.

### Type and signature consistency check

- `MarketType` values are used unchanged by adapters, normalization, ledger and settlement.
- `HkjcMarketLine.odds_decimal` is `Decimal`, and `MarketLine.odds_decimal` is `Numeric(10, 4)`.
- `SettlementOutcome` from Task 3 is consumed unchanged by `LedgerService.settle_paper_bet`.
- `persist_raw_payload` accepts `FetchResult` from Task 5 and returns `RawPayload` from Task 4.
- `normalize_hkjc_snapshot` consumes `HkjcOddsPayload` from Task 8 and returns `(OddsSnapshot, list[MarketLine])`.
- `build_adapters` constructs every adapter with the constructor signature defined in Tasks 5 to 9.
- `IngestPipeline.ingest_hkjc_odds` uses `self._adapters.hkjc.query_version`, which is a public attribute on `HkjcAdapter`.
- `run_dry_run` uses only ORM models and interfaces defined in Tasks 4, 10, 11 and 12.
- All money and odds fields use `Decimal` in code and `Numeric` in the database.

### Red-flag scan

- No unresolved decision markers remain in the task steps.
- Every code-changing step shows the full code needed to perform it.
- Every test step has a run command and an expected result.
- Every task lists an atomic commit step for a future execution session.
- Current execution is under an explicit no-commit override: do not run `git commit` until the user authorizes it.
- The old single `run_key`, binary HDC/HIL EV/Kelly, full `[0.01, 0.99]` clipping, split-line de-vig, and full-market G1 paths are superseded by the Revision 2 section and the Task 3.5/11/12 amendments.
