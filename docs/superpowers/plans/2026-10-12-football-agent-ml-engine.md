# Football Betting Agent — Sub-system B (Prediction Engine v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the ML prediction engine (sub-system B) on top of the existing data layer: as-of-kickoff feature building, LightGBM 1X2 + Asian-handicap models with isotonic calibration, de-vig value detection, a champion/challenger model registry, scheduled predict + retrain jobs, and read endpoints — all versioned, reproducible, and leakage-safe.

**Architecture:** A new `app/ml/` package inside the existing FastAPI repo. It reads from the A-layer Postgres tables via async SQLAlchemy, builds leakage-safe feature frames in one chronological pass, trains LightGBM models with per-class isotonic calibration on a temporal split, evaluates against the market (Brier/log-loss) and the closing line (CLV), and stores versioned artifacts + metrics in `model_versions`. A `champion` model serves predictions into `predictions`; a scheduled retrain builds a `challenger` and only promotes it if it is at least `ML_CHAMPION_MARGIN` better on Brier (and CLV not worse). Jobs reuse the A-layer APScheduler; training runs off the event loop.

**Tech Stack:** Python 3.11+, LightGBM, scikit-learn (isotonic), pandas, numpy, joblib, SQLAlchemy 2.x (async), Alembic, pytest. Reuses: `app/db/session.py`, `app/db/base.py`, `app/db/models.py`, `app/services/runs.py`, `app/config.py`, `app/scheduler.py`, `app/api/`.

## Global Constraints

- Python >= 3.11; package manager `uv`.
- Reuse the A-layer conventions verbatim: async SQLAlchemy 2.x, the `UtcDateTime` type (all timestamps aware-UTC), `_json_type()` (JSONB with `.with_variant(JSON,"sqlite")`) for JSON columns, idempotent upserts keyed by natural UNIQUE constraints, `track_run(session_factory, job, work)` for job observability, Chinese `type: 描述` commit messages.
- **Leakage safety**: every feature row for a match must use only data from matches/odds with kickoff/capture strictly before that match. `build_feature_rows` is leakage-safe by construction (state accumulates only from earlier kickoff groups).
- **No live network in the default test run** (`-m 'not live'`); tests use synthetic data or tmp SQLite.
- ruff (line-length 100) + pytest are the gates. macOS: `lightgbm` requires `libomp` (`brew install libomp`).
- **One champion per target**: enforced in code (`promote` demotes the current champion in the same transaction) and by a partial unique index (`status = 'champion'`).
- Do NOT touch branch `main`.

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Add ML dependencies |
| `app/config.py` | Add `ML_*` settings |
| `app/db/models.py` | Add `ModelVersion`, `Prediction`, `MatchFeature` |
| `alembic/versions/0002_ml_tables.py` | Migration for the three tables + champion partial index |
| `app/ml/__init__.py` | Package marker |
| `app/ml/labels.py` | 1X2 + handicap label derivation, line parsing |
| `app/ml/deviq.py` | Odds de-vigging |
| `app/ml/value.py` | Edge, fair odds, Kelly fraction, CLV metrics |
| `app/ml/features.py` | Leakage-safe feature builder + HKJC/football-data payload parsers |
| `app/ml/dataset.py` | DB → feature frame → temporal split |
| `app/ml/models.py` | LightGBM train + isotonic calibration, eval, artifact I/O |
| `app/ml/registry.py` | Champion/challenger gate, promote, rollback |
| `app/ml/predict.py` | Champion serving → upsert `predictions` |
| `app/ml/jobs.py` | `predict_upcoming`, `retrain` (training off-loop) |
| `app/scheduler.py` | Wire the ML jobs |
| `app/api/schemas.py`, `app/api/routes.py` | `GET /predictions`, `GET /models` |
| `tests/test_ml_*.py`, `tests/ml_helpers.py` | Tests |

---

### Task 1: Dependencies and `ML_*` settings

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings` gains `ml_enable: bool`, `ml_1x2_model: str`, `ml_handicap_model: str`, `ml_value_edge_threshold: float`, `ml_retrain_interval: int`, `ml_predict_lookahead_hours: int`, `ml_min_train_rows: int`, `ml_artifact_dir: str`, `ml_champion_margin: float`, `ml_history_from_year: int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_ml_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.ml_enable is False
    assert settings.ml_1x2_model == "lightgbm"
    assert settings.ml_handicap_model == "lightgbm"
    assert settings.ml_value_edge_threshold == 0.02
    assert settings.ml_retrain_interval == 604800
    assert settings.ml_predict_lookahead_hours == 48
    assert settings.ml_min_train_rows == 500
    assert settings.ml_artifact_dir == "artifacts/ml"
    assert settings.ml_champion_margin == 0.0
    assert settings.ml_history_from_year == 2010


def test_ml_env_override(monkeypatch) -> None:
    monkeypatch.setenv("ML_ENABLE", "true")
    monkeypatch.setenv("ML_VALUE_EDGE_THRESHOLD", "0.05")
    monkeypatch.setenv("ML_RETRAIN_INTERVAL", "3600")
    settings = Settings(_env_file=None)
    assert settings.ml_enable is True
    assert settings.ml_value_edge_threshold == 0.05
    assert settings.ml_retrain_interval == 3600
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_config.py -k ml -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'ml_enable'`.

- [ ] **Step 3: Add dependencies and settings**

In `pyproject.toml`, add to the `dependencies` list:

```toml
    "lightgbm>=4.3",
    "scikit-learn>=1.5",
    "pandas>=2.2",
    "numpy>=1.26",
    "joblib>=1.4",
```

In `app/config.py`, add these fields to `Settings` (after the existing data-layer fields, keeping every existing field unchanged):

```python
    # ML prediction engine (sub-system B)
    ml_enable: bool = False
    ml_1x2_model: str = "lightgbm"
    ml_handicap_model: str = "lightgbm"
    ml_value_edge_threshold: float = 0.02
    ml_retrain_interval: int = 604800
    ml_predict_lookahead_hours: int = 48
    ml_min_train_rows: int = 500
    ml_artifact_dir: str = "artifacts/ml"
    ml_champion_margin: float = 0.0
    ml_history_from_year: int = 2010
```

- [ ] **Step 4: Install and run to verify it passes**

Run: `uv sync && uv run pytest tests/test_config.py -v`
Expected: PASS (all config tests green).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/config.py tests/test_config.py uv.lock
git commit -m "feat: 新增 ML 引擎依賴與 ML_* 設定項"
```

---

### Task 2: DB models and migration `0002`

**Files:**
- Modify: `app/db/models.py`
- Create: `alembic/versions/0002_ml_tables.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Consumes: `Base`, `UtcDateTime` (`app/db/base.py`); `_json_type()` helper (already in `app/db/models.py`).
- Produces: ORM classes `ModelVersion`, `Prediction`, `MatchFeature`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_migrations.py`:

```python
def test_offline_migration_creates_ml_tables() -> None:
    script = generate_offline_sql()
    for table in ("model_versions", "predictions", "match_features"):
        assert f"CREATE TABLE {table}" in script
    assert "uq_predictions_natural" in script
    assert "uq_match_features_natural" in script
    assert "uq_model_versions_champion_target" in script
```

(`generate_offline_sql` is the existing helper in that file; reuse it.)

Add a model smoke test to `tests/test_models.py`:

```python
async def test_ml_models_create_and_roundtrip(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with db.session_factory() as session:
            session.add(
                ModelVersion(
                    target="1x2",
                    algorithm="lightgbm",
                    params={"n": 1},
                    metrics={"brier": 0.2},
                    artifact_path="/tmp/m1.joblib",
                    status="challenger",
                )
            )
            await session.commit()
        async with db.session_factory() as session:
            version = (await session.execute(select(ModelVersion))).scalar_one()
            assert version.status == "challenger"
            assert version.metrics["brier"] == 0.2
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_migrations.py::test_offline_migration_creates_ml_tables tests/test_models.py::test_ml_models_create_and_roundtrip -v`
Expected: FAIL — `ModelVersion` not defined / tables missing.

- [ ] **Step 3: Add the ORM models**

In `app/db/models.py`, extend the imports to include `Float`, `Index`, and `text`:

```python
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
```

Then append the three models:

```python
class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        Index(
            "uq_model_versions_champion_target",
            "target",
            unique=True,
            postgresql_where=text("status = 'champion'"),
            sqlite_where=text("status = 'champion'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    algorithm: Mapped[str] = mapped_column(String(40), nullable=False)
    params: Mapped[dict] = mapped_column(_json_type(), nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(_json_type(), nullable=False, default=dict)
    artifact_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="challenger")
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    promoted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "target", "outcome", "model_version_id", name="uq_predictions_natural"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id"), nullable=False
    )
    prob: Mapped[float] = mapped_column(Float, nullable=False)
    implied_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    fair_odds: Mapped[float] = mapped_column(Float, nullable=False)
    market_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommended_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )


class MatchFeature(Base):
    __tablename__ = "match_features"
    __table_args__ = (
        UniqueConstraint("match_id", "feature_version", name="uq_match_features_natural"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    feature_version: Mapped[str] = mapped_column(String(40), nullable=False)
    built_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    features: Mapped[dict] = mapped_column(_json_type(), nullable=False, default=dict)
```

- [ ] **Step 4: Write the migration**

Create `alembic/versions/0002_ml_tables.py` (mirror the style of `0001_initial_schema.py`; use `sa.DateTime(timezone=True)` for timestamps and `postgresql.JSONB` for JSON):

```python
"""ML tables

Revision ID: 0002_ml_tables
Revises: 0001_initial_schema
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_ml_tables"
down_revision: str | None = "0001_initial_schema"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("algorithm", sa.String(length=40), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("artifact_path", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_model_versions_target", "model_versions", ["target"])
    op.create_index(
        "uq_model_versions_champion_target",
        "model_versions",
        ["target"],
        unique=True,
        postgresql_where=sa.text("status = 'champion'"),
        sqlite_where=sa.text("status = 'champion'"),
    )

    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column(
            "model_version_id", sa.Integer(), sa.ForeignKey("model_versions.id"), nullable=False
        ),
        sa.Column("prob", sa.Float(), nullable=False),
        sa.Column("implied_prob", sa.Float(), nullable=True),
        sa.Column("edge", sa.Float(), nullable=True),
        sa.Column("fair_odds", sa.Float(), nullable=False),
        sa.Column("market_odds", sa.Float(), nullable=True),
        sa.Column("recommended_fraction", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "match_id", "target", "outcome", "model_version_id", name="uq_predictions_natural"
        ),
    )
    op.create_index("ix_predictions_match_id", "predictions", ["match_id"])

    op.create_table(
        "match_features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("feature_version", sa.String(length=40), nullable=False),
        sa.Column(
            "built_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("features", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("match_id", "feature_version", name="uq_match_features_natural"),
    )
    op.create_index("ix_match_features_match_id", "match_features", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_match_features_match_id", table_name="match_features")
    op.drop_table("match_features")
    op.drop_index("ix_predictions_match_id", table_name="predictions")
    op.drop_table("predictions")
    op.drop_index("uq_model_versions_champion_target", table_name="model_versions")
    op.drop_index("ix_model_versions_target", table_name="model_versions")
    op.drop_table("model_versions")
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_migrations.py tests/test_models.py -v && uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add app/db/models.py alembic/versions/0002_ml_tables.py tests/test_migrations.py tests/test_models.py
git commit -m "feat: 新增 ML 資料表（model_versions/predictions/match_features）與 0002 遷移"
```

---

### Task 3: Labels (`app/ml/labels.py`)

**Files:**
- Create: `app/ml/__init__.py`, `app/ml/labels.py`
- Test: `tests/test_ml_labels.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `label_1x2(home_score: int, away_score: int) -> str`; `parse_handicap_line(condition: str | None) -> float | None`; `is_whole_or_half(line: float) -> bool`; `handicap_label(home_score: int, away_score: int, line: float) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ml_labels.py`:

```python
import pytest

from app.ml.labels import (
    handicap_label,
    is_whole_or_half,
    label_1x2,
    parse_handicap_line,
)


def test_label_1x2() -> None:
    assert label_1x2(2, 1) == "H"
    assert label_1x2(1, 1) == "D"
    assert label_1x2(0, 3) == "A"


def test_parse_handicap_line() -> None:
    assert parse_handicap_line("-1") == -1.0
    assert parse_handicap_line("+0.5") == 0.5
    assert parse_handicap_line("0") == 0.0
    assert parse_handicap_line("-0.25") == -0.25
    assert parse_handicap_line(None) is None
    assert parse_handicap_line("") is None
    assert parse_handicap_line("n/a") is None


