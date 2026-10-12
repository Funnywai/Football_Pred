# Football Betting Agent — Sub-system C (Paper Ledger) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the paper ledger (sub-system C) on top of the merged data layer + ML engine: one automated champion-value-bet strategy (fractional Kelly, HKD, minimum bet HKD 10 / cap 5%), automatic settlement including handicap pushes, bankroll/summary/equity-curve read-only API, and a scheduled `ledger_update` job.

**Architecture:** A new `app/services/ledger.py` service runs settle → place in one idempotent `ledger_update` job wrapped in `track_run`, writing a single `ledger_bets` table (UNIQUE `match_id × target × outcome`). Bankroll, roi, yield and the equity curve are always recomputed from bets at read time — never stored. The job joins the existing APScheduler behind `LEDGER_ENABLE`; the API adds three read endpoints in the `/predictions` style.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x (async), Alembic, FastAPI, APScheduler, pytest, mypy-less ruff. Reuses: `app/db/session.py`, `app/db/models.py`, `app/ml/labels.py`, `app/ml/features.py::MatchRow`, `app/ml/dataset.py::load_market_priors`, `app/ml/registry.py::STATUS_CHAMPION`, `app/services/runs.py::track_run`, `app/config.py`, `tests/ml_helpers.py`.

## Global Constraints

- Python >= 3.11; package manager `uv`. ruff (line-length 100) + pytest are the gates; the default test run is `-m 'not live'` (no live network).
- All ledger money is **HKD** (paper currency; no FX, no unit conversion). Minimum bet = one HKJC bet unit, **HKD 10**: `ledger_min_stake: float = 10.0`. A stake below it is **skipped, never raised up**; the cap is **downward-only** at `ledger_max_stake_fraction × batch bankroll` (default 5%). The rule applies to every market (HAD today; later markets the same).
- **Bet identity**: UNIQUE `(match_id, target, outcome)` over ALL statuses — one bet per match × target × direction, ever. Champion replacement adds new prediction rows but never a new bet (identity excludes `model_version_id`).
- **Settlement authority**: only `Result` rows with `confirmed = True`; HKJC results are never overwritten by external sources (A-layer rule, reused untouched).
- **Bankroll is derived, never stored**: `bankroll = ledger_initial_bankroll + Σ profit(settled) − Σ stake(pending)`.
- Reuse A-layer conventions verbatim: async SQLAlchemy 2.x, `UtcDateTime` (aware-UTC timestamps), idempotent upserts keyed by natural UNIQUE constraints, `track_run(session_factory, job, work)` observability, fail-soft scheduler jobs, Chinese `type: 描述` commit messages.
- Branch: work on `ledger` (based on main `04b8136`); never commit to `main` directly.

## File Structure

| Path | Responsibility |
|---|---|
| `app/config.py` | Add `LEDGER_*` settings |
| `app/db/models.py` | Add `LedgerBet` ORM (append at end; imports already complete) |
| `alembic/versions/0003_ledger_bets.py` | Migration for `ledger_bets` |
| `app/services/ledger.py` | Settlement, placement, `ledger_update` job, summary/equity read helpers |
| `app/api/schemas.py`, `app/api/routes.py`, `app/api/main.py` | Read API `/bets`, `/bets/summary`, `/bets/equity-curve` |
| `app/scheduler.py` | Wire `ledger_update` behind `LEDGER_ENABLE` |
| `tests/test_config.py`, `tests/test_migrations.py`, `tests/test_models.py` | Settings / migration / ORM tests |
| `tests/test_ledger.py`, `tests/test_ledger_api.py`, `tests/test_ledger_end_to_end.py` | Service / API / e2e tests |

---

### Task 1: `LEDGER_*` settings

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings` gains `ledger_enable: bool`, `ledger_update_interval: int`, `ledger_initial_bankroll: float`, `ledger_kelly_multiplier: float`, `ledger_max_stake_fraction: float`, `ledger_min_stake: float`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_ledger_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.ledger_enable is True
    assert settings.ledger_update_interval == 3600
    assert settings.ledger_initial_bankroll == 1000.0
    assert settings.ledger_kelly_multiplier == 0.5
    assert settings.ledger_max_stake_fraction == 0.05
    assert settings.ledger_min_stake == 10.0


def test_ledger_env_override(monkeypatch) -> None:
    monkeypatch.setenv("LEDGER_ENABLE", "false")
    monkeypatch.setenv("LEDGER_INITIAL_BANKROLL", "10000")
    monkeypatch.setenv("LEDGER_KELLY_MULTIPLIER", "0.25")
    settings = Settings(_env_file=None)
    assert settings.ledger_enable is False
    assert settings.ledger_initial_bankroll == 10000.0
    assert settings.ledger_kelly_multiplier == 0.25
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_config.py -k ledger -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'ledger_enable'`.

- [ ] **Step 3: Add the settings**

In `app/config.py`, INSIDE `Settings`, append after the ML prediction-engine block (every existing field untouched):

```python
    # Paper ledger (sub-system C)
    ledger_enable: bool = True
    ledger_update_interval: int = 3600
    ledger_initial_bankroll: float = 1000.0
    ledger_kelly_multiplier: float = 0.5
    ledger_max_stake_fraction: float = 0.05
    ledger_min_stake: float = 10.0
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (all config tests green, including the pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: 新增 Paper Ledger LEDGER_* 設定項"
```

---

### Task 2: `LedgerBet` model and migration `0003`

**Files:**
- Modify: `app/db/models.py` (append at end of file)
- Create: `alembic/versions/0003_ledger_bets.py`
- Modify: `tests/test_migrations.py`, `tests/test_models.py`

**Interfaces:**
- Consumes: `Base`, `UtcDateTime` (`app/db/models.py` already imports `Float`, `UniqueConstraint`, `func`).
- Produces: ORM class `LedgerBet` with fields `id, match_id, target, outcome, model_version_id, line, odds, stake, bankroll_at_place, edge, kelly_multiplier, result_source, status, placed_at, settled_at, payout, profit`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_migrations.py`:

```python
def test_offline_migration_creates_ledger_bets() -> None:
    script = generate_offline_sql()
    assert "CREATE TABLE ledger_bets" in script
    assert "uq_ledger_bets_natural" in script