def test_is_whole_or_half() -> None:
    assert is_whole_or_half(0.0)
    assert is_whole_or_half(-1.0)
    assert is_whole_or_half(0.5)
    assert is_whole_or_half(-1.5)
    assert not is_whole_or_half(-0.25)
    assert not is_whole_or_half(0.75)


def test_handicap_label() -> None:
    assert handicap_label(2, 1, -0.5) == "H"
    assert handicap_label(1, 1, -0.5) == "A"
    assert handicap_label(3, 1, -1.0) == "H"
    assert handicap_label(2, 1, -1.0) is None  # push on a whole line
    assert handicap_label(2, 1, -1.25) is None  # quarter line skipped in v1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ml_labels.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ml'`.

- [ ] **Step 3: Implement**

Create `app/ml/__init__.py`:

```python
"""ML prediction engine (sub-system B)."""
```

Create `app/ml/labels.py`:

```python
"""Label derivation for the ML prediction engine (1X2 and Asian handicap)."""

from __future__ import annotations

QUARTER_EPSILON = 1e-9


def label_1x2(home_score: int, away_score: int) -> str:
    """Return "H", "D" or "A" for a final score."""
    if home_score > away_score:
        return "H"
    if home_score < away_score:
        return "A"
    return "D"


def parse_handicap_line(condition: str | None) -> float | None:
    """Parse an HKJC HDC ``condition`` string (e.g. "-1", "+0.5", "0") into a float."""
    if condition is None:
        return None
    text = condition.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def is_whole_or_half(line: float) -> bool:
    """True for whole (0, -1) and half (-0.5, +1.5) lines; False for quarter lines."""
    doubled = line * 2.0
    return abs(doubled - round(doubled)) < QUARTER_EPSILON


def handicap_label(home_score: int, away_score: int, line: float) -> str | None:
    """Home-cover label for the main line.

    Returns "H" when the home side covers, "A" when the away side covers, and
    ``None`` when the match is skipped: quarter lines (v1 simplification) and
    whole-line pushes (net == line).
    """
    if not is_whole_or_half(line):
        return None
    net = home_score - away_score
    if net > line:
        return "H"
    if net < line:
        return "A"
    return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ml_labels.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ml/__init__.py app/ml/labels.py tests/test_ml_labels.py
git commit -m "feat: 新增 1X2 與讓球標籤推導模組"
```

---

### Task 4: De-vig (`app/ml/deviq.py`)

**Files:**
- Create: `app/ml/deviq.py`
- Test: `tests/test_ml_deviq.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `implied_probs(odds: Sequence[float]) -> list[float]`; `overround(odds: Sequence[float]) -> float`; `devig_multiplicative(odds: Sequence[float]) -> list[float]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ml_deviq.py`:

```python
import pytest

from app.ml.deviq import devig_multiplicative, implied_probs, overround


def test_implied_probs() -> None:
    assert implied_probs([2.0, 4.0]) == [0.5, 0.25]


def test_implied_probs_rejects_nonpositive() -> None:
    with pytest.raises(ValueError):
        implied_probs([0.0])


def test_overround_and_devig() -> None:
    odds = [2.1, 3.4, 3.8]
    assert overround(odds) > 1.0
    fair = devig_multiplicative(odds)
    assert len(fair) == 3
    assert abs(sum(fair) - 1.0) < 1e-9
    # favourite keeps the largest fair probability
    assert fair.index(max(fair)) == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ml_deviq.py -v`
Expected: FAIL — `No module named 'app.ml.deviq'`.

- [ ] **Step 3: Implement**

Create `app/ml/deviq.py`:

```python
"""Odds de-vigging (multiplicative method, v1)."""

from __future__ import annotations

from collections.abc import Sequence


def implied_probs(odds: Sequence[float]) -> list[float]:
    """Raw implied probabilities ``1 / odds`` (they sum to the overround)."""
    probs: list[float] = []
    for value in odds:
        if value <= 0:
            raise ValueError(f"odds must be positive, got {value!r}")
        probs.append(1.0 / value)
    return probs


def overround(odds: Sequence[float]) -> float:
    """Sum of raw implied probabilities (>= 1 for a real book)."""
    return sum(implied_probs(odds))


def devig_multiplicative(odds: Sequence[float]) -> list[float]:
    """Remove the overround multiplicatively so fair probabilities sum to 1."""
    implied = implied_probs(odds)
    total = sum(implied)
    if total <= 0:
        raise ValueError("implied probability sum must be positive")
    return [value / total for value in implied]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ml_deviq.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ml/deviq.py tests/test_ml_deviq.py
git commit -m "feat: 新增賠率去水模組"
```

---

### Task 5: Value detection (`app/ml/value.py`)

**Files:**
- Create: `app/ml/value.py`
- Test: `tests/test_ml_value.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `edge(model_prob: float, fair_prob: float) -> float`; `fair_odds(model_prob: float) -> float`; `is_value(edge_value: float, threshold: float) -> bool`; `kelly_fraction(model_prob: float, odds: float) -> float`; `clv_metrics(model_probs_by_match: dict[int, dict[str, float]], closing_probs_by_match: dict[int, dict[str, float]]) -> dict[str, float | int | None]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ml_value.py`:

```python
import pytest

from app.ml.value import clv_metrics, edge, fair_odds, is_value, kelly_fraction


def test_edge_and_fair_odds() -> None:
    assert edge(0.5, 0.45) == pytest.approx(0.05)
    assert fair_odds(0.5) == pytest.approx(2.0)
    assert fair_odds(0.0) == float("inf")


def test_is_value() -> None:
    assert is_value(0.03, 0.02)
    assert not is_value(0.02, 0.02)  # strictly greater


def test_kelly_fraction() -> None:
    # even odds, true prob 0.6 -> f = (1*0.6 - 0.4)/1 = 0.2
    assert kelly_fraction(0.6, 2.0) == pytest.approx(0.2)
    assert kelly_fraction(0.4, 2.0) == 0.0  # no edge -> no stake
    assert kelly_fraction(0.5, 1.0) == 0.0  # b <= 0


def test_clv_metrics() -> None:
    model = {1: {"H": 0.5, "D": 0.3, "A": 0.2}}
    closing = {1: {"H": 0.45, "D": 0.32, "A": 0.23}}
    metrics = clv_metrics(model, closing)
    assert metrics["n"] == 3
    assert metrics["clv_fraction"] == pytest.approx(1 / 3)  # H beats, D/A don't
    assert clv_metrics({1: {"H": 0.5}}, {})["clv_fraction"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ml_value.py -v`
Expected: FAIL — `No module named 'app.ml.value'`.

- [ ] **Step 3: Implement**

Create `app/ml/value.py`:

```python
"""Value detection: edge, fair odds, Kelly fraction, CLV metrics."""

from __future__ import annotations


def edge(model_prob: float, fair_prob: float) -> float:
    """Model probability minus the de-vigged market probability."""
    return model_prob - fair_prob


def fair_odds(model_prob: float) -> float:
    """Decimal odds implied by the model probability (inf when prob <= 0)."""
    if model_prob <= 0:
        return float("inf")
    return 1.0 / model_prob


def is_value(edge_value: float, threshold: float) -> bool:
    """A value bet is flagged when the edge strictly exceeds the threshold."""
    return edge_value > threshold


def kelly_fraction(model_prob: float, odds: float) -> float:
    """Kelly stake fraction ``f = (b*p - q) / b`` clamped to [0, 1]."""
    b = odds - 1.0
    if b <= 0:
        return 0.0
    p = min(max(model_prob, 0.0), 1.0)
    q = 1.0 - p
    fraction = (b * p - q) / b
    return min(max(fraction, 0.0), 1.0)


def clv_metrics(
    model_probs_by_match: dict[int, dict[str, float]],
    closing_probs_by_match: dict[int, dict[str, float]],
) -> dict[str, float | int | None]:
    """Beat-the-closing-line metrics over matches present in both mappings.

    For every outcome shared by a match's model probabilities and its HKJC
    closing de-vigged probabilities, the model "beats the close" when
    ``model_prob >= closing_prob``. Returns the beat fraction, the mean edge and
    the number of comparisons; ``None``/0 when no match has closing data (the
    normal case until HKJC history accumulates).
    """
    beats: list[float] = []
    edges: list[float] = []
    for match_id, model_probs in model_probs_by_match.items():
        closing = closing_probs_by_match.get(match_id)
        if not closing:
            continue
        for outcome, model_prob in model_probs.items():
            closing_prob = closing.get(outcome)
            if closing_prob is None:
                continue
            beats.append(1.0 if model_prob >= closing_prob else 0.0)
            edges.append(model_prob - closing_prob)
    if not beats:
        return {"clv_fraction": None, "clv_mean_edge": None, "n": 0}
    return {
        "clv_fraction": sum(beats) / len(beats),
        "clv_mean_edge": sum(edges) / len(edges),
        "n": len(beats),
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ml_value.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ml/value.py tests/test_ml_value.py
git commit -m "feat: 新增價值偵測、Kelly 與 CLV 指標模組"
```

---

### Task 6: Feature builder (`app/ml/features.py`)

**Files:**
- Create: `app/ml/features.py`
- Test: `tests/test_ml_features.py`

**Interfaces:**
- Consumes: `parse_handicap_line` (`app/ml/labels.py`).
- Produces: `FEATURE_VERSION: str`; `FEATURE_COLUMNS: list[str]`; dataclasses `MatchRow`, `MarketPrior`, `FeatureRow`; `build_feature_rows(rows, market_priors=None) -> list[FeatureRow]`; `hkjc_had_odds(payload) -> dict[str, float] | None`; `hkjc_hdc_main(payload) -> tuple[float, dict[str, float]] | None`; `football_data_close_odds(payload) -> dict[str, float] | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ml_features.py`:

```python
import math
from datetime import UTC, datetime, timedelta

from app.ml.features import (
    FEATURE_COLUMNS,
    MarketPrior,
    MatchRow,
    build_feature_rows,
    football_data_close_odds,
    hkjc_had_odds,
    hkjc_hdc_main,
)

HAD_PAYLOAD = {
    "lines": [
        {
            "combinations": [
                {"str": "H", "currentOdds": "2.10"},
                {"str": "D", "currentOdds": "3.40"},
                {"str": "A", "currentOdds": "3.80"},
            ]
        }
    ]
}
HDC_PAYLOAD = {
    "lines": [
        {"condition": "-1", "main": False,
         "combinations": [{"str": "H", "currentOdds": "2.0"}, {"str": "A", "currentOdds": "1.9"}]},
        {"condition": "-1.5", "main": True,
         "combinations": [{"str": "H", "currentOdds": "2.5"}, {"str": "A", "currentOdds": "1.6"}]},
    ]
}
FD_PAYLOAD = {
    "odds": {
        "B365": {"open": [2.0, 3.4, 3.6], "close": [2.05, 3.3, 3.7]},
        "PS": {"open": [2.1, 3.5, 3.9], "close": [2.15, 3.4, 4.0]},
    }
}


def _row(mid, ko, home, away, hs=None, as_=None, code="EPL", season="2026/27"):
    return MatchRow(
        match_id=mid, kickoff_time=ko, home_team_id=home, away_team_id=away,
        league_code=code, season_label=season, home_score=hs, away_score=as_,
    )


def _equal(a, b):
    assert a.keys() == b.keys()
    for key in a:
        av, bv = a[key], b[key]
        if isinstance(av, float) and math.isnan(av):
            assert isinstance(bv, float) and math.isnan(bv)
        else:
            assert av == bv


def test_payload_parsers() -> None:
    assert hkjc_had_odds(HAD_PAYLOAD) == {"H": 2.10, "D": 3.40, "A": 3.80}
    assert hkjc_hdc_main(HDC_PAYLOAD) == (-1.5, {"H": 2.5, "A": 1.6})
    assert football_data_close_odds(FD_PAYLOAD) == {"H": 2.15, "D": 3.4, "A": 4.0}
    assert hkjc_had_odds({}) is None
    assert football_data_close_odds({}) is None


def test_feature_row_has_all_columns() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    rows = build_feature_rows([_row(1, t, 1, 2, hs=1, as_=0), _row(2, t + timedelta(days=3), 1, 3)])
    assert set(rows[0].features.keys()) == set(FEATURE_COLUMNS)
    assert rows[0].features["has_market_prior"] == 0.0


def test_no_future_leakage() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    a = _row(1, t, 1, 2, hs=2, as_=0)
    b = _row(2, t + timedelta(days=7), 1, 3)
    c = _row(3, t + timedelta(days=14), 1, 4, hs=5, as_=5)
    with_future = {r.match_id: r.features for r in build_feature_rows([a, b, c])}
    without_future = {r.match_id: r.features for r in build_feature_rows([a, b])}
    _equal(with_future[2], without_future[2])


def test_same_kickoff_does_not_leak() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    a = _row(1, t, 1, 2, hs=3, as_=0)
    b = _row(2, t, 3, 4, hs=0, as_=0)
    paired = {r.match_id: r.features for r in build_feature_rows([a, b])}
    solo = {r.match_id: r.features for r in build_feature_rows([b])}
    _equal(paired[2], solo[2])


def test_market_prior_features() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    prior = MarketPrior(
        had_probs={"H": 0.5, "D": 0.3, "A": 0.2},
        hdc_line=-0.5,
        hdc_probs={"H": 0.55, "A": 0.45},
        source="hkjc",
    )
    rows = build_feature_rows([_row(1, t, 1, 2)], {1: prior})
    features = rows[0].features
    assert features["has_market_prior"] == 1.0
    assert features["market_home"] == 0.5
    assert features["has_hdc_prior"] == 1.0
    assert features["hdc_line"] == -0.5
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ml_features.py -v`
Expected: FAIL — `No module named 'app.ml.features'`.

- [ ] **Step 3: Implement**

Create `app/ml/features.py`:

```python
"""As-of-kickoff feature builder.

Every feature row is computed from state that only accumulates from matches
with a strictly earlier kickoff time, so the builder is leakage-safe by
construction: adding future matches never changes an earlier row, and matches
sharing a kickoff time cannot leak into each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.ml.labels import parse_handicap_line

FEATURE_VERSION = "v1"

ELO_INITIAL = 1500.0
ELO_K = 20.0
ELO_HOME_ADVANTAGE = 65.0
FORM_WINDOW = 5
STRENGTH_WINDOW = 10
H2H_WINDOW = 5
DEFAULT_REST_DAYS = 7.0

LEAGUE_CODES: dict[str, int] = {
    "EPL": 0,
    "LALIGA": 1,
    "SERIEA": 2,
    "BUNDESLIGA": 3,
    "LIGUE1": 4,
    "UCL": 5,
}

FEATURE_COLUMNS: list[str] = [
    "elo_home", "elo_away", "elo_diff",
    "attack_home", "defense_home", "attack_away", "defense_away",
    "attack_diff", "defense_diff",
    "form_points_home", "form_gd_home", "form_points_away", "form_gd_away",
    "home_form_points", "away_form_points",
    "rest_days_home", "rest_days_away",
    "league_code", "matchday_index",
    "h2h_net_gd",
    "market_home", "market_draw", "market_away",
    "hdc_line", "market_hdc_home", "market_hdc_away",
    "has_market_prior", "has_hdc_prior",
]


@dataclass(frozen=True)
class MatchRow:
    """One match as seen by the feature builder (scores optional for upcoming)."""

    match_id: int
    kickoff_time: datetime
    home_team_id: int
    away_team_id: int
    league_code: str
    season_label: str
    home_score: int | None = None
    away_score: int | None = None


@dataclass(frozen=True)
class MarketPrior:
    """De-vigged market probabilities and raw odds for one match."""

    had_probs: dict[str, float] | None = None
    had_odds: dict[str, float] | None = None
    hdc_line: float | None = None
    hdc_probs: dict[str, float] | None = None
    hdc_odds: dict[str, float] | None = None
    source: str = "none"


@dataclass(frozen=True)
class FeatureRow:
    match_id: int
    kickoff_time: datetime
    features: dict[str, float]


def hkjc_had_odds(payload: dict) -> dict[str, float] | None:
    """Extract {"H","D","A"} current odds from an HKJC HAD pool payload."""
    lines = payload.get("lines") or []
    if not lines:
        return None
    odds: dict[str, float] = {}
    for combination in lines[0].get("combinations") or []:
        key = combination.get("str")
        value = combination.get("currentOdds")
        if key in {"H", "D", "A"} and value is not None:
            odds[key] = float(value)
    if set(odds) != {"H", "D", "A"}:
        return None
    return odds


def hkjc_hdc_main(payload: dict) -> tuple[float, dict[str, float]] | None:
    """Extract the main HDC line and its {"H","A"} odds from a pool payload."""
    for line in payload.get("lines") or []:
        if not line.get("main"):
            continue
        parsed = parse_handicap_line(line.get("condition"))
        if parsed is None:
            continue
        odds: dict[str, float] = {}
        for combination in line.get("combinations") or []:
            key = combination.get("str")
            value = combination.get("currentOdds")
            if key in {"H", "A"} and value is not None:
                odds[key] = float(value)
        if set(odds) == {"H", "A"}:
            return parsed, odds
    return None


def football_data_close_odds(payload: dict) -> dict[str, float] | None:
    """Closing {"H","D","A"} odds from a football-data snapshot payload.

    Prefers Pinnacle ("PS") as the sharp prior, then the market average ("Avg"),
    then Bet365 ("B365").
    """
    bookmakers = payload.get("odds") or {}
    for bookmaker in ("PS", "Avg", "B365"):
        entry = bookmakers.get(bookmaker)
        if not entry:
            continue
        close = entry.get("close") or []
        if len(close) != 3 or any(value is None for value in close):
            continue
        return {"H": float(close[0]), "D": float(close[1]), "A": float(close[2])}
    return None


@dataclass
class _TeamHistory:
    results: list[tuple[int, int]] = field(default_factory=list)
    home_results: list[tuple[int, int]] = field(default_factory=list)
    away_results: list[tuple[int, int]] = field(default_factory=list)
    last_kickoff: datetime | None = None
    season_counts: dict[str, int] = field(default_factory=dict)


class _State:
    def __init__(self) -> None:
        self.teams: dict[int, _TeamHistory] = {}
        self.elo: dict[int, float] = {}
        self.h2h: dict[tuple[int, int], list[tuple[int, int]]] = {}
        self.goals_total = 0
        self.team_matches = 0

    def team(self, team_id: int) -> _TeamHistory:
        return self.teams.setdefault(team_id, _TeamHistory())

    def elo_of(self, team_id: int) -> float:
        return self.elo.get(team_id, ELO_INITIAL)

    def scoring_baseline(self) -> float:
        if self.team_matches == 0:
            return 1.0
        baseline = self.goals_total / (2.0 * self.team_matches)
        return baseline if baseline > 0 else 1.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _form(results: list[tuple[int, int]]) -> tuple[float, float]:
    window = results[-FORM_WINDOW:]
    points = 0.0
    gd = 0.0
    for goals_for, goals_against in window:
        gd += goals_for - goals_against
        if goals_for > goals_against:
            points += 3.0
        elif goals_for == goals_against:
            points += 1.0
    return points, gd


def _strength(results: list[tuple[int, int]], baseline: float) -> tuple[float, float]:
    window = results[-STRENGTH_WINDOW:]
    if not window:
        return 1.0, 1.0
    attack = _mean([float(gf) for gf, _ in window]) / baseline
    defense = _mean([float(ga) for _, ga in window]) / baseline
    return attack, defense


def _rest_days(last_kickoff: datetime | None, kickoff: datetime) -> float:
    if last_kickoff is None:
        return DEFAULT_REST_DAYS
    return (kickoff - last_kickoff).total_seconds() / 86400.0


def _h2h_net(state: _State, home_team_id: int, away_team_id: int) -> float:
    key = (min(home_team_id, away_team_id), max(home_team_id, away_team_id))
    entries = state.h2h.get(key, [])[-H2H_WINDOW:]
    if not entries:
        return 0.0
    nets = [net if stored_home == home_team_id else -net for stored_home, net in entries]
    return _mean([float(value) for value in nets])


def _features_for(state: _State, row: MatchRow, prior: MarketPrior | None) -> dict[str, float]:
    home = state.team(row.home_team_id)
    away = state.team(row.away_team_id)
    baseline = state.scoring_baseline()
    elo_home = state.elo_of(row.home_team_id)
    elo_away = state.elo_of(row.away_team_id)
    attack_home, defense_home = _strength(home.results, baseline)
    attack_away, defense_away = _strength(away.results, baseline)
    form_points_home, form_gd_home = _form(home.results)
    form_points_away, form_gd_away = _form(away.results)
    home_form_points, _ = _form(home.home_results)
    away_form_points, _ = _form(away.away_results)
    matchday_index = home.season_counts.get(row.season_label, 0) + 1
    nan = float("nan")
    features = {
        "elo_home": elo_home,
        "elo_away": elo_away,
        "elo_diff": elo_home - elo_away,
        "attack_home": attack_home,
        "defense_home": defense_home,
        "attack_away": attack_away,
        "defense_away": defense_away,
        "attack_diff": attack_home - attack_away,
        "defense_diff": defense_home - defense_away,
        "form_points_home": form_points_home,
        "form_gd_home": form_gd_home,
        "form_points_away": form_points_away,
        "form_gd_away": form_gd_away,
        "home_form_points": home_form_points,
        "away_form_points": away_form_points,
        "rest_days_home": _rest_days(home.last_kickoff, row.kickoff_time),
        "rest_days_away": _rest_days(away.last_kickoff, row.kickoff_time),
        "league_code": float(LEAGUE_CODES.get(row.league_code, -1)),
        "matchday_index": float(matchday_index),
        "h2h_net_gd": _h2h_net(state, row.home_team_id, row.away_team_id),
        "market_home": nan,
        "market_draw": nan,
        "market_away": nan,
        "hdc_line": nan,
        "market_hdc_home": nan,
        "market_hdc_away": nan,
        "has_market_prior": 0.0,
        "has_hdc_prior": 0.0,
    }
    if prior is not None and prior.had_probs is not None:
        features["market_home"] = prior.had_probs.get("H", nan)
        features["market_draw"] = prior.had_probs.get("D", nan)
        features["market_away"] = prior.had_probs.get("A", nan)
        features["has_market_prior"] = 1.0
    if prior is not None and prior.hdc_line is not None and prior.hdc_probs is not None:
        features["hdc_line"] = prior.hdc_line
        features["market_hdc_home"] = prior.hdc_probs.get("H", nan)
        features["market_hdc_away"] = prior.hdc_probs.get("A", nan)
        features["has_hdc_prior"] = 1.0
    return features


def _update(state: _State, row: MatchRow) -> None:
    if row.home_score is None or row.away_score is None:
        return
    home_score = row.home_score
    away_score = row.away_score
    home = state.team(row.home_team_id)
    away = state.team(row.away_team_id)
    home.results.append((home_score, away_score))
    away.results.append((away_score, home_score))
    home.home_results.append((home_score, away_score))
    away.away_results.append((away_score, home_score))
    home.last_kickoff = row.kickoff_time
    away.last_kickoff = row.kickoff_time
    home.season_counts[row.season_label] = home.season_counts.get(row.season_label, 0) + 1
    away.season_counts[row.season_label] = away.season_counts.get(row.season_label, 0) + 1
    state.goals_total += home_score + away_score
    state.team_matches += 1
    elo_home = state.elo_of(row.home_team_id)
    elo_away = state.elo_of(row.away_team_id)
    expected_home = 1.0 / (1.0 + 10.0 ** ((elo_away - elo_home - ELO_HOME_ADVANTAGE) / 400.0))
    if home_score > away_score:
        actual_home = 1.0
    elif home_score == away_score:
        actual_home = 0.5
    else:
        actual_home = 0.0
    state.elo[row.home_team_id] = elo_home + ELO_K * (actual_home - expected_home)
    state.elo[row.away_team_id] = elo_away + ELO_K * ((1.0 - actual_home) - (1.0 - expected_home))
    key = (min(row.home_team_id, row.away_team_id), max(row.home_team_id, row.away_team_id))
    state.h2h.setdefault(key, []).append((row.home_team_id, home_score - away_score))


def build_feature_rows(
    rows: list[MatchRow],
    market_priors: dict[int, MarketPrior] | None = None,
) -> list[FeatureRow]:
    """Build one feature row per match, strictly as-of kickoff.

    Rows are processed in (kickoff_time, match_id) order. All matches sharing a
    kickoff time see the same pre-kickoff state; their results are applied only
    afterwards, so simultaneous matches cannot leak into each other.
    """
    priors = market_priors or {}
    ordered = sorted(rows, key=lambda row: (row.kickoff_time, row.match_id))
    state = _State()
    output: list[FeatureRow] = []
    index = 0
    while index < len(ordered):
        kickoff = ordered[index].kickoff_time
        group: list[MatchRow] = []
        while index < len(ordered) and ordered[index].kickoff_time == kickoff:
            group.append(ordered[index])
            index += 1
        for row in group:
            output.append(
                FeatureRow(
                    match_id=row.match_id,
                    kickoff_time=row.kickoff_time,
                    features=_features_for(state, row, priors.get(row.match_id)),
                )
            )
        for row in group:
            _update(state, row)
    return output
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ml_features.py -v`
Expected: PASS (including the two leakage tests).