```

In `tests/test_models.py`, first extend the existing `from datetime import date, datetime` line to:

```python
from datetime import UTC, date, datetime
```

Extend the `app.db.models` import list to include `LedgerBet` (keep the existing names), and add a new import line anywhere after the other imports:

```python
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team
```

Then append the roundtrip test:

```python
async def test_ledger_bet_roundtrip(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            match = await seed_finished_match(
                session, league, season, home, away,
                match_id_label="M1", kickoff=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                home_score=2, away_score=1,
            )
            version = ModelVersion(
                target="1x2",
                algorithm="lightgbm",
                params={},
                metrics={},
                artifact_path="/tmp/m1.joblib",
                status="champion",
            )
            session.add(version)
            await session.flush()
            session.add(
                LedgerBet(
                    match_id=match.id,
                    target="1x2",
                    outcome="H",
                    model_version_id=version.id,
                    odds=2.1,
                    stake=15.0,
                    bankroll_at_place=1000.0,
                    kelly_multiplier=0.5,
                )
            )
            await session.commit()
        async with db.session_factory() as session:
            bet = (await session.execute(select(LedgerBet))).scalar_one()
            assert bet.status == "pending"
            assert bet.outcome == "H"
            assert bet.line is None
            assert bet.stake == 15.0
            assert bet.payout is None
            assert bet.profit is None
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_migrations.py::test_offline_migration_creates_ledger_bets tests/test_models.py::test_ledger_bet_roundtrip -v`
Expected: FAIL — `ImportError: cannot import name 'LedgerBet'` and the table missing from the offline SQL.

- [ ] **Step 3: Add the ORM model**

Append at the END of `app/db/models.py` (all imports already exist in that file):

```python
class LedgerBet(Base):
    __tablename__ = "ledger_bets"
    __table_args__ = (
        UniqueConstraint("match_id", "target", "outcome", name="uq_ledger_bets_natural"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id"), nullable=False
    )
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds: Mapped[float] = mapped_column(Float, nullable=False)
    stake: Mapped[float] = mapped_column(Float, nullable=False)
    bankroll_at_place: Mapped[float] = mapped_column(Float, nullable=False)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    kelly_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    result_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    placed_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    payout: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- [ ] **Step 4: Write the migration**

Create `alembic/versions/0003_ledger_bets.py`, mirroring the style of `0002_ml_tables.py`. IMPORTANT: open `alembic/versions/0002_ml_tables.py`, copy its exact `revision` string value, and paste that value verbatim as `down_revision` below (do not guess the string):

```python
"""Paper ledger bets table

Revision ID: 0003_ledger_bets
Revises: <paste 0002's exact revision value here>
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_ledger_bets"
down_revision: str | None = "<paste 0002's exact revision value here>"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ledger_bets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column(
            "model_version_id", sa.Integer(), sa.ForeignKey("model_versions.id"), nullable=False
        ),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("odds", sa.Float(), nullable=False),
        sa.Column("stake", sa.Float(), nullable=False),
        sa.Column("bankroll_at_place", sa.Float(), nullable=False),
        sa.Column("edge", sa.Float(), nullable=True),
        sa.Column("kelly_multiplier", sa.Float(), nullable=False),
        sa.Column("result_source", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "placed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payout", sa.Float(), nullable=True),
        sa.Column("profit", sa.Float(), nullable=True),
        sa.UniqueConstraint("match_id", "target", "outcome", name="uq_ledger_bets_natural"),
    )
    op.create_index("ix_ledger_bets_match_id", "ledger_bets", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_ledger_bets_match_id", table_name="ledger_bets")
    op.drop_table("ledger_bets")
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_migrations.py tests/test_models.py -v && uv run ruff check .`
Expected: PASS (both migration tests + all model roundtrips), ruff clean.

- [ ] **Step 6: Commit**

```bash
git add app/db/models.py alembic/versions/0003_ledger_bets.py tests/test_migrations.py tests/test_models.py
git commit -m "feat: 新增 Paper Ledger 注單表與 0003 遷移"
```

---

### Task 3: Settlement (`settle_bets`)

**Files:**
- Create: `app/services/ledger.py`
- Create: `tests/test_ledger.py`

**Interfaces:**
- Consumes: `LedgerBet`, `Match`, `Result` (app.db.models); `label_1x2`, `handicap_label` (`app/ml/labels.py`); `make_db`/`seed_*` (`tests/ml_helpers.py`).
- Produces: `async settle_bets(session: AsyncSession) -> int` (later tasks import from `app.services.ledger`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ledger.py`:

```python
"""Paper ledger tests: settlement, placement, and read-time math (sub-system C)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.db.models import LedgerBet, ModelVersion, OddsSnapshot, Prediction, Result
from app.services.ledger import settle_bets
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team

KICKOFF = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


async def _db_with_result(
    tmp_path, *, home_score: int, away_score: int
) -> tuple:
    """Seed one finished match (HKJC result confirmed) + a champion; return (db, match.id)."""
    db = await make_db(tmp_path)
    async with db.session_factory() as session:
        league, season = await seed_context(session)
        home = await seed_team(session, "Home")
        away = await seed_team(session, "Away")
        match = await seed_finished_match(
            session, league, season, home, away,
            match_id_label="M1", kickoff=KICKOFF,
            home_score=home_score, away_score=away_score,
        )
        session.add(
            ModelVersion(
                target="1x2", algorithm="lightgbm", params={}, metrics={},
                artifact_path="/tmp/m1.joblib", status="champion",
            )
        )
        await session.commit()
    return db, match.id


async def _add_bet(
    db,
    match_id: int,
    *,
    target: str = "1x2",
    outcome: str = "H",
    line: float | None = None,
    odds: float = 2.1,
    stake: float = 15.0,
) -> None:
    async with db.session_factory() as session:
        version = (await session.execute(select(ModelVersion))).scalar_one()
        session.add(
            LedgerBet(
                match_id=match_id, target=target, outcome=outcome,
                model_version_id=version.id, line=line,
                odds=odds, stake=stake, bankroll_at_place=1000.0, kelly_multiplier=0.5,
            )
        )
        await session.commit()


async def _the_bet(db) -> LedgerBet:
    async with db.session_factory() as session:
        return (await session.execute(select(LedgerBet))).scalar_one()


async def test_settle_won_1x2(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, outcome="H")
    async with db.session_factory() as session:
        assert await settle_bets(session) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.status == "won"
    assert bet.payout == pytest.approx(15.0 * 2.1)
    assert bet.profit == pytest.approx(15.0 * 2.1 - 15.0)
    assert bet.settled_at is not None
    assert bet.result_source == "hkjc"


async def test_settle_lost_1x2(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, outcome="A")
    async with db.session_factory() as session:
        assert await settle_bets(session) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.status == "lost"
    assert bet.payout == 0.0
    assert bet.profit == pytest.approx(-15.0)


async def test_settle_won_handicap(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, target="handicap", outcome="H", line=-0.5)
    async with db.session_factory() as session:
        assert await settle_bets(session) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.status == "won"
    assert bet.payout == pytest.approx(15.0 * 2.1)


async def test_settle_lost_handicap(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, target="handicap", outcome="A", line=-0.5)
    async with db.session_factory() as session:
        assert await settle_bets(session) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.status == "lost"


async def test_settle_push_handicap_whole_line(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, target="handicap", outcome="H", line=-1.0)
    async with db.session_factory() as session:
        assert await settle_bets(session) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.status == "push"
    assert bet.payout == pytest.approx(15.0)
    assert bet.profit == 0.0


async def test_settle_idempotent(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, outcome="H")
    async with db.session_factory() as session:
        assert await settle_bets(session) == 1
        await session.commit()
        assert await settle_bets(session) == 0
        await session.commit()
    assert (await _the_bet(db)).status == "won"


async def test_settle_without_result_stays_pending(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, outcome="H")
    async with db.session_factory() as session:
        await session.execute(delete(Result).where(Result.match_id == match_id))
        await session.commit()
        assert await settle_bets(session) == 0
    assert (await _the_bet(db)).status == "pending"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ledger'`.

- [ ] **Step 3: Implement `app/services/ledger.py`**

```python
"""Paper ledger (sub-system C): automated staking of champion value bets.

All amounts are HKD. Bankroll is derived from the bets table, never stored.
The scheduled entry point is ``ledger_update`` (settle confirmed results,
then place new bets); both passes are idempotent.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LedgerBet, Match, Result
from app.ml.labels import handicap_label, label_1x2

logger = logging.getLogger(__name__)


async def settle_bets(session: AsyncSession) -> int:
    """Settle pending bets whose match has a confirmed result (A-layer authority).

    Only ``Result`` rows with ``confirmed = True`` settle a bet. Handicap bets
    settle via ``handicap_label``: the bet's direction wins; a whole-line push
    (``None``) returns the stake. Idempotent: settled bets are never touched
    again. Returns the number of bets settled.
    """
    stmt = (
        select(LedgerBet, Result)
        .join(Match, Match.id == LedgerBet.match_id)
        .join(Result, Result.match_id == Match.id)
        .where(LedgerBet.status == "pending")
        .where(Result.confirmed.is_(True))
    )
    rows = (await session.execute(stmt)).all()
    settled = 0
    for bet, result in rows:
        if bet.target == "handicap":
            if bet.line is None:
                logger.warning(
                    "handicap bet %s has no line; leaving it pending", bet.id
                )
                continue
            cover = handicap_label(result.home_score, result.away_score, bet.line)
            if cover is None:
                bet.status = "push"
                bet.payout = bet.stake
            elif cover == bet.outcome:
                bet.status = "won"
                bet.payout = bet.stake * bet.odds
            else:
                bet.status = "lost"
                bet.payout = 0.0
        elif label_1x2(result.home_score, result.away_score) == bet.outcome:
            bet.status = "won"
            bet.payout = bet.stake * bet.odds
        else:
            bet.status = "lost"
            bet.payout = 0.0
        bet.profit = bet.payout - bet.stake
        bet.settled_at = datetime.now(UTC)
        bet.result_source = result.source
        settled += 1
    await session.flush()
    return settled
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ledger.py -v`
Expected: PASS (all 7 settlement tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/ledger.py tests/test_ledger.py
git commit -m "feat: 新增 Paper Ledger 結算服務（讓球退本、冪等）"
```

---

### Task 4: Placement + `ledger_update` job

**Files:**
- Modify: `app/services/ledger.py` (append; also extend imports)
- Modify: `tests/test_ledger.py` (append tests; extendimports)

**Interfaces:**
- Consumes: `LedgerBet`, `Match`, `ModelVersion`, `Prediction`, `League`, `Season`; `Settings`; `load_market_priors` (`app/ml/dataset.py`, `(session, rows: list[MatchRow]) -> dict[int, MarketPrior]`); `MatchRow` (`app/ml/features.py`); `TARGET_HANDICAP` (`app/ml/models.py`, value `"handicap"`); `STATUS_CHAMPION` (`app/ml/registry.py`, value `"champion"`); `track_run(session_factory, job, work) -> int` (`app/services/runs.py`); `settle_bets` (Task 3).
- Produces: `async _bankroll_now(session, settings) -> float`; `_size_stake(bankroll_batch_start: float, recommended_fraction: float, settings) -> float | None`; `async place_bets(session, settings) -> int`; `LEDGER_JOB_ID = "ledger_update"`; `async ledger_update(session_factory, settings) -> int`.

- [ ] **Step 1: Write the failing tests**

Replace the import list at the top of `tests/test_ledger.py` with:

```python
"""Paper ledger tests: settlement, placement, and read-time math (sub-system C)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.config import Settings
from app.db.models import LedgerBet, ModelVersion, OddsSnapshot, Prediction, Result
from app.services.ledger import _size_stake, place_bets, settle_bets
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team

KICKOFF = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}
HDC = {"lines": [{"condition": "-0.5", "main": True, "combinations": [
    {"str": "H", "currentOdds": "2.0"}, {"str": "A", "currentOdds": "1.9"}]}]}
```

append (keep every Task-3 test unchanged) at the end of the file:

```python
def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_size_stake_fractional_kelly_and_cap() -> None:
    settings = _settings()
    # 6% fraction × 0.5 multiplier on HKD 1000 = HKD 30
    assert _size_stake(1000.0, 0.06, settings) == pytest.approx(30.0)
    # rounding to 2dp: 1234 × 0.05 × 0.5 = 30.85
    assert _size_stake(1234.0, 0.05, settings) == pytest.approx(30.85)
    # cap is downward-only: 25% × 0.5 = 125 > cap 50 → capped at 50
    assert _size_stake(1000.0, 0.25, settings) == pytest.approx(50.0)
    # below the HKD 10 minimum → skipped (never raised to the minimum)
    assert _size_stake(1000.0, 0.01, settings) is None
    # cap itself below the minimum (100 × 5% = 5) → skipped
    assert _size_stake(100.0, 0.6, settings) is None


async def _seed_matches_with_champion(tmp_path, *, n: int = 2) -> tuple:
    """n finished matches with HAD/HDC snapshots + one champion; return (db, match ids)."""
    db = await make_db(tmp_path)
    async with db.session_factory() as session:
        league, season = await seed_context(session)
        teams = [await seed_team(session, f"T{i}") for i in range(3)]
        match_ids = []
        for i in range(n):
            match = await seed_finished_match(
                session, league, season, teams[i % 3], teams[(i + 1) % 3],
                match_id_label=f"M{i}", kickoff=KICKOFF + timedelta(days=i),
                home_score=2, away_score=1, had_payload=HAD, hdc_payload=HDC,
            )
            match_ids.append(match.id)
        session.add(
            ModelVersion(
                target="1x2", algorithm="lightgbm", params={}, metrics={},
                artifact_path="/tmp/m1.joblib", status="champion",
            )
        )
        await session.commit()
    return db, match_ids


async def _champion_version_id(db) -> int:
    async with db.session_factory() as session:
        return (
            (await session.execute(select(ModelVersion))).scalar_one().id
        )


async def _add_prediction(
    db,
    match_id: int,
    version_id: int,
    *,
    target: str = "1x2",
    outcome: str = "H",
    market_odds: float = 2.1,
    fraction: float = 0.06,
    edge: float = 0.05,
) -> None:
    async with db.session_factory() as session:
        session.add(
            Prediction(
                match_id=match_id, target=target, outcome=outcome,
                model_version_id=version_id, prob=0.5, implied_prob=0.45,
                edge=edge, fair_odds=2.0, market_odds=market_odds,
                recommended_fraction=fraction,
            )
        )
        await session.commit()


async def test_place_sizes_and_locks_fields(tmp_path) -> None:
    db, match_ids = await _seed_matches_with_champion(tmp_path, n=1)
    version = await _champion_version_id(db)
    await _add_prediction(db, match_ids[0], version)
    async with db.session_factory() as session:
        assert await place_bets(session, _settings()) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.stake == pytest.approx(30.0)
    assert bet.odds == pytest.approx(2.1)
    assert bet.edge == pytest.approx(0.05)
    assert bet.kelly_multiplier == pytest.approx(0.5)
    assert bet.bankroll_at_place == pytest.approx(1000.0)
    assert bet.status == "pending"
    assert bet.model_version_id == version


async def test_place_handicap_locks_recomputed_line(tmp_path) -> None:
    db, match_ids = await _seed_matches_with_champion(tmp_path, n=1)
    version = await _champion_version_id(db)
    await _add_prediction(
        db, match_ids[0], version, target="handicap", outcome="A",
        market_odds=1.9, fraction=0.08,
    )
    async with db.session_factory() as session:
        assert await place_bets(session, _settings()) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.line == pytest.approx(-0.5)
    assert bet.odds == pytest.approx(1.9)


async def test_place_skips_handicap_without_line(tmp_path) -> None:
    db, match_ids = await _seed_matches_with_champion(tmp_path, n=1)
    version = await _champion_version_id(db)
    async with db.session_factory() as session:
        await session.execute(
            delete(OddsSnapshot).where(OddsSnapshot.odds_type == "HDC")
        )
        await session.commit()
    await _add_prediction(
        db, match_ids[0], version, target="handicap", outcome="A",
        market_odds=1.9, fraction=0.08,
    )
    async with db.session_factory() as session:
        assert await place_bets(session, _settings()) == 0
    async with db.session_factory() as session:
        rows = (await session.execute(select(LedgerBet))).scalars().all()
        assert rows == []


async def test_place_idempotent_and_non_champion_never_bet(tmp_path) -> None:
    db, match_ids = await _seed_matches_with_champion(tmp_path, n=2)
    version = await _champion_version_id(db)
    await _add_prediction(db, match_ids[0], version)
    await _add_prediction(db, match_ids[1], version)
    await _add_prediction(db, match_ids[0], version, outcome="D", fraction=0.0)
    async with db.session_factory() as session:
        session.add(
            ModelVersion(
                target="1x2", algorithm="lightgbm", params={}, metrics={},
                artifact_path="/tmp/m2.joblib", status="retired",
            )
        )
        await session.commit()
        retired_id = (
            (await session.execute(
                select(ModelVersion).where(ModelVersion.status == "retired")
            ))
            .scalar_one()
            .id
        )
    # a retired version's stale row on an already-bet key must not re-bet
    await _add_prediction(db, match_ids[0], retired_id)
    async with db.session_factory() as session:
        assert await place_bets(session, _settings()) == 2
        await session.commit()
        assert await place_bets(session, _settings()) == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ledger.py -v`
Expected: FAIL — `ImportError: cannot import name '_size_stake' from 'app.services.ledger'`.

- [ ] **Step 3: Implement placement and the job**

In `app/services/ledger.py`, replace the import block with:

```python
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import (
    LedgerBet,
    League,
    Match,
    ModelVersion,
    Prediction,
    Result,
    Season,
)
from app.ml.dataset import load_market_priors
from app.ml.features import MatchRow
from app.ml.labels import handicap_label, label_1x2
from app.ml.models import TARGET_HANDICAP
from app.ml.registry import STATUS_CHAMPION
from app.services.runs import track_run

logger = logging.getLogger(__name__)

LEDGER_JOB_ID = "ledger_update"
```

(keep `settle_bets` exactly as Task 3 wrote it), then append:

```python
async def _bankroll_now(session: AsyncSession, settings: Settings) -> float:
    """Derived bankroll: initial + settled profit − open stakes. Never stored."""
    settled = select(func.coalesce(func.sum(LedgerBet.profit), 0.0)).where(
        LedgerBet.status != "pending"
    )
    open_stakes = select(func.coalesce(func.sum(LedgerBet.stake), 0.0)).where(
        LedgerBet.status == "pending"
    )
    realized = (await session.execute(settled)).scalar_one()
    open_total = (await session.execute(open_stakes)).scalar_one()
    return settings.ledger_initial_bankroll + float(realized) - float(open_total)


def _size_stake(
    bankroll_batch_start: float,
    recommended_fraction: float,
    settings: Settings,
) -> float | None:
    """Fractional-Kelly stake, capped downward only. None = below HKD 10 → skip.

    Never raises a stake up to the minimum; the rule is uniform for every
    market (HAD today; any later market the same).
    """
    raw = round(
        bankroll_batch_start * recommended_fraction * settings.ledger_kelly_multiplier,
        2,
    )
    cap = settings.ledger_max_stake_fraction * bankroll_batch_start
    stake = min(raw, cap)
    if stake < settings.ledger_min_stake:
        return None
    return stake


async def place_bets(session: AsyncSession, settings: Settings) -> int:
    """Place fractional-Kelly bets on unbet champion value predictions.

    Selection: the prediction must belong to the current champion
    (``ModelVersion.status = champion``), carry ``recommended_fraction > 0``,
    and have no bet for the same ``(match_id, target, outcome)`` in any
    status. One batch shares one ``bankroll_batch_start``. Handicap bets lock
    the champion's hdc_line recomputed via ``load_market_priors`` at placement
    time and are skipped when that line is unavailable. Returns bets placed.
    """
    bankroll_batch_start = await _bankroll_now(session, settings)
    candidates = (
        (
            await session.execute(
                select(Prediction)
                .join(ModelVersion, ModelVersion.id == Prediction.model_version_id)
                .where(ModelVersion.status == STATUS_CHAMPION)
                .where(Prediction.recommended_fraction > 0)
                .order_by(Prediction.match_id, Prediction.target, Prediction.outcome)
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        return 0
    by_match: dict[int, list[Prediction]] = {}
    for prediction in candidates:
        by_match.setdefault(prediction.match_id, []).append(prediction)
    betted: set[tuple[int, str, str]] = set()
    existing_rows = (
        await session.execute(
            select(LedgerBet.match_id, LedgerBet.target, LedgerBet.outcome).where(
                LedgerBet.match_id.in_(list(by_match))
            )
        )
    ).all()
    betted = {(m, t, o) for m, t, o in existing_rows}
    lines: dict[int, float | None] = {}
    handicap_matches = [
        mid for mid, preds in by_match.items() if any(p.target == TARGET_HANDICAP for p in preds)
    ]
    if handicap_matches:
        fields = (
            await session.execute(
                select(Match, League.code, Season.label)
                .join(League, League.id == Match.league_id)
                .join(Season, Season.id == Match.season_id)
                .where(Match.id.in_(handicap_matches))
            )
        ).all()
        target_rows = [
            MatchRow(
                match_id=m.id,
                kickoff_time=m.kickoff_time,
                home_team_id=m.home_team_id,
                away_team_id=m.away_team_id,
                league_code=code,
                season_label=label,
            )
            for m, code, label in fields
        ]
        priors = await load_market_priors(session, target_rows)
        lines = {match_id: prior.hdc_line for match_id, prior in priors.items()}
    placed = 0
    for prediction in candidates:
        key = (prediction.match_id, prediction.target, prediction.outcome)
        if key in betted:
            continue
        if prediction.target == TARGET_HANDICAP:
            line = lines.get(prediction.match_id)
            if line is None:
                logger.info(
                    "skipping handicap bet on match %s: no hdc line", prediction.match_id
                )
                continue
        else:
            line = None
        if prediction.market_odds is None:
            continue
        stake = _size_stake(bankroll_batch_start, prediction.recommended_fraction, settings)
        if stake is None:
            logger.info(
                "skipping bet on match %s %s/%s: below HKD %.2f minimum",
                prediction.match_id, prediction.target, prediction.outcome,
                settings.ledger_min_stake,
            )
            continue
        session.add(
            LedgerBet(
                match_id=prediction.match_id,
                target=prediction.target,
                outcome=prediction.outcome,
                model_version_id=prediction.model_version_id,
                line=line,
                odds=prediction.market_odds,
                stake=stake,
                bankroll_at_place=bankroll_batch_start,
                edge=prediction.edge,
                kelly_multiplier=settings.ledger_kelly_multiplier,
            )
        )
        betted.add(key)
        placed += 1
    await session.flush()
    return placed


async def ledger_update(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> int:
    """Scheduled entry point: settle confirmed results, then place new bets."""

    async def work(session: AsyncSession) -> int:
        settled = await settle_bets(session)
        placed = await place_bets(session, settings)
        return settled + placed

    return await track_run(session_factory, LEDGER_JOB_ID, work)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ledger.py -v`
Expected: PASS (the 7 settlement tests + the 5 new placement/stake tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/ledger.py tests/test_ledger.py
git commit -m "feat: 新增 Paper Ledger 下注與 ledger_update 任務（fractional Kelly、防重注）"
```

---

### Task 5: Read helpers + read API

**Files:**
- Modify: `app/services/ledger.py` (append summary/equity helpers)
- Modify: `app/api/schemas.py`, `app/api/routes.py` (append)
- Modify: `app/api/main.py` (one line)
- Test: `tests/test_ledger_api.py`

**Interfaces:**
- Consumes: `summary`/`equity_curve` produced here; `SessionDep`, `router`, `aliased`, `Query`, `Request` (routes.py has all already); `create_app` sets `app.state.settings` (added in this task).
- Produces: `LedgerSummary` NamedTuple (`initial_bankroll, bankroll, n_bets, n_settled, n_open, stakes_total, open_stakes, realized_profit, roi, yield_pct`); `EquityPoint` NamedTuple (`t: datetime | None, bankroll`); schemas `BetOut`, `BetSummary`, `EquityPointOut`; routes `GET /bets`, `GET /bets/summary`, `GET /bets/equity-curve`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ledger_api.py`:

```python
"""Paper ledger read-API tests: /bets, /bets/summary, /bets/equity-curve."""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app.api.main import create_app
from app.config import Settings
from app.db.models import LedgerBet, ModelVersion
from app.services.ledger import settle_bets
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team


async def _client(db):
    app = create_app(Settings(_env_file=None), db=db)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _seed_pending_bet(tmp_path):
    """Seed one pending HKD-15 bet (outcome H) on a finished 2:1 match + champion."""
    db = await make_db(tmp_path)
    async with db.session_factory() as session:
        league, season = await seed_context(session)
        home = await seed_team(session, "Home")
        away = await seed_team(session, "Away")
        match = await seed_finished_match(
            session, league, season, home, away,
            match_id_label="M1", kickoff=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
            home_score=2, away_score=1,
        )
        version = ModelVersion(
            target="1x2", algorithm="lightgbm", params={}, metrics={},
            artifact_path="/tmp/m1.joblib", status="champion",
        )
        session.add(version)
        await session.flush()
        session.add(
            LedgerBet(
                match_id=match.id, target="1x2", outcome="H",
                model_version_id=version.id, odds=2.1, stake=15.0,
                bankroll_at_place=1000.0, kelly_multiplier=0.5,
            )
        )
        await session.commit()
    return db, match.id


async def test_bets_endpoints_empty(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with await _client(db) as client:
            response = await client.get("/bets")
            assert response.status_code == 200
            assert response.json() == []
            summary_response = await client.get("/bets/summary")
            assert summary_response.status_code == 200
            assert summary_response.json() == {
                "initial_bankroll": 1000.0, "bankroll": 1000.0, "n_bets": 0,
                "n_settled": 0, "n_open": 0, "stakes_total": 0.0,
                "open_stakes": 0.0, "realized_profit": 0.0, "roi": 0.0, "yield_pct": 0.0,
            }
            curve_response = await client.get("/bets/equity-curve")
            assert curve_response.status_code == 200
            points = curve_response.json()
            assert len(points) == 2
            assert points[0]["bankroll"] == 1000.0
            assert points[-1]["bankroll"] == 1000.0
    finally:
        await db.dispose()


async def test_bets_listing_and_summary_math(tmp_path) -> None:
    db, match_id = await _seed_pending_bet(tmp_path)
    try:
        async with db.session_factory() as session:
            assert await settle_bets(session) == 1  # 2:1 vs outcome H → won
            await session.commit()
        async with await _client(db) as client:
            bets = (await client.get("/bets")).json()
            assert len(bets) == 1
            bet = bets[0]
            assert bet["status"] == "won"
            assert bet["stake"] == 15.0
            assert bet["payout"] == pytest.approx(31.5)
            assert bet["profit"] == pytest.approx(16.5)
            assert bet["odds"] == pytest.approx(2.1)
            assert bet["home_team"] == "Home"
            assert bet["away_team"] == "Away"
            assert bet["kelly_multiplier"] == 0.5
            assert bet["bankroll_at_place"] == 1000.0

            summary = (await client.get("/bets/summary")).json()
            assert summary["initial_bankroll"] == 1000.0
            assert summary["n_bets"] == 1 and summary["n_settled"] == 1 and summary["n_open"] == 0
            assert summary["stakes_total"] == pytest.approx(15.0)
            assert summary["open_stakes"] == 0.0
            assert summary["realized_profit"] == pytest.approx(16.5)
            assert summary["bankroll"] == pytest.approx(1016.5)
            assert summary["roi"] == pytest.approx(16.5 / 15.0)
            assert summary["yield_pct"] == pytest.approx(16.5 / 15.0)

            curve = (await client.get("/bets/equity-curve")).json()
            assert len(curve) == 3  # initial + one settlement + current
            assert curve[0]["bankroll"] == 1000.0
            assert curve[-1]["bankroll"] == pytest.approx(1016.5)

            status_filtered = (
                await client.get("/bets", params={"status": "lost"})
            ).json()
            assert status_filtered == []
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ledger_api.py -v`
Expected: FAIL — 404s (`/bets*` routes missing) or import errors.

- [ ] **Step 3: Append the read helpers to `app/services/ledger.py`**

```python
class LedgerSummary(NamedTuple):
    initial_bankroll: float
    bankroll: float
    n_bets: int
    n_settled: int
    n_open: int
    stakes_total: float
    open_stakes: float
    realized_profit: float
    roi: float
    yield_pct: float


async def summary(session: AsyncSession, settings: Settings) -> LedgerSummary:
    """Aggregate every summary value from the bets table (single source of truth)."""
    rows = (
        await session.execute(select(LedgerBet.status, LedgerBet.stake, LedgerBet.profit))
    ).all()
    settled = [
        (status, stake, profit) for status, stake, profit in rows if status != "pending"
    ]
    settled_stakes = sum(stake for _, stake, _ in settled)
    open_stakes = sum(stake for status, stake, _ in rows if status == "pending")
    realized = sum(profit if profit is not None else 0.0 for _, _, profit in settled)
    stakes_total = settled_stakes + open_stakes
    return LedgerSummary(
        initial_bankroll=settings.ledger_initial_bankroll,
        bankroll=settings.ledger_initial_bankroll + realized - open_stakes,
        n_bets=len(rows),
        n_settled=len(settled),
        n_open=len(rows) - len(settled),
        stakes_total=stakes_total,
        open_stakes=open_stakes,
        realized_profit=realized,
        roi=realized / settled_stakes if settled_stakes else 0.0,
        yield_pct=realized / stakes_total if stakes_total else 0.0,
    )


class EquityPoint(NamedTuple):
    t: datetime | None
    bankroll: float


async def equity_curve(session: AsyncSession, settings: Settings) -> list[EquityPoint]:
    """Realized-wealth points: the initial bankroll, one point per settlement, final = now.

    At each settlement event the bankroll equals the initial bankroll plus
    settled profit so far, minus the stakes that are open as of that event
    (placed by then and settled strictly later, or never). Settlement events
    with the same timestamp are ordered by bet id (deterministic).
    """
    bets = (
        (
            await session.execute(select(LedgerBet).order_by(LedgerBet.placed_at, LedgerBet.id))
        )
        .scalars()
        .all()
    )
    settled = sorted(
        [bet for bet in bets if bet.status != "pending"],
        key=lambda bet: (bet.settled_at, bet.id),
    )
    points = [EquityPoint(t=None, bankroll=settings.ledger_initial_bankroll)]
    realized = 0.0
    for bet in settled:
        realized += bet.profit if bet.profit is not None else 0.0
        t_i = bet.settled_at
        open_at = sum(
            other.stake
            for other in bets
            if other.placed_at <= t_i and (other.settled_at is None or other.settled_at > t_i)
        )
        points.append(
            EquityPoint(t=t_i, bankroll=settings.ledger_initial_bankroll + realized - open_at)
        )
    points.append(
        EquityPoint(t=datetime.now(UTC), bankroll=await _bankroll_now(session, settings))
    )
    return points
```

- [ ] **Step 4: Append the API schemas**

Append to `app/api/schemas.py` (both `datetime` and `BaseModel` already imported):

```python
class BetOut(BaseModel):
    id: int
    match_id: int
    target: str
    outcome: str
    model_version_id: int
    line: float | None
    odds: float
    stake: float
    bankroll_at_place: float
    edge: float | None
    kelly_multiplier: float
    status: str
    placed_at: datetime
    settled_at: datetime | None
    payout: float | None
    profit: float | None
    kickoff_time: datetime
    league_code: str
    home_team: str
    away_team: str


class BetSummary(BaseModel):
    initial_bankroll: float
    bankroll: float
    n_bets: int
    n_settled: int
    n_open: int
    stakes_total: float
    open_stakes: float
    realized_profit: float
    roi: float
    yield_pct: float


class EquityPointOut(BaseModel):
    t: datetime | None
    bankroll: float
```

- [ ] **Step 5: Expose settings on app state**

In `app/api/main.py`, inside `create_app`, directly AFTER the `if db is not None: app.state.db = db` block and BEFORE `app.include_router(router)`, add:

```python
    app.state.settings = settings
```

(The lifespan also assigns `app.state.settings`; leave it untouched — same value, and TestClient transports used in this repo never run lifespan, so this pre-lifespan assignment is what the new endpoints rely on in tests.)

- [ ] **Step 6: Append the routes**

In `app/api/routes.py`, replace the schemas import line with the full list:

```python
from app.api.schemas import (
    BetOut,
    BetSummary,
    EquityPointOut,
    MatchOut,
    ModelOut,
    OddsOut,
    PredictionOut,
    ResultOut,
    TeamOut,
)
```

Extend the models import line by appending `LedgerBet` (it becomes
`from app.db.models import LedgerBet, League, Match, OddsSnapshot, Result, Team`), add a new import line after it:

```python
from app.services.ledger import equity_curve as ledger_equity_curve
from app.services.ledger import summary as ledger_summary
```

Then append at the end of the file (reuse the `SessionDep`, `aliased`, and `Query` patterns of `/predictions`):

```python
@router.get("/bets", response_model=list[BetOut])
async def list_bets(
    session: SessionDep,
    status: str | None = None,
    match_id: int | None = None,
    target: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[BetOut]:
    home = aliased(Team)
    away = aliased(Team)
    stmt = (
        select(LedgerBet, Match.kickoff_time, League.code, home.name_en, away.name_en)
        .join(Match, Match.id == LedgerBet.match_id)
        .join(League, League.id == Match.league_id)
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .order_by(LedgerBet.placed_at, LedgerBet.id)
        .offset(offset)
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(LedgerBet.status == status)
    if match_id is not None:
        stmt = stmt.where(LedgerBet.match_id == match_id)
    if target is not None:
        stmt = stmt.where(LedgerBet.target == target)
    rows = (await session.execute(stmt)).all()
    return [
        BetOut(
            id=bet.id,
            match_id=bet.match_id,
            target=bet.target,
            outcome=bet.outcome,
            model_version_id=bet.model_version_id,
            line=bet.line,
            odds=bet.odds,
            stake=bet.stake,
            bankroll_at_place=bet.bankroll_at_place,
            edge=bet.edge,
            kelly_multiplier=bet.kelly_multiplier,
            status=bet.status,
            placed_at=bet.placed_at,
            settled_at=bet.settled_at,
            payout=bet.payout,
            profit=bet.profit,
            kickoff_time=kickoff_time,
            league_code=league_code,
            home_team=home_name,
            away_team=away_name,
        )
        for bet, kickoff_time, league_code, home_name, away_name in rows
    ]


@router.get("/bets/summary", response_model=BetSummary)
async def bets_summary(session: SessionDep, request: Request) -> BetSummary:
    values = await ledger_summary(session, request.app.state.settings)
    return BetSummary(
        initial_bankroll=values.initial_bankroll,
        bankroll=values.bankroll,
        n_bets=values.n_bets,
        n_settled=values.n_settled,
        n_open=values.n_open,
        stakes_total=values.stakes_total,
        open_stakes=values.open_stakes,
        realized_profit=values.realized_profit,
        roi=values.roi,
        yield_pct=values.yield_pct,
    )


@router.get("/bets/equity-curve", response_model=list[EquityPointOut])
async def bets_equity_curve(
    session: SessionDep, request: Request
) -> list[EquityPointOut]:
    points = await ledger_equity_curve(session, request.app.state.settings)
    return [EquityPointOut(t=p.t, bankroll=p.bankroll) for p in points]
```

- [ ] **Step 7: Run to verify it passes**

Run: `uv run pytest tests/test_ledger_api.py tests/test_ledger.py -v && uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 8: Commit**

```bash
git add app/services/ledger.py app/api/schemas.py app/api/routes.py app/api/main.py tests/test_ledger_api.py
git commit -m "feat: 新增 Paper Ledger 唯讀 API（/bets、/bets/summary、/bets/equity-curve）"
```

---

### Task 6: Scheduler wiring

**Files:**
- Modify: `app/scheduler.py`
- Modify: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `ledger_update` (Task 4); `settings.ledger_enable`, `settings.ledger_update_interval` (Task 1). This task must NOT create a second scheduler.
- Produces: scheduler job `id="ledger_update"` (interval `settings.ledger_update_interval`, `args=[session_factory, settings]`, `max_instances=1`, `coalesce=True`) registered when `settings.ledger_enable` is true.

- [ ] **Step 1: Write the failing tests**

Replace the whole body of `tests/test_scheduler.py` with:

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
    assert set(jobs) == {"sync_odds", "settle_results", "prune_odds", "ledger_update"}
    assert jobs["sync_odds"].trigger.interval.total_seconds() == 600
    assert jobs["settle_results"].trigger.interval.total_seconds() == 900
    assert jobs["prune_odds"].trigger.__class__.__name__ == "CronTrigger"
    assert jobs["ledger_update"].trigger.interval.total_seconds() == 3600


def test_build_scheduler_without_ledger_when_disabled():
    settings = Settings(_env_file=None, ledger_enable=False)
    scheduler = build_scheduler(settings, None, _FakeProvider(), _FakeProvider())
    jobs = {job.id for job in scheduler.get_jobs()}
    assert jobs == {"sync_odds", "settle_results", "prune_odds"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: FAIL — the exact-set assertion misses `ledger_update` (the wiring does not exist yet).

- [ ] **Step 3: Wire the job**

In `app/scheduler.py`, add the import next to the other service imports:

```python
from app.services.ledger import ledger_update
```

then, in `build_scheduler`, directly after the existing ML wiring block (`if settings.ml_enable: build_ml_scheduler(...)`) and BEFORE `return scheduler`, append:

```python
    if settings.ledger_enable:
        scheduler.add_job(
            ledger_update,
            "interval",
            seconds=settings.ledger_update_interval,
            args=[session_factory, settings],
            id="ledger_update",
            max_instances=1,
            coalesce=True,
        )
```

(Still the SAME scheduler instance — never a second one.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_scheduler.py tests/test_ml_jobs.py -v`
Expected: PASS — the 4-job default set and the disabled case; the ML scheduler tests unaffected.

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: 新增 ledger_update 排程任務接線（LEDGER_ENABLE 控制）"
```

---

### Task 7: End-to-end test and quality gates

**Files:**
- Create: `tests/test_ledger_end_to_end.py`

**Interfaces:**
- Consumes: everything above; the B-loop (`build_dataset` → `train_1x2` → `save_artifact` → `register_challenger` → `maybe_promote` → `load_champion` → `load_upcoming_matches` → `predict_match` → `upsert_predictions`).

- [ ] **Step 1: Write the end-to-end test**

Create `tests/test_ledger_end_to_end.py`:

```python
"""Sub-system C end-to-end: champion predictions → bets → settlement → summary."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models import LedgerBet, ModelVersion, Prediction
from app.ml.dataset import build_dataset
from app.ml.models import TARGET_1X2, save_artifact, train_1x2
from app.ml.predict import (
    load_champion,
    load_upcoming_matches,
    predict_match,
    upsert_predictions,
)
from app.ml.registry import maybe_promote, register_challenger
from app.services.ledger import equity_curve, ledger_update
from app.services.ledger import summary as ledger_summary
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team

HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}
HDC = {"lines": [{"condition": "-0.5", "main": True, "combinations": [
    {"str": "H", "currentOdds": "2.0"}, {"str": "A", "currentOdds": "1.9"}]}]}


async def _value_prediction_keys(db) -> set[tuple[int, str, str]]:
    """Champion predictions with a Kelly fraction (the exact set placement must bet)."""
    async with db.session_factory() as session:
        champion = (
            await session.execute(select(ModelVersion).where(ModelVersion.status == "champion"))
        ).scalar_one()
        rows = (
            (
                await session.execute(
                    select(Prediction).where(
                        Prediction.model_version_id == champion.id,
                        Prediction.recommended_fraction > 0,
                    )
                )
            )
            .scalars()
            .all()
        )
        return {(row.match_id, row.target, row.outcome) for row in rows}


async def test_end_to_end_predict_place_settle(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        settings = Settings(
            _env_file=None,
            ml_min_train_rows=20,
            ml_history_from_year=2020,
            ml_value_edge_threshold=0.0,
            ml_artifact_dir=str(tmp_path / "artifacts"),
        )
        base = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            teams = [await seed_team(session, f"T{i}") for i in range(6)]
            for index in range(60):
                await seed_finished_match(
                    session, league, season, teams[index % 6], teams[(index + 1) % 6],
                    match_id_label=f"M{index}", kickoff=base + timedelta(days=index),
                    home_score=index % 4, away_score=(index + 1) % 3,
                    had_payload=HAD, hdc_payload=HDC,
                )
            upcoming = await seed_finished_match(
                session, league, season, teams[0], teams[1],
                match_id_label="M_UP", kickoff=base + timedelta(days=90),
                home_score=0, away_score=0,
            )
            upcoming.status = "scheduled"
            await session.commit()
            upcoming_id = upcoming.id

        async with db.session_factory() as session:
            dataset = await build_dataset(session, settings)
            model = train_1x2(dataset.train, dataset.calibration, dataset.eval)
            artifact = tmp_path / "champ.joblib"
            save_artifact(model, artifact)
            version = await register_challenger(
                session, TARGET_1X2, "lightgbm", {}, model.metrics, str(artifact)
            )
            await maybe_promote(session, version, 0.0)
            await session.commit()

        async with db.session_factory() as session:
            champion = await load_champion(session, TARGET_1X2)
            assert champion is not None
            now = base + timedelta(days=89)
            matches = await load_upcoming_matches(session, settings, now)
            assert len(matches) == 1
            rows = await predict_match(session, matches[0], champion, None, settings)
            written = await upsert_predictions(session, rows)
            await session.commit()
            assert written == 3

        expected = await _value_prediction_keys(db)

        # Run 1: settle(nothing pending) + place
        async with db.session_factory() as session:
            processed = await ledger_update(db.session_factory, settings)
        async with db.session_factory() as session:
            bets = (await session.execute(select(LedgerBet))).scalars().all()
            assert {b.model_version_id for b in bets} == {await _champion_id(db)}
            assert {(b.match_id, b.target, b.outcome) for b in bets} == expected
            assert processed == len(bets)
            for bet in bets:
                assert 10.0 <= bet.stake <= 0.05 * 1000.0
                assert bet.status == "pending"
                assert bet.kelly_multiplier == pytest.approx(0.5)
                assert bet.bankroll_at_place == pytest.approx(1000.0)
        # Run 2: the confirmed 0:0 result settles every pending bet (D wins; H/A
        # lose) and placement stays idempotent — settled N, placed 0.
        async with db.session_factory() as session:
            processed = await ledger_update(db.session_factory, settings)
        async with db.session_factory() as session:
            bets = (await session.execute(select(LedgerBet))).scalars().all()
            for bet in bets:
                assert bet.status == ("won" if bet.outcome == "D" else "lost")
                assert bet.result_source == "hkjc"
                assert bet.settled_at is not None
            assert processed == len(bets)  # settled everything, placed nothing
            values = await ledger_summary(session, settings)
            realized = sum(bet.profit if bet.profit is not None else 0.0 for bet in bets)
            assert values.realized_profit == pytest.approx(realized)
            assert values.bankroll == pytest.approx(1000.0 + realized)
            assert values.n_settled == len(bets)
            assert values.n_open == 0
            curve = [p.bankroll for p in await equity_curve(session, settings)]
            assert len(curve) == len(bets) + 2  # initial + one event per bet + current
            assert curve[0] == 1000.0
            assert curve[-1] == pytest.approx(1000.0 + realized)

        # Run 3: steady state — fully idempotent, nothing left to do.
        async with db.session_factory() as session:
            assert await ledger_update(db.session_factory, settings) == 0
    finally:
        await db.dispose()


async def _champion_id(db) -> int:
    async with db.session_factory() as session:
        return (
            (
                await session.execute(
                    select(ModelVersion).where(ModelVersion.status == "champion")
                )
            )
            .scalar_one()
            .id
        )
```

NOTES for the implementer (pre-resolved decisions):
- `ml_value_edge_threshold=0.0` keeps nonzero value bets highly likely while staying fully deterministic; the exact bet set is asserted via `_value_prediction_keys` computed from the DB — never predicted. If `expected` is empty, the test still passes: it asserts identity/consistency, not a minimum bet count; the exact-count behaviour is locked by Task 4's deterministic tests.
- The upcoming match is seeded via `seed_finished_match` (its confirmed 0:0 result already exists) with `status` flipped to `scheduled`. Intentional: Run 1 settles nothing only because no pending bets exist yet; Run 2 settles the just-placed bets (D wins the draw) while proving placement never re-bets; Run 3 is the steady state. This exercises settle-before-place, placement immutability, and settlement states without surgery on the seed helpers.

- [ ] **Step 2: Run the end-to-end test**

Run: `uv run pytest tests/test_ledger_end_to_end.py -v`
Expected: PASS (it trains real LightGBM — allow some seconds).

- [ ] **Step 3: Run the full suite and lint**

Run: `uv run pytest && uv run ruff check .`
Expected: all tests pass (live deselected; 121 existing + new tests), ruff clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_ledger_end_to_end.py
git commit -m "test: 新增 Paper Ledger 端到端迴路（預測→下注→結算→績效）"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Task(s) |
|---|---|
| §2 In: automated champion strategy / settlement / summary+equity / scheduler+track_run | Tasks 4, 3, 5, 6 |
| §3 Q1 fully automated, read-only API | Tasks 4 (`ledger_update`), 5 (no POST routes) |
| §3 Q2 fractional Kelly + HKD 10 min skip / 5% cap / batch bankroll | Task 4 (`_size_stake`, batch start) |
| §3 Q3 champion strategy only | Task 4 (champion-join selection only) |
| §3 Q4 odds locked at prediction; bets immutable | Task 4 (`odds = prediction.market_odds`, dedupe first-wins) |
| §3 Q5 delivery surface | Tasks 2–5 (tables + service + API), 6 (scheduler) |
| §3 Q6 independent scheduled job | Task 6 |
| §5 data model + derivations | Tasks 2 (table), 4 (`_bankroll_now`), 5 (`summary`, `equity_curve`) |
| §6 placement rules + defaults + skip/cap mechanics | Tasks 1, 4 |
| §7 settlement rules | Task 3 |
| §8 three read endpoints | Task 5 |
| §9 error handling/observability (track_run, fail-soft, single writer) | Tasks 4, 6 |
| §10 success metrics (reproducibility, settlement completeness, hand-checkable summary) | Tasks 4 (audit columns), 3 (push/idempotent), 5+7 (summary math from bets) |
| §11 testing plan (unit/integration/e2e/scheduler) | Tasks 3, 4, 5, 6, 7 |
| §12 risks (min-stake skip protects low bankroll — cap note) | Task 4 (cap + skip logic + test) |

**2. Placeholder scan:** The only non-code text in code blocks is Task 2's `down_revision` slot, which carries an EXACT mechanical instruction (copy 0002's revision value; the value differs from what the old B plan snippet guessed, so pinning it to the repo's real value is deliberate). Every other step carries complete code. No "TBD"/"TODO"/"appropriate"/"handle edge cases".

**3. Type/name consistency:** `settle_bets` (T3) is imported by the T4 and T5 test files and used by `ledger_update` (T4); `_bankroll_now` (T4) is reused by `equity_curve` (T5); `_size_stake` (T4) private but imported by tests — names stable across tasks. `STATUS_CHAMPION`/`TARGET_HANDICAP` come from B (`app.ml.registry` / `app.ml.models`) exactly as produced by B Tasks 8–9. `track_run(session_factory, job, work)` matches A's signature. Schemas (`BetOut`, `BetSummary`, `EquityPointOut`) match T5 route constructor args 1:1. `NamedTuple` import (typing) is added in T4's import block and used in T5. `async_sessionmaker` import added in T4. `pytest.approx` used in T5 tests — the test file includes `import pytest`. The equity/summary helpers live in `app/services/ledger.py` and are imported in routes with `as`-aliases to avoid shadowing; the equity helper is a module function `equity_curve` (not the route name), and route functions are `list_bets`/`bets_summary`/`bets_equity_curve`.

**4. Definition of done:** `uv run pytest` green (live deselected; ≥121 existing pass + all new), `uv run ruff check .` clean; `alembic upgrade head` applies `0003_ledger_bets`; with default settings the scheduler registers `ledger_update` (4 jobs) and with `LEDGER_ENABLE=false` it does not; a seeded champion prediction with `recommended_fraction > 0` lands as a `pending` bet ≥ HKD 10 within one `ledger_update` run, and settles automatically (push included) once a confirmed result exists.