- [ ] **Step 5: Commit**

```bash
git add app/ml/features.py tests/test_ml_features.py
git commit -m "feat: 新增防洩漏特徵建構器（Elo、攻守、近況、H2H、市場先驗）"
```

---

### Task 7: Dataset assembly (`app/ml/dataset.py`) + Pinnacle in the football-data provider

**Files:**
- Create: `app/ml/dataset.py`
- Create: `tests/ml_helpers.py`
- Modify: `app/providers/football_data/provider.py`
- Modify: `tests/test_football_data_provider.py`
- Test: `tests/test_ml_dataset.py`

**Interfaces:**
- Consumes: `Settings`; `Match`, `Result`, `OddsSnapshot`, `League`, `Season`; `devig_multiplicative`; `build_feature_rows`, `hkjc_had_odds`, `hkjc_hdc_main`, `football_data_close_odds`, `MarketPrior`, `MatchRow`, `FEATURE_VERSION`; `label_1x2`, `handicap_label`.
- Produces: dataclass `Dataset(train, calibration, eval, feature_version)`; `load_training_rows(session, settings, before=None) -> list[MatchRow]`; `load_hkjc_priors(session, rows) -> dict[int, MarketPrior]`; `load_market_priors(session, rows) -> dict[int, MarketPrior]`; `temporal_split(df, calibration_fraction=0.1, eval_fraction=0.2) -> tuple[DataFrame, DataFrame, DataFrame]`; `build_dataset(session, settings) -> Dataset`.

- [ ] **Step 1: Extend the football-data provider with Pinnacle**

Open `app/providers/football_data/provider.py`. In the `BOOKMAKERS` mapping, add a Pinnacle entry following the existing tuple format — the Pinnacle columns in football-data CSVs are `PSH/PSD/PSA` (open) and `PSCH/PSCD/PSCA` (close):

```python
    "PS": ("PSH", "PSD", "PSA", "PSCH", "PSCD", "PSCA"),
```

(If a `"PS"` entry already exists, leave it as-is.) Add to `tests/test_football_data_provider.py` a test asserting Pinnacle is parsed from a tiny CSV containing `PSH,PSD,PSA,PSCH,PSCD,PSCA` columns and that `"PS"` appears in the parsed `odds`.

- [ ] **Step 2: Write the failing tests**

Create `tests/ml_helpers.py`:

```python
"""Shared helpers for ML tests: a tiny seeded league/teams/matches/results/odds DB."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.models import League, Match, OddsSnapshot, Result, Season, Team
from app.db.session import Database


async def make_db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'ml.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return db


async def seed_context(session: AsyncSession, code: str = "EPL") -> tuple[League, Season]:
    league = League(code=code, name_en=code, name_ch=None, country=None, active=True)
    session.add(league)
    await session.flush()
    season = Season(
        league_id=league.id,
        label="2026/27",
        start_date=date(2026, 7, 1),
        end_date=date(2027, 6, 30),
    )
    session.add(season)
    await session.flush()
    return league, season


async def seed_team(session: AsyncSession, name: str) -> Team:
    team = Team(name_en=name, name_ch=None, hkjc_team_id=None, aliases=[], external_ids={})
    session.add(team)
    await session.flush()
    return team


async def seed_finished_match(
    session: AsyncSession,
    league: League,
    season: Season,
    home: Team,
    away: Team,
    *,
    match_id_label: str,
    kickoff: datetime,
    home_score: int,
    away_score: int,
    had_payload: dict | None = None,
    hdc_payload: dict | None = None,
    snapshot_source: str = "hkjc",
    snapshot_at_offset_hours: int = -1,
) -> Match:
    match = Match(
        season_id=season.id,
        league_id=league.id,
        hkjc_match_id=match_id_label,
        kickoff_time=kickoff,
        status="finished",
        home_team_id=home.id,
        away_team_id=away.id,
    )
    session.add(match)
    await session.flush()
    session.add(
        Result(
            match_id=match.id,
            home_score=home_score,
            away_score=away_score,
            ttl_corner=None,
            source="hkjc",
            confirmed=True,
            payout_confirmed=True,
        )
    )
    if had_payload is not None:
        session.add(
            OddsSnapshot(
                match_id=match.id,
                captured_at=kickoff.replace() + __import__("datetime").timedelta(hours=snapshot_at_offset_hours),
                snapshot_bucket=kickoff,
                source=snapshot_source,
                inplay=False,
                odds_type="HAD",
                payload=had_payload,
            )
        )
    if hdc_payload is not None:
        session.add(
            OddsSnapshot(
                match_id=match.id,
                captured_at=kickoff.replace() + __import__("datetime").timedelta(hours=snapshot_at_offset_hours),
                snapshot_bucket=kickoff,
                source=snapshot_source,
                inplay=False,
                odds_type="HDC",
                payload=hdc_payload,
            )
        )
    await session.flush()
    return match
```

Create `tests/test_ml_dataset.py`:

```python
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.config import Settings
from app.ml.dataset import build_dataset, load_market_priors, load_training_rows, temporal_split
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team

HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}
HDC = {"lines": [{"condition": "-0.5", "main": True, "combinations": [
    {"str": "H", "currentOdds": "2.0"}, {"str": "A", "currentOdds": "1.9"}]}]}
FD = {"odds": {"PS": {"open": [2.1, 3.5, 3.9], "close": [2.15, 3.4, 4.0]}}}


def _settings() -> Settings:
    return Settings(_env_file=None, ml_history_from_year=2020)


def test_temporal_split_is_chronological() -> None:
    df = pd.DataFrame(
        {
            "kickoff_time": pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC"),
            "match_id": range(100),
        }
    )
    train, calibration, evaluation = temporal_split(df)
    assert len(train) == 70 and len(calibration) == 10 and len(evaluation) == 20
    assert train["kickoff_time"].max() < calibration["kickoff_time"].min()
    assert calibration["kickoff_time"].max() < evaluation["kickoff_time"].min()


async def test_load_training_rows_and_market_priors(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        t = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            await seed_finished_match(
                session, league, season, home, away,
                match_id_label="M1", kickoff=t, home_score=2, away_score=1,
                had_payload=HAD, hdc_payload=HDC,
            )
            await session.commit()
        async with db.session_factory() as session:
            rows = await load_training_rows(session, _settings())
            assert len(rows) == 1 and rows[0].home_score == 2
            priors = await load_market_priors(session, rows)
            prior = priors[rows[0].match_id]
            assert prior.had_probs is not None
            assert abs(sum(prior.had_probs.values()) - 1.0) < 1e-9
            assert prior.hdc_line == -0.5
            assert prior.source == "hkjc"
    finally:
        await db.dispose()


async def test_market_prior_falls_back_to_football_data(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        t = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            # football-data snapshot captured exactly at kickoff (closing line)
            await seed_finished_match(
                session, league, season, home, away,
                match_id_label="M1", kickoff=t, home_score=1, away_score=0,
                had_payload=FD, snapshot_source="football_data", snapshot_at_offset_hours=0,
            )
            await session.commit()
        async with db.session_factory() as session:
            rows = await load_training_rows(session, _settings())
            priors = await load_market_priors(session, rows)
            assert priors[rows[0].match_id].source == "football_data"
    finally:
        await db.dispose()


async def test_build_dataset(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            teams = [await seed_team(session, f"T{i}") for i in range(6)]
            base = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
            for index in range(40):
                await seed_finished_match(
                    session, league, season, teams[index % 6], teams[(index + 1) % 6],
                    match_id_label=f"M{index}", kickoff=base + timedelta(days=index),
                    home_score=index % 4, away_score=(index + 1) % 3,
                    had_payload=HAD, hdc_payload=HDC,
                )
            await session.commit()
        async with db.session_factory() as session:
            dataset = await build_dataset(session, _settings())
            assert len(dataset.train) + len(dataset.calibration) + len(dataset.eval) == 40
            assert "label_1x2" in dataset.train.columns
    finally:
        await db.dispose()
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_ml_dataset.py tests/test_football_data_provider.py -v`
Expected: FAIL — `No module named 'app.ml.dataset'` (and the Pinnacle assertion fails first if the provider step wasn't done).

- [ ] **Step 4: Implement `app/ml/dataset.py`**

```python
"""Training dataset assembly: DB rows -> feature frame -> temporal split."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import League, Match, OddsSnapshot, Result, Season
from app.ml.deviq import devig_multiplicative
from app.ml.features import (
    FEATURE_VERSION,
    FeatureRow,
    MarketPrior,
    MatchRow,
    build_feature_rows,
    football_data_close_odds,
    hkjc_had_odds,
    hkjc_hdc_main,
)
from app.ml.labels import handicap_label, label_1x2

CALIBRATION_FRACTION = 0.1
EVAL_FRACTION = 0.2
MIN_DATASET_ROWS = 10


@dataclass
class Dataset:
    train: pd.DataFrame
    calibration: pd.DataFrame
    eval: pd.DataFrame
    feature_version: str = FEATURE_VERSION


async def load_training_rows(
    session: AsyncSession,
    settings: Settings,
    before: datetime | None = None,
) -> list[MatchRow]:
    """Confirmed results from the configured history window, oldest first."""
    stmt = (
        select(Match, Result, League.code, Season.label)
        .join(Result, Result.match_id == Match.id)
        .join(League, League.id == Match.league_id)
        .join(Season, Season.id == Match.season_id)
        .where(Result.confirmed.is_(True))
        .where(Match.kickoff_time >= datetime(settings.ml_history_from_year, 7, 1, tzinfo=UTC))
        .where(League.code.in_(settings.league_whitelist))
        .order_by(Match.kickoff_time, Match.id)
    )
    if before is not None:
        stmt = stmt.where(Match.kickoff_time < before)
    rows = (await session.execute(stmt)).all()
    return [
        MatchRow(
            match_id=match.id,
            kickoff_time=match.kickoff_time,
            home_team_id=match.home_team_id,
            away_team_id=match.away_team_id,
            league_code=league_code,
            season_label=season_label,
            home_score=result.home_score,
            away_score=result.away_score,
        )
        for match, result, league_code, season_label in rows
    ]


async def _latest_hkjc_snapshots(
    session: AsyncSession, rows: list[MatchRow], odds_type: str
) -> dict[int, OddsSnapshot]:
    if not rows:
        return {}
    kickoffs = {row.match_id: row.kickoff_time for row in rows}
    stmt = (
        select(OddsSnapshot)
        .where(OddsSnapshot.match_id.in_(list(kickoffs)))
        .where(OddsSnapshot.odds_type == odds_type)
        .where(OddsSnapshot.source == "hkjc")
        .where(OddsSnapshot.inplay.is_(False))
        .order_by(OddsSnapshot.captured_at)
    )
    latest: dict[int, OddsSnapshot] = {}
    for snapshot in (await session.execute(stmt)).scalars():
        if snapshot.captured_at < kickoffs[snapshot.match_id]:
            latest[snapshot.match_id] = snapshot
    return latest


async def _football_data_snapshots(
    session: AsyncSession, rows: list[MatchRow]
) -> dict[int, OddsSnapshot]:
    if not rows:
        return {}
    stmt = (
        select(OddsSnapshot)
        .where(OddsSnapshot.match_id.in_([row.match_id for row in rows]))
        .where(OddsSnapshot.odds_type == "HAD")
        .where(OddsSnapshot.source == "football_data")
    )
    return {snapshot.match_id: snapshot for snapshot in (await session.execute(stmt)).scalars()}


async def load_hkjc_priors(session: AsyncSession, rows: list[MatchRow]) -> dict[int, MarketPrior]:
    """HKJC-only de-vigged priors (used for CLV, which needs HKJC closes)."""
    had = await _latest_hkjc_snapshots(session, rows, "HAD")
    hdc = await _latest_hkjc_snapshots(session, rows, "HDC")
    priors: dict[int, MarketPrior] = {}
    for row in rows:
        had_probs = had_odds = None
        snapshot = had.get(row.match_id)
        if snapshot is not None:
            had_odds = hkjc_had_odds(snapshot.payload)
            if had_odds is not None:
                fair = devig_multiplicative([had_odds["H"], had_odds["D"], had_odds["A"]])
                had_probs = {"H": fair[0], "D": fair[1], "A": fair[2]}
        hdc_line = hdc_probs = hdc_odds = None
        snapshot = hdc.get(row.match_id)
        if snapshot is not None:
            main = hkjc_hdc_main(snapshot.payload)
            if main is not None:
                hdc_line, hdc_odds = main
                fair = devig_multiplicative([hdc_odds["H"], hdc_odds["A"]])
                hdc_probs = {"H": fair[0], "A": fair[1]}
        priors[row.match_id] = MarketPrior(
            had_probs=had_probs,
            had_odds=had_odds,
            hdc_line=hdc_line,
            hdc_probs=hdc_probs,
            hdc_odds=hdc_odds,
            source="hkjc" if had_probs is not None else "none",
        )
    return priors


async def load_market_priors(session: AsyncSession, rows: list[MatchRow]) -> dict[int, MarketPrior]:
    """HKJC priors where available, else football-data closing (Pinnacle first)."""
    priors = await load_hkjc_priors(session, rows)
    missing = [row for row in rows if priors[row.match_id].had_probs is None]
    if not missing:
        return priors
    fallback = await _football_data_snapshots(session, missing)
    for row in missing:
        snapshot = fallback.get(row.match_id)
        if snapshot is None:
            continue
        odds = football_data_close_odds(snapshot.payload)
        if odds is None:
            continue
        fair = devig_multiplicative([odds["H"], odds["D"], odds["A"]])
        prior = priors[row.match_id]
        priors[row.match_id] = MarketPrior(
            had_probs={"H": fair[0], "D": fair[1], "A": fair[2]},
            had_odds=odds,
            hdc_line=prior.hdc_line,
            hdc_probs=prior.hdc_probs,
            hdc_odds=prior.hdc_odds,
            source="football_data",
        )
    return priors


def temporal_split(
    df: pd.DataFrame,
    calibration_fraction: float = CALIBRATION_FRACTION,
    eval_fraction: float = EVAL_FRACTION,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronological train/calibration/eval split (oldest -> newest)."""
    ordered = df.sort_values(["kickoff_time", "match_id"]).reset_index(drop=True)
    n = len(ordered)
    if n < MIN_DATASET_ROWS:
        raise ValueError(f"need at least {MIN_DATASET_ROWS} rows, got {n}")
    n_eval = max(1, int(n * eval_fraction))
    n_cal = max(1, int(n * calibration_fraction))
    n_train = n - n_eval - n_cal
    if n_train < 1:
        raise ValueError(f"split leaves no training rows (n={n})")
    return (
        ordered.iloc[:n_train].copy(),
        ordered.iloc[n_train : n_train + n_cal].copy(),
        ordered.iloc[n_train + n_cal :].copy(),
    )


def _frame(rows: list[MatchRow], priors: dict[int, MarketPrior]) -> pd.DataFrame:
    by_id = {row.match_id: row for row in rows}
    records: list[dict] = []
    for feature_row in build_feature_rows(rows, priors):
        row = by_id[feature_row.match_id]
        if row.home_score is None or row.away_score is None:
            continue
        prior = priors.get(feature_row.match_id)
        label_hdc = None
        if prior is not None and prior.hdc_line is not None:
            label_hdc = handicap_label(row.home_score, row.away_score, prior.hdc_line)
        records.append(
            {
                **feature_row.features,
                "match_id": feature_row.match_id,
                "kickoff_time": feature_row.kickoff_time,
                "label_1x2": label_1x2(row.home_score, row.away_score),
                "label_handicap": label_hdc,
            }
        )
    if not records:
        raise ValueError("no labelled rows could be built")
    return pd.DataFrame.from_records(records)


async def build_dataset(session: AsyncSession, settings: Settings) -> Dataset:
    """Assemble the full training dataset from the database."""
    rows = await load_training_rows(session, settings)
    if not rows:
        raise ValueError("no confirmed results in the configured history window")
    priors = await load_market_priors(session, rows)
    train, calibration, evaluation = temporal_split(_frame(rows, priors))
    return Dataset(train=train, calibration=calibration, eval=evaluation)
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_ml_dataset.py tests/test_football_data_provider.py -v && uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add app/ml/dataset.py tests/ml_helpers.py tests/test_ml_dataset.py app/providers/football_data/provider.py tests/test_football_data_provider.py
git commit -m "feat: 新增訓練資料集組裝、時間切分與 Pinnacle 收盤賠率解析"
```

---

### Task 8: Models (`app/ml/models.py`)

**Files:**
- Create: `app/ml/models.py`
- Test: `tests/test_ml_models.py`

**Interfaces:**
- Consumes: `FEATURE_COLUMNS`, `FEATURE_VERSION`.
- Produces: `TARGET_1X2 = "1x2"`, `TARGET_HANDICAP = "handicap"`; `TracedModel` (see below — named `TrainedModel`); `train_1x2(train_df, calibration_df, eval_df, params=None) -> TrainedModel`; `train_handicap(...)`; `predict_proba(model, features, calibrated=True) -> np.ndarray`; `evaluate_1x2(probs, labels) -> dict`; `evaluate_handicap(probs, labels) -> dict`; `save_artifact(model, path)`; `load_artifact(path) -> TrainedModel`; `_fit_isotonic_binary`, `_apply_isotonic_binary`, `_fit_isotonic_multiclass`, `_apply_isotonic_multiclass`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ml_models.py`:

```python
import numpy as np
import pandas as pd
import pytest

from app.ml.features import FEATURE_COLUMNS
from app.ml.models import (
    TARGET_1X2,
    _apply_isotonic_binary,
    _fit_isotonic_binary,
    load_artifact,
    predict_proba,
    save_artifact,
    train_1x2,
    train_handicap,
)


def _frame(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({column: rng.normal(size=n) for column in FEATURE_COLUMNS})
    df["kickoff_time"] = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    df["match_id"] = range(n)
    strength = df["elo_diff"].to_numpy()
    logits = np.column_stack([strength, np.zeros(n), -strength])
    probs = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
    labels = np.array(["H", "D", "A"])[
        [rng.choice(3, p=row) for row in probs]
    ]
    df["label_1x2"] = labels
    df["label_handicap"] = np.where(rng.uniform(size=n) < 1 / (1 + np.exp(-strength)), "H", "A")
    return df


def test_isotonic_binary_calibration_improves_brier() -> None:
    rng = np.random.default_rng(0)
    n = 4000
    p_true = rng.uniform(0.05, 0.95, n)
    y = (rng.uniform(size=n) < p_true).astype(int)
    raw = p_true**2  # deliberately miscalibrated
    calibrators = _fit_isotonic_binary(raw[:2000], y[:2000])
    calibrated = _apply_isotonic_binary(calibrators, raw[2000:])
    brier_raw = float(np.mean((raw[2000:] - y[2000:]) ** 2))
    brier_calibrated = float(np.mean((calibrated - y[2000:]) ** 2))
    assert brier_calibrated < brier_raw


def test_train_predict_evaluate_1x2(tmp_path) -> None:
    df = _frame(600, seed=1)
    model = train_1x2(df.iloc[:420], df.iloc[420:480], df.iloc[480:])
    probs = predict_proba(model, df.iloc[480:][FEATURE_COLUMNS].to_dict("records"))
    assert probs.shape == (120, 3)
    assert np.allclose(probs.sum(axis=1), 1.0)
    assert "brier" in model.metrics and "logloss" in model.metrics
    assert model.target == TARGET_1X2
    path = tmp_path / "m1x2.joblib"
    save_artifact(model, path)
    reloaded = load_artifact(path)
    again = predict_proba(reloaded, df.iloc[480:][FEATURE_COLUMNS].to_dict("records"))
    assert np.allclose(probs, again)


def test_train_handicap(tmp_path) -> None:
    df = _frame(400, seed=2)
    model = train_handicap(df.iloc[:280], df.iloc[280:320], df.iloc[320:])
    probs = predict_proba(model, df.iloc[320:][FEATURE_COLUMNS].to_dict("records"))
    assert probs.shape == (80,)
    assert ((probs >= 0) & (probs <= 1)).all()


def test_train_requires_rows() -> None:
    empty = _frame(5, seed=3)
    with pytest.raises(ValueError):
        train_1x2(empty.iloc[:0], empty.iloc[:0], empty.iloc[:0])
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ml_models.py -v`
Expected: FAIL — `No module named 'app.ml.models'`.

- [ ] **Step 3: Implement**

Create `app/ml/models.py`:

```python
"""LightGBM training + isotonic calibration for the 1X2 and handicap targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import log_loss

from app.ml.features import FEATURE_COLUMNS, FEATURE_VERSION

TARGET_1X2 = "1x2"
TARGET_HANDICAP = "handicap"

LABEL_TO_INDEX = {"H": 0, "D": 1, "A": 2}
INDEX_TO_LABEL = {0: "H", 1: "D", 2: "A"}

DEFAULT_1X2_PARAMS: dict = {
    "objective": "multiclass",
    "num_class": 3,
    "learning_rate": 0.04,
    "num_leaves": 31,
    "min_child_samples": 30,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "seed": 42,
    "verbose": -1,
}

DEFAULT_HANDICAP_PARAMS: dict = {
    "objective": "binary",
    "learning_rate": 0.04,
    "num_leaves": 31,
    "min_child_samples": 30,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "seed": 42,
    "verbose": -1,
}

NUM_BOOST_ROUND = 500
EARLY_STOPPING_ROUNDS = 50
VAL_FRACTION = 0.15
MIN_ROWS_FOR_VAL = 10
MIN_TRAIN_ROWS = 20


@dataclass
class TrainedModel:
    target: str
    booster: lgb.Booster
    calibrators: list[IsotonicRegression]
    feature_columns: list[str] = field(default_factory=lambda: list(FEATURE_COLUMNS))
    feature_version: str = FEATURE_VERSION
    metrics: dict = field(default_factory=dict)


def _matrix(df: pd.DataFrame) -> pd.DataFrame:
    return df[FEATURE_COLUMNS].astype(float)


def _labels_1x2(df: pd.DataFrame) -> np.ndarray:
    return df["label_1x2"].map(LABEL_TO_INDEX).astype(int).to_numpy()


def _labels_handicap(df: pd.DataFrame) -> np.ndarray:
    return (df["label_handicap"] == "H").astype(int).to_numpy()


def _temporal_val_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    if len(df) < MIN_ROWS_FOR_VAL:
        return df, None
    n_val = max(1, int(len(df) * VAL_FRACTION))
    return df.iloc[:-n_val], df.iloc[-n_val:]


def _fit_isotonic_binary(raw: np.ndarray, labels: np.ndarray) -> list[IsotonicRegression]:
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(raw, labels.astype(float))
    return [calibrator]


def _apply_isotonic_binary(calibrators: list[IsotonicRegression], raw: np.ndarray) -> np.ndarray:
    return np.clip(calibrators[0].predict(raw), 0.0, 1.0)


def _fit_isotonic_multiclass(raw: np.ndarray, labels: np.ndarray) -> list[IsotonicRegression]:
    calibrators: list[IsotonicRegression] = []
    for class_index in range(raw.shape[1]):
        calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        calibrator.fit(raw[:, class_index], (labels == class_index).astype(float))
        calibrators.append(calibrator)
    return calibrators


def _apply_isotonic_multiclass(
    calibrators: list[IsotonicRegression], raw: np.ndarray
) -> np.ndarray:
    calibrated = np.column_stack(
        [calibrator.predict(raw[:, index]) for index, calibrator in enumerate(calibrators)]
    )
    totals = calibrated.sum(axis=1, keepdims=True)
    totals[totals <= 0] = 1.0
    return calibrated / totals


def _train_booster(
    fit_df: pd.DataFrame,
    val_df: pd.DataFrame | None,
    label_fn,
    params: dict,
) -> lgb.Booster:
    train_set = lgb.Dataset(_matrix(fit_df), label=label_fn(fit_df))
    if val_df is None:
        return lgb.train(params, train_set, num_boost_round=200)
    val_set = lgb.Dataset(_matrix(val_df), label=label_fn(val_df), reference=train_set)
    return lgb.train(
        params,
        train_set,
        num_boost_round=NUM_BOOST_ROUND,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )


def train_1x2(
    train_df: pd.DataFrame,
    calibration_df: pd.DataFrame,
    eval_df: pd.DataFrame,
    params: dict | None = None,
) -> TrainedModel:
    train_df = train_df.dropna(subset=["label_1x2"])
    calibration_df = calibration_df.dropna(subset=["label_1x2"])
    eval_df = eval_df.dropna(subset=["label_1x2"])
    if len(train_df) < MIN_TRAIN_ROWS:
        raise ValueError(f"need at least {MIN_TRAIN_ROWS} 1x2 training rows")
    if calibration_df.empty:
        raise ValueError("no 1x2 calibration rows")
    fit_df, val_df = _temporal_val_split(train_df)
    booster = _train_booster(fit_df, val_df, _labels_1x2, {**DEFAULT_1X2_PARAMS, **(params or {})})
    raw_calibration = np.asarray(booster.predict(_matrix(calibration_df))).reshape(
        len(calibration_df), 3
    )
    calibrators = _fit_isotonic_multiclass(raw_calibration, _labels_1x2(calibration_df))
    model = TrainedModel(target=TARGET_1X2, booster=booster, calibrators=calibrators)
    if not eval_df.empty:
        probs = predict_proba(model, eval_df[FEATURE_COLUMNS].to_dict("records"))
        model.metrics = evaluate_1x2(probs, eval_df["label_1x2"].tolist())
    return model


def train_handicap(
    train_df: pd.DataFrame,
    calibration_df: pd.DataFrame,
    eval_df: pd.DataFrame,
    params: dict | None = None,
) -> TrainedModel:
    train_df = train_df.dropna(subset=["label_handicap"])
    calibration_df = calibration_df.dropna(subset=["label_handicap"])
    eval_df = eval_df.dropna(subset=["label_handicap"])
    if len(train_df) < MIN_TRAIN_ROWS:
        raise ValueError(f"need at least {MIN_TRAIN_ROWS} handicap training rows")
    if calibration_df.empty:
        raise ValueError("no handicap calibration rows")
    fit_df, val_df = _temporal_val_split(train_df)
    booster = _train_booster(
        fit_df, val_df, _labels_handicap, {**DEFAULT_HANDICAP_PARAMS, **(params or {})}
    )
    raw_calibration = np.asarray(booster.predict(_matrix(calibration_df))).reshape(
        len(calibration_df)
    )
    calibrators = _fit_isotonic_binary(raw_calibration, _labels_handicap(calibration_df))
    model = TrainedModel(target=TARGET_HANDICAP, booster=booster, calibrators=calibrators)
    if not eval_df.empty:
        probs = predict_proba(model, eval_df[FEATURE_COLUMNS].to_dict("records"))
        model.metrics = evaluate_handicap(probs, eval_df["label_handicap"].tolist())
    return model


def predict_proba(
    model: TrainedModel,
    features: list[dict[str, float]],
    calibrated: bool = True,
) -> np.ndarray:
    """Calibrated probabilities: (n, 3) for 1X2, (n,) for handicap."""
    frame = pd.DataFrame(
        [
            {column: row.get(column, float("nan")) for column in model.feature_columns}
            for row in features
        ],
        columns=model.feature_columns,
    )
    raw = np.asarray(model.booster.predict(frame))
    if model.target == TARGET_1X2:
        raw = raw.reshape(len(features), 3)
        if calibrated and model.calibrators:
            return _apply_isotonic_multiclass(model.calibrators, raw)
        return raw
    raw = raw.reshape(len(features))
    if calibrated and model.calibrators:
        return _apply_isotonic_binary(model.calibrators, raw)
    return raw


def evaluate_1x2(probs: np.ndarray, labels: list[str]) -> dict:
    y = np.array([LABEL_TO_INDEX[label] for label in labels])
    onehot = np.eye(3)[y]
    brier = float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))
    logloss = float(log_loss(y, probs, labels=[0, 1, 2]))
    return {"brier": brier, "logloss": logloss, "n": int(len(y))}


def evaluate_handicap(probs: np.ndarray, labels: list[str]) -> dict:
    y = np.array([1 if label == "H" else 0 for label in labels])
    brier = float(np.mean((probs - y) ** 2))
    logloss = float(log_loss(y, probs, labels=[0, 1]))
    return {"brier": brier, "logloss": logloss, "n": int(len(y))}


def save_artifact(model: TrainedModel, path: str | Path) -> None:
    joblib.dump(
        {
            "target": model.target,
            "booster": model.booster,
            "calibrators": model.calibrators,
            "feature_columns": model.feature_columns,
            "feature_version": model.feature_version,
        },
        path,
    )


def load_artifact(path: str | Path) -> TrainedModel:
    payload = joblib.load(path)
    return TrainedModel(
        target=payload["target"],
        booster=payload["booster"],
        calibrators=payload["calibrators"],
        feature_columns=payload["feature_columns"],
        feature_version=payload["feature_version"],
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ml_models.py -v`
Expected: PASS (calibration improves Brier; models train/predict/reload).

- [ ] **Step 5: Commit**

```bash
git add app/ml/models.py tests/test_ml_models.py
git commit -m "feat: 新增 LightGBM 1X2/讓球模型訓練與 isotonic 校準"
```

---

### Task 9: Registry (`app/ml/registry.py`)

**Files:**
- Create: `app/ml/registry.py`
- Test: `tests/test_ml_registry.py`

**Interfaces:**
- Consumes: `ModelVersion`; `TARGET_1X2`, `TARGET_HANDICAP` (re-exported from `app/ml/models.py`).
- Produces: `STATUS_CHAMPION`/`STATUS_CHALLENGER`/`STATUS_RETIRED`; `get_champion(session, target) -> ModelVersion | None`; `register_challenger(session, target, algorithm, params, metrics, artifact_path) -> ModelVersion`; `gate_passes(challenger_metrics, champion_metrics, margin) -> bool`; `promote(session, version) -> None`; `maybe_promote(session, challenger, margin) -> bool`; `rollback(session, target) -> ModelVersion | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ml_registry.py`:

```python
from app.ml.registry import (
    STATUS_CHAMPION,
    STATUS_RETIRED,
    gate_passes,
    get_champion,
    maybe_promote,
    register_challenger,
    rollback,
)
from ml_helpers import make_db


def test_gate_passes() -> None:
    assert gate_passes({"brier": 0.18, "clv_mean_edge": None}, {"brier": 0.20}, 0.0)
    assert not gate_passes({"brier": 0.20}, {"brier": 0.20}, 0.0)  # not better
    assert not gate_passes({"brier": 0.19}, {"brier": 0.20}, 0.05)  # not better by margin
    assert not gate_passes(
        {"brier": 0.18, "clv_mean_edge": 0.01},
        {"brier": 0.20, "clv_mean_edge": 0.02},
        0.0,
    )  # CLV worse


async def test_promote_and_rollback(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            first = await register_challenger(
                session, "1x2", "lightgbm", {}, {"brier": 0.20}, "/a.joblib"
            )
            assert await maybe_promote(session, first, 0.0)  # first becomes champion
            champion = await get_champion(session, "1x2")
            assert champion is not None and champion.id == first.id

            better = await register_challenger(
                session, "1x2", "lightgbm", {}, {"brier": 0.15}, "/b.joblib"
            )
            assert await maybe_promote(session, better, 0.0)
            champion = await get_champion(session, "1x2")
            assert champion is not None and champion.id == better.id

            previous = await rollback(session, "1x2")
            assert previous is not None and previous.id == first.id
            champion = await get_champion(session, "1x2")
            assert champion is not None and champion.id == first.id
            assert better.status == STATUS_RETIRED
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ml_registry.py -v`
Expected: FAIL — `No module named 'app.ml.registry'`.

- [ ] **Step 3: Implement**

Create `app/ml/registry.py`:

```python
"""Model version registry: champion/challenger gate, promote, rollback."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelVersion
from app.ml.models import TARGET_1X2, TARGET_HANDICAP  # noqa: F401  (re-exported for callers)

STATUS_CHAMPION = "champion"
STATUS_CHALLENGER = "challenger"
STATUS_RETIRED = "retired"


async def get_champion(session: AsyncSession, target: str) -> ModelVersion | None:
    stmt = (
        select(ModelVersion)
        .where(ModelVersion.target == target)
        .where(ModelVersion.status == STATUS_CHAMPION)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def register_challenger(
    session: AsyncSession,
    target: str,
    algorithm: str,
    params: dict,
    metrics: dict,
    artifact_path: str,
) -> ModelVersion:
    version = ModelVersion(
        target=target,
        algorithm=algorithm,
        params=params,
        metrics=metrics,
        artifact_path=artifact_path,
        status=STATUS_CHALLENGER,
    )
    session.add(version)
    await session.flush()
    return version


def gate_passes(challenger_metrics: dict, champion_metrics: dict, margin: float) -> bool:
    """Promote only when the challenger is at least ``margin`` better on Brier and
    its CLV mean edge is not worse (missing CLV on either side passes)."""
    challenger_brier = challenger_metrics.get("brier")
    champion_brier = champion_metrics.get("brier")
    if challenger_brier is None or champion_brier is None:
        return False
    if challenger_brier > champion_brier - margin:
        return False
    challenger_clv = challenger_metrics.get("clv_mean_edge")
    champion_clv = champion_metrics.get("clv_mean_edge")
    if challenger_clv is not None and champion_clv is not None and challenger_clv < champion_clv:
        return False
    return True


async def promote(session: AsyncSession, version: ModelVersion) -> None:
    """Make ``version`` the champion, retiring any current champion."""
    current = await get_champion(session, version.target)
    if current is not None and current.id != version.id:
        current.status = STATUS_RETIRED
        await session.flush()
    version.status = STATUS_CHAMPION
    version.promoted_at = datetime.now(UTC)
    await session.flush()


async def maybe_promote(session: AsyncSession, challenger: ModelVersion, margin: float) -> bool:
    champion = await get_champion(session, challenger.target)
    if champion is None:
        await promote(session, challenger)
        return True
    if gate_passes(challenger.metrics, champion.metrics, margin):
        await promote(session, challenger)
        return True
    return False


async def rollback(session: AsyncSession, target: str) -> ModelVersion | None:
    """Restore the most recently promoted retired version as champion."""
    stmt = (
        select(ModelVersion)
        .where(ModelVersion.target == target)
        .where(ModelVersion.status == STATUS_RETIRED)
        .where(ModelVersion.promoted_at.is_not(None))
        .order_by(ModelVersion.promoted_at.desc())
        .limit(1)
    )
    previous = (await session.execute(stmt)).scalar_one_or_none()
    if previous is None:
        return None
    await promote(session, previous)
    return previous
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ml_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ml/registry.py tests/test_ml_registry.py
git commit -m "feat: 新增模型註冊表（champion/challenger 閘門、晉升、回滾）"
```

---

### Task 10: Serving (`app/ml/predict.py`)

**Files:**
- Create: `app/ml/predict.py`
- Test: `tests/test_ml_predict.py`

**Interfaces:**
- Consumes: `Settings`; `Match`, `League`, `Season`, `Prediction`, `MatchFeature`, `ModelVersion`; `load_training_rows`, `load_market_priors`; `MarketPrior`, `MatchRow`, `build_feature_rows`, `FEATURE_VERSION`; `TARGET_1X2`, `TARGET_HANDICAP`, `TrainedModel`, `load_artifact`, `predict_proba`; `get_champion`; `edge`, `fair_odds`, `is_value`, `kelly_fraction`; `is_whole_or_half`.
- Produces: `Champion`; `UpcomingMatch`; `load_champion(session, target) -> Champion | None`; `load_upcoming_matches(session, settings, now) -> list[UpcomingMatch]`; `build_prediction_rows(upcoming, feature_row, champion_1x2, champion_handicap, prior, threshold) -> list[Prediction]`; `upsert_predictions(session, rows) -> int`; `upsert_feature(session, match_id, features) -> None`; `predict_match(session, upcoming, champion_1x2, champion_handicap, settings) -> list[Prediction]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ml_predict.py`:

```python
from datetime import UTC, datetime

from app.ml.features import FEATURE_COLUMNS, FeatureRow, MarketPrior
from app.ml.predict import Champion, UpcomingMatch, build_prediction_rows


def _feature_row(match_id, kickoff):
    return FeatureRow(
        match_id=match_id, kickoff_time=kickoff, features={c: 0.0 for c in FEATURE_COLUMNS}
    )


def test_build_prediction_rows_marks_value() -> None:
    kickoff = datetime(2026, 8, 1, tzinfo=UTC)
    upcoming = UpcomingMatch(1, kickoff, 1, 2, "EPL", "2026/27")
    prior = MarketPrior(
        had_probs={"H": 0.40, "D": 0.30, "A": 0.30},
        had_odds={"H": 2.5, "D": 3.3, "A": 3.3},
        hdc_line=-0.5,
        hdc_probs={"H": 0.45, "A": 0.55},
        hdc_odds={"H": 2.0, "A": 1.8},
    )
    champion = Champion(version=type("V", (), {"id": 7})(), model=None)
    rows = build_prediction_rows(
        upcoming,
        _feature_row(1, kickoff),
        champion_1x2=champion,
        champion_handicap=None,
        prior=prior,
        threshold=0.02,
        probs_1x2={"H": 0.5, "D": 0.28, "A": 0.22},
    )
    home = next(r for r in rows if r.outcome == "H")
    assert home.implied_prob == 0.40
    assert home.edge > 0
    assert home.recommended_fraction > 0
    assert home.fair_odds == 2.0
```

Note: this test asserts the pure computation path; the final `build_prediction_rows` signature takes precomputed 1X2 probs to keep the helper pure and testable. Implement `build_prediction_rows` with that signature (see Step 3).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ml_predict.py -v`
Expected: FAIL — `No module named 'app.ml.predict'`.

- [ ] **Step 3: Implement**

Create `app/ml/predict.py`:

```python
"""Champion serving: build features, predict, upsert prediction rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import League, Match, MatchFeature, ModelVersion, Prediction, Season
from app.ml.dataset import load_market_priors, load_training_rows
from app.ml.features import FEATURE_VERSION, FeatureRow, MarketPrior, MatchRow, build_feature_rows
from app.ml.labels import is_whole_or_half
from app.ml.models import TARGET_1X2, TARGET_HANDICAP, TrainedModel, load_artifact, predict_proba
from app.ml.registry import get_champion
from app.ml.value import edge, fair_odds, is_value, kelly_fraction

OUTCOMES_1X2 = ("H", "D", "A")
OUTCOMES_HANDICAP = ("H", "A")


@dataclass
class Champion:
    version: ModelVersion
    model: TrainedModel | None


@dataclass(frozen=True)
class UpcomingMatch:
    match_id: int
    kickoff_time: datetime
    home_team_id: int
    away_team_id: int
    league_code: str
    season_label: str


async def load_champion(session: AsyncSession, target: str) -> Champion | None:
    version = await get_champion(session, target)
    if version is None:
        return None
    return Champion(version=version, model=load_artifact(version.artifact_path))


async def load_upcoming_matches(
    session: AsyncSession, settings: Settings, now: datetime
) -> list[UpcomingMatch]:
    horizon = now + timedelta(hours=settings.ml_predict_lookahead_hours)
    stmt = (
        select(Match, League.code, Season.label)
        .join(League, League.id == Match.league_id)
        .join(Season, Season.id == Match.season_id)
        .where(Match.status == "scheduled")
        .where(Match.kickoff_time >= now)
        .where(Match.kickoff_time <= horizon)
        .where(League.code.in_(settings.league_whitelist))
        .order_by(Match.kickoff_time, Match.id)
    )
    return [
        UpcomingMatch(
            match_id=match.id,
            kickoff_time=match.kickoff_time,
            home_team_id=match.home_team_id,
            away_team_id=match.away_team_id,
            league_code=code,
            season_label=season_label,
        )
        for match, code, season_label in (await session.execute(stmt)).all()
    ]


def _rows_for(
    upcoming: UpcomingMatch,
    champion: Champion,
    target: str,
    prob_map: dict[str, float],
    prior: MarketPrior | None,
    threshold: float,
) -> list[Prediction]:
    rows: list[Prediction] = []
    for outcome, model_prob in prob_map.items():
        fair_prob = market_odds = None
        if target == TARGET_1X2 and prior is not None and prior.had_probs is not None:
            fair_prob = prior.had_probs.get(outcome)
            market_odds = (prior.had_odds or {}).get(outcome)
        elif target == TARGET_HANDICAP and prior is not None and prior.hdc_probs is not None:
            fair_prob = prior.hdc_probs.get(outcome)
            market_odds = (prior.hdc_odds or {}).get(outcome)
        edge_value = edge(model_prob, fair_prob) if fair_prob is not None else None
        fraction = 0.0
        if market_odds is not None and edge_value is not None and is_value(edge_value, threshold):
            fraction = kelly_fraction(model_prob, market_odds)
        rows.append(
            Prediction(
                match_id=upcoming.match_id,
                target=target,
                outcome=outcome,
                model_version_id=champion.version.id,
                prob=model_prob,
                implied_prob=fair_prob,
                edge=edge_value,
                fair_odds=fair_odds(model_prob),
                market_odds=market_odds,
                recommended_fraction=fraction,
            )
        )
    return rows


def build_prediction_rows(
    upcoming: UpcomingMatch,
    feature_row: FeatureRow,
    champion_1x2: Champion | None,
    champion_handicap: Champion | None,
    prior: MarketPrior | None,
    threshold: float,
    probs_1x2: dict[str, float] | None = None,
    probs_handicap: dict[str, float] | None = None,
) -> list[Prediction]:
    """Build prediction rows. ``probs_*`` may be supplied directly (tests) or are
    computed from the champion models when omitted."""
    rows: list[Prediction] = []
    if champion_1x2 is not None:
        if probs_1x2 is None:
            assert champion_1x2.model is not None
            values = predict_proba(champion_1x2.model, [feature_row.features])[0]
            probs_1x2 = {outcome: float(values[i]) for i, outcome in enumerate(OUTCOMES_1X2)}
        rows.extend(
            _rows_for(upcoming, champion_1x2, TARGET_1X2, probs_1x2, prior, threshold)
        )
    if champion_handicap is not None and prior is not None and prior.hdc_line is not None:
        if not is_whole_or_half(prior.hdc_line):
            return rows
        if probs_handicap is None:
            assert champion_handicap.model is not None
            home_prob = float(predict_proba(champion_handicap.model, [feature_row.features])[0])
            probs_handicap = {"H": home_prob, "A": 1.0 - home_prob}
        rows.extend(
            _rows_for(upcoming, champion_handicap, TARGET_HANDICAP, probs_handicap, prior, threshold)
        )
    return rows


async def upsert_predictions(session: AsyncSession, rows: list[Prediction]) -> int:
    count = 0
    for row in rows:
        existing = (
            await session.execute(
                select(Prediction).where(
                    Prediction.match_id == row.match_id,
                    Prediction.target == row.target,
                    Prediction.outcome == row.outcome,
                    Prediction.model_version_id == row.model_version_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(row)
        else:
            existing.prob = row.prob
            existing.implied_prob = row.implied_prob
            existing.edge = row.edge
            existing.fair_odds = row.fair_odds
            existing.market_odds = row.market_odds
            existing.recommended_fraction = row.recommended_fraction
        count += 1
    await session.flush()
    return count


async def upsert_feature(session: AsyncSession, match_id: int, features: dict[str, float]) -> None:
    existing = (
        await session.execute(
            select(MatchFeature).where(
                MatchFeature.match_id == match_id,
                MatchFeature.feature_version == FEATURE_VERSION,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            MatchFeature(match_id=match_id, feature_version=FEATURE_VERSION, features=features)
        )
    else:
        existing.features = features
        existing.built_at = datetime.now(UTC)
    await session.flush()


async def predict_match(
    session: AsyncSession,
    upcoming: UpcomingMatch,
    champion_1x2: Champion | None,
    champion_handicap: Champion | None,
    settings: Settings,
) -> list[Prediction]:
    target_row = MatchRow(
        match_id=upcoming.match_id,
        kickoff_time=upcoming.kickoff_time,
        home_team_id=upcoming.home_team_id,
        away_team_id=upcoming.away_team_id,
        league_code=upcoming.league_code,
        season_label=upcoming.season_label,
    )
    history = await load_training_rows(session, settings, before=upcoming.kickoff_time)
    prior = (await load_market_priors(session, [target_row]))[upcoming.match_id]
    feature_rows = build_feature_rows([*history, target_row], {upcoming.match_id: prior})
    feature_row = next(row for row in feature_rows if row.match_id == upcoming.match_id)
    await upsert_feature(session, upcoming.match_id, feature_row.features)
    return build_prediction_rows(
        upcoming,
        feature_row,
        champion_1x2,
        champion_handicap,
        prior,
        settings.ml_value_edge_threshold,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ml_predict.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ml/predict.py tests/test_ml_predict.py
git commit -m "feat: 新增冠軍模型推論與預測寫入模組"
```

---

### Task 11: Jobs and scheduler wiring (`app/ml/jobs.py`, `app/scheduler.py`)

**Files:**
- Create: `app/ml/jobs.py`
- Modify: `app/scheduler.py`
- Test: `tests/test_ml_jobs.py`

**Interfaces:**
- Consumes: `Settings`; `async_sessionmaker`; `build_dataset`, `load_hkjc_priors`; `train_1x2`, `train_handicap`, `save_artifact`, `predict_proba`, `TARGET_1X2`, `TARGET_HANDICAP`; `register_challenger`, `maybe_promote`, `get_champion`; `load_champion`, `load_upcoming_matches`, `predict_match`, `upsert_predictions`; `track_run`; `clv_metrics`.
- Produces: `predict_upcoming(session_factory, settings) -> int`; `retrain(session_factory, settings) -> int`; `_train_challenger_sync(dataset, closing_priors, settings) -> dict | None`; `PREDICT_JOB_ID = "ml_predict"`, `RETRAIN_JOB_ID = "ml_retrain"`, `PREDICT_INTERVAL_SECONDS = 3600`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ml_jobs.py`:

```python
from datetime import UTC, datetime

from app.config import Settings
from app.ml.jobs import PREDICT_JOB_ID, RETRAIN_JOB_ID, build_ml_scheduler, predict_upcoming
from ml_helpers import make_db


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, ml_enable=True, **overrides)


def test_build_ml_scheduler_registers_jobs() -> None:
    scheduler = build_ml_scheduler(_settings(), session_factory=None)
    ids = {job.id for job in scheduler.get_jobs()}
    assert PREDICT_JOB_ID in ids and RETRAIN_JOB_ID in ids


async def test_predict_upcoming_no_champion_is_noop(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        count = await predict_upcoming(db.session_factory, _settings())
        assert count == 0
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ml_jobs.py -v`
Expected: FAIL — `No module named 'app.ml.jobs'`.

- [ ] **Step 3: Implement `app/ml/jobs.py`**

```python
"""Scheduled ML jobs: predict upcoming matches, retrain (off the event loop)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import League, Match, Season
from app.ml.dataset import Dataset, build_dataset, load_hkjc_priors
from app.ml.features import FEATURE_COLUMNS, MatchRow
from app.ml.models import (
    TARGET_1X2,
    TARGET_HANDICAP,
    predict_proba,
    save_artifact,
    train_1x2,
    train_handicap,
)
from app.ml.predict import (
    load_champion,
    load_upcoming_matches,
    predict_match,
    upsert_predictions,
)
from app.ml.registry import maybe_promote, register_challenger
from app.ml.value import clv_metrics
from app.services.runs import track_run

logger = logging.getLogger(__name__)

PREDICT_JOB_ID = "ml_predict"
RETRAIN_JOB_ID = "ml_retrain"
PREDICT_INTERVAL_SECONDS = 3600


async def predict_upcoming(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> int:
    async def work(session: AsyncSession) -> int:
        now = datetime.now(UTC)
        champion_1x2 = await load_champion(session, TARGET_1X2)
        champion_handicap = await load_champion(session, TARGET_HANDICAP)
        if champion_1x2 is None and champion_handicap is None:
            logger.info("no champion models yet; skipping prediction")
            return 0
        upcoming = await load_upcoming_matches(session, settings, now)
        count = 0
        for match in upcoming:
            rows = await predict_match(session, match, champion_1x2, champion_handicap, settings)
            count += await upsert_predictions(session, rows)
        return count

    return await track_run(session_factory, PREDICT_JOB_ID, work)


async def _eval_closing_priors(
    session: AsyncSession, dataset: Dataset
) -> dict[int, dict[str, float]]:
    rows = [
        MatchRow(
            match_id=int(record.match_id),
            kickoff_time=record.kickoff_time.to_pydatetime()
            if hasattr(record.kickoff_time, "to_pydatetime")
            else record.kickoff_time,
            home_team_id=0,
            away_team_id=0,
            league_code="EPL",
            season_label="",
        )
        for record in dataset.eval.itertuples()
    ]
    priors = await load_hkjc_priors(session, rows)
    return {
        match_id: prior.had_probs
        for match_id, prior in priors.items()
        if prior.had_probs is not None
    }


def _model_probs_1x2(model, frame: pd.DataFrame) -> dict[int, dict[str, float]]:
    probs = predict_proba(model, frame[FEATURE_COLUMNS].to_dict("records"))
    return {
        int(match_id): {"H": float(row[0]), "D": float(row[1]), "A": float(row[2])}
        for match_id, row in zip(frame["match_id"].tolist(), probs, strict=True)
    }


def _train_challenger_sync(
    dataset: Dataset,
    closing_priors: dict[int, dict[str, float]],
    settings: Settings,
) -> dict | None:
    if len(dataset.train) < settings.ml_min_train_rows:
        logger.warning(
            "retrain skipped: %d train rows < %d", len(dataset.train), settings.ml_min_train_rows
        )
        return None
    artifact_dir = Path(settings.ml_artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    result: dict = {}
    try:
        model_1x2 = train_1x2(dataset.train, dataset.calibration, dataset.eval)
    except ValueError as exc:
        logger.warning("1x2 training skipped: %s", exc)
    else:
        clv = clv_metrics(_model_probs_1x2(model_1x2, dataset.eval), closing_priors)
        metrics = {**model_1x2.metrics, **clv}
        path = artifact_dir / f"1x2-{stamp}.joblib"
        save_artifact(model_1x2, path)
        result[TARGET_1X2] = {
            "path": str(path),
            "params": {"num_trees": int(model_1x2.booster.num_trees())},
            "metrics": metrics,
        }
    try:
        model_handicap = train_handicap(dataset.train, dataset.calibration, dataset.eval)
    except ValueError as exc:
        logger.warning("handicap training skipped: %s", exc)
    else:
        path = artifact_dir / f"handicap-{stamp}.joblib"
        save_artifact(model_handicap, path)
        result[TARGET_HANDICAP] = {
            "path": str(path),
            "params": {"num_trees": int(model_handicap.booster.num_trees())},
            "metrics": model_handicap.metrics,
        }
    return result


async def retrain(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> int:
    async def work(session: AsyncSession) -> int:
        try:
            dataset = await build_dataset(session, settings)
        except ValueError as exc:
            logger.warning("retrain skipped: %s", exc)
            return 0
        closing_priors = await _eval_closing_priors(session, dataset)
        result = await asyncio.to_thread(_train_challenger_sync, dataset, closing_priors, settings)
        if not result:
            return 0
        promoted = 0
        for target, payload in result.items():
            version = await register_challenger(
                session,
                target,
                settings.ml_1x2_model,
                payload["params"],
                payload["metrics"],
                payload["path"],
            )
            if await maybe_promote(session, version, settings.ml_champion_margin):
                promoted += 1
        return promoted

    return await track_run(session_factory, RETRAIN_JOB_ID, work)


def build_ml_scheduler(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    scheduler: AsyncIOScheduler | None = None,
) -> AsyncIOScheduler:
    """Register the ML jobs on an (optionally provided) AsyncIOScheduler."""
    scheduler = scheduler or AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        predict_upcoming,
        "interval",
        seconds=PREDICT_INTERVAL_SECONDS,
        args=[session_factory, settings],
        id=PREDICT_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        retrain,
        "interval",
        seconds=settings.ml_retrain_interval,
        args=[session_factory, settings],
        id=RETRAIN_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
```

- [ ] **Step 4: Wire into `app/scheduler.py`**

Read `app/scheduler.py`; in the function that builds/starts the scheduler (where `settings.enable_scheduler` is honoured), when `settings.ml_enable` is true, call `build_ml_scheduler(settings, session_factory, scheduler=scheduler)` to register the ML jobs on the same scheduler instance. Do not add a second scheduler. If `app/scheduler.py` has no session factory in scope, thread it through from the caller (`app/api/main.py` lifespan already builds `app.state.db`, so pass `app.state.db.session_factory`).

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_ml_jobs.py tests/test_scheduler.py -v && uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add app/ml/jobs.py app/scheduler.py tests/test_ml_jobs.py
git commit -m "feat: 新增 ML 排程（預測/重訓）並接入 APScheduler"
```

---

### Task 12: Read API (`app/api/schemas.py`, `app/api/routes.py`)

**Files:**
- Modify: `app/api/schemas.py`
- Modify: `app/api/routes.py`
- Test: `tests/test_ml_api.py`

**Interfaces:**
- Consumes: existing `SessionDep`, `Team`, `League`, `Match`, `Prediction`, `ModelVersion`.
- Produces: response models `PredictionOut`, `ModelOut`; routes `GET /predictions`, `GET /models`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ml_api.py`:

```python
from datetime import UTC, datetime

import httpx
import pytest

from app.api.main import create_app
from app.config import Settings
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team


async def _client(db):
    app = create_app(Settings(_env_file=None), db=db)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_list_models_empty(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with await _client(db) as client:
            response = await client.get("/models")
            assert response.status_code == 200
            assert response.json() == []
    finally:
        await db.dispose()


async def test_list_predictions_empty(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with await _client(db) as client:
            response = await client.get("/predictions")
            assert response.status_code == 200
            assert response.json() == []
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ml_api.py -v`
Expected: FAIL — 404 (routes not defined).

- [ ] **Step 3: Implement schemas**

Append to `app/api/schemas.py`:

```python
class PredictionOut(BaseModel):
    id: int
    match_id: int
    target: str
    outcome: str
    model_version_id: int
    prob: float
    implied_prob: float | None
    edge: float | None
    fair_odds: float
    market_odds: float | None
    recommended_fraction: float | None
    kickoff_time: datetime
    league_code: str
    home_team: str
    away_team: str


class ModelOut(BaseModel):
    id: int
    target: str
    algorithm: str
    status: str
    metrics: dict
    artifact_path: str
    created_at: datetime
    promoted_at: datetime | None
```

(Ensure `datetime` and `BaseModel` are already imported in the file; add if missing.)

- [ ] **Step 4: Implement routes**

Append to `app/api/routes.py` (reuse the existing `router`, `SessionDep`, and the `aliased` import pattern used by `/matches`):

```python
@router.get("/predictions", response_model=list[PredictionOut])
async def list_predictions(
    session: SessionDep,
    match_id: int | None = None,
    target: str | None = None,
    value_only: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[PredictionOut]:
    home = aliased(Team)
    away = aliased(Team)
    stmt = (
        select(Prediction, Match.kickoff_time, League.code, home.name_en, away.name_en)
        .join(Match, Match.id == Prediction.match_id)
        .join(League, League.id == Match.league_id)
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .order_by(Match.kickoff_time, Prediction.target, Prediction.outcome)
        .offset(offset)
        .limit(limit)
    )
    if match_id is not None:
        stmt = stmt.where(Prediction.match_id == match_id)
    if target is not None:
        stmt = stmt.where(Prediction.target == target)
    if value_only:
        stmt = stmt.where(Prediction.recommended_fraction > 0)
    rows = (await session.execute(stmt)).all()
    return [
        PredictionOut(
            id=prediction.id,
            match_id=prediction.match_id,
            target=prediction.target,
            outcome=prediction.outcome,
            model_version_id=prediction.model_version_id,
            prob=prediction.prob,
            implied_prob=prediction.implied_prob,
            edge=prediction.edge,
            fair_odds=prediction.fair_odds,
            market_odds=prediction.market_odds,
            recommended_fraction=prediction.recommended_fraction,
            kickoff_time=kickoff_time,
            league_code=league_code,
            home_team=home_name,
            away_team=away_name,
        )
        for prediction, kickoff_time, league_code, home_name, away_name in rows
    ]


@router.get("/models", response_model=list[ModelOut])
async def list_models(session: SessionDep) -> list[ModelOut]:
    stmt = select(ModelVersion).order_by(ModelVersion.target, ModelVersion.created_at.desc())
    return [
        ModelOut(
            id=version.id,
            target=version.target,
            algorithm=version.algorithm,
            status=version.status,
            metrics=version.metrics,
            artifact_path=version.artifact_path,
            created_at=version.created_at,
            promoted_at=version.promoted_at,
        )
        for version in (await session.execute(stmt)).scalars()
    ]
```

Add the needed imports at the top of `app/api/routes.py` (`Prediction`, `ModelVersion` from `app.db.models`; `PredictionOut`, `ModelOut` from `app.api.schemas`; `Query` from `fastapi` if not already imported).

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_ml_api.py -v && uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add app/api/schemas.py app/api/routes.py tests/test_ml_api.py
git commit -m "feat: 新增 /predictions 與 /models 唯讀端點"
```

---

### Task 13: End-to-end test and quality gates

**Files:**
- Create: `tests/test_ml_end_to_end.py`

**Interfaces:**
- Consumes: everything above.
- Produces: an end-to-end test (seed → dataset → train → register champion → predict → rows).

- [ ] **Step 1: Write the end-to-end test**

Create `tests/test_ml_end_to_end.py`:

```python
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.ml.dataset import build_dataset
from app.ml.models import TARGET_1X2, save_artifact, train_1x2
from app.ml.predict import load_champion, load_upcoming_matches, predict_match, upsert_predictions
from app.ml.registry import register_challenger
from app.ml.registry import maybe_promote
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team

HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}
HDC = {"lines": [{"condition": "-0.5", "main": True, "combinations": [
    {"str": "H", "currentOdds": "2.0"}, {"str": "A", "currentOdds": "1.9"}]}]}


async def test_end_to_end_train_then_predict(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        settings = Settings(
            _env_file=None,
            ml_enable=True,
            ml_min_train_rows=20,
            ml_history_from_year=2020,
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
            # one upcoming, unplayed match
            upcoming_match = await seed_finished_match(
                session, league, season, teams[0], teams[1],
                match_id_label="M_UP", kickoff=base + timedelta(days=90),
                home_score=0, away_score=0,
            )
            upcoming_match.status = "scheduled"
            await session.commit()

        # train a champion directly (bypasses the weekly job)
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
            upcoming = await load_upcoming_matches(session, settings, now)
            assert len(upcoming) == 1
            rows = await predict_match(session, upcoming[0], champion, None, settings)
            assert {row.outcome for row in rows} == {"H", "D", "A"}
            written = await upsert_predictions(session, rows)
            assert written == 3
            await session.commit()
        async with db.session_factory() as session:
            from sqlalchemy import select
            from app.db.models import Prediction

            stored = (await session.execute(select(Prediction))).scalars().all()
            assert len(stored) == 3
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run the end-to-end test**

Run: `uv run pytest tests/test_ml_end_to_end.py -v`
Expected: PASS.

- [ ] **Step 3: Run the full suite and lint**

Run: `uv run pytest && uv run ruff check .`
Expected: all tests pass (live tests deselected), ruff clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_ml_end_to_end.py
git commit -m "test: 新增 ML 子系統端到端測試（訓練→預測→寫入）"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Task(s) |
|---|---|
| §3 locked decisions (all 6) | Global Constraints + Tasks 3–13 |
| §4 `app/ml/` architecture + migration | Tasks 2, 3–11 (+12 API) |
| §5 as-of-kickoff features + no leakage | Task 6 (incl. two leakage tests) |
| §6 labels 1X2 + handicap main line, quarter skipped | Task 3 |
| §7 LightGBM + isotonic calibration + temporal validation | Task 8 |
| §8 de-vig / edge / Kelly fraction | Tasks 4, 5 |
| §9 Brier/log-loss vs market + CLV | Tasks 5 (`clv_metrics`), 8 (evaluate), 11 (CLV in retrain) |
| §10 retrain + champion/challenger gate + rollback | Tasks 9, 11 |
| §11 training data nuance (HKJC vs football-data prior) | Task 7 (Pinnacle + fallback), Task 11 (`load_hkjc_priors` for CLV) |
| §12 data model additions | Task 2 |
| §13 API `/predictions`, `/models` | Task 12 |
| §14 scheduling | Task 11 |
| §15 config `ML_*` | Task 1 |
| §16 testing (leakage, labels, de-vig, calibration, registry, e2e) | Tasks 3,4,6,8,9,13 |
| §17 risks (champion margin, worker training) | Tasks 11 (worker), 9 (margin) |

**2. Placeholder scan:** No `TBD`/`TODO`/"similar to Task N"; every code step carries the full body. (Verify: `grep -nE "TBD|TODO|similar to Task" <plan>` → only this line.)

**3. Type/name consistency:** `FEATURE_COLUMNS`, `MatchRow`, `MarketPrior`, `FeatureRow`, `FEATURE_VERSION` defined once in `app/ml/features.py` and imported everywhere; `TARGET_1X2`/`TARGET_HANDICAP` defined in `app/ml/models.py` and re-exported by `app/ml/registry.py`; `Dataset` in `dataset.py`; `Champion`/`UpcomingMatch` in `predict.py`; `track_run(session_factory, job, work)` matches the A-layer signature; `Settings` field names (`ml_*`) match Task 1. `build_prediction_rows` takes optional `probs_1x2`/`probs_handicap` so the pure path is unit-testable and the model path is used in production.

**4. Definition of done:** `uv run pytest` green (live deselected); `uv run ruff check .` clean; `alembic upgrade head` applies `0002`; with `ML_ENABLE=true` the scheduler registers the two ML jobs; a `champion` model serves rows into `/predictions`.



