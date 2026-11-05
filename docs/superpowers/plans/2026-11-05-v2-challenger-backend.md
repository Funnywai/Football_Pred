# V2 Market-Shrunk Challenger Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a second deterministic paper-betting lane, `challenger`, with `poisson-v2-shrunk` probabilities blended 50/50 with de-vigged T-30m HAD market probabilities, while g1 remains unchanged.

**Architecture:** A pure probability helper de-vigs market odds and reallocates the existing Poisson score distribution to the blended H/D/A probabilities. `decide_match()` keeps its g1 behaviour and then runs an optional challenger decision in an isolated savepoint. The challenger has its own lane experiment, bankroll account, decision logs and paper bets; settlement already scopes by `experiment_id`. Backend API endpoints expose the challenger summary and bets; UI is deferred.

**Tech Stack:** Python 3.12, SQLAlchemy, FastAPI, RQ, pytest, existing Poisson/EV/Kelly/Ledger modules.

## Global Constraints

- Do not change g1's model, strategy, decision slot, ledger, bankroll or existing API responses.
- Challenger lane name is exactly `challenger`.
- Challenger model version is exactly `poisson-v2-shrunk`.
- Challenger strategy version is exactly `g1`.
- Initial market weight is fixed at `Decimal("0.50")`; no live tuning.
- De-vig is proportional: inverse odds divided by their sum.
- Invalid/missing market odds skip the challenger only.
- Challenger writes must be isolated from g1 with a savepoint.
- No UI in this plan.
- No schema migration is needed; `LedgerExperiment.lane` is already a string.
- No commits or deployment unless explicitly requested by the user.

---

### Task 1: De-vig and market-shrinkage helpers

**Files:**
- Create: `packages/models/shrinkage.py`
- Test: `tests/models/test_shrinkage.py`

**Interfaces:**
- Produces:
  - `proportional_devig(odds: Mapping[Side, Decimal]) -> dict[Side, Decimal] | None`
  - `shrink_had_prediction(prediction: HadPrediction, odds: Mapping[Side, Decimal], weight: Decimal = Decimal("0.50")) -> HadPrediction | None`
  - `CHALLENGER_MODEL_VERSION: str = "poisson-v2-shrunk"`

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal

from packages.domain.enums import Side
from packages.models.poisson import HadPrediction
from packages.models.shrinkage import (
    CHALLENGER_MODEL_VERSION,
    proportional_devig,
    shrink_had_prediction,
)

D = Decimal


def _prediction() -> HadPrediction:
    return HadPrediction(
        p_home=D("0.60"),
        p_draw=D("0.25"),
        p_away=D("0.15"),
        score_distribution={
            (1, 0): D("0.60"),
            (0, 0): D("0.25"),
            (0, 1): D("0.15"),
        },
        tail_mass=D("0"),
        score_grid_max=10,
        tail_handling="truncated_renormalized",
    )


def test_proportional_devig_sums_to_one():
    market = proportional_devig(
        {Side.H: D("4.00"), Side.D: D("3.00"), Side.A: D("2.00")}
    )
    assert market is not None
    assert sum(market.values()) == D("1.000000000000000000000000000")


def test_proportional_devig_rejects_missing_or_invalid_odds():
    assert proportional_devig({Side.H: D("2.00")}) is None
    assert proportional_devig(
        {Side.H: D("1.00"), Side.D: D("3.00"), Side.A: D("3.00")}
    ) is None


def test_shrink_reallocates_score_distribution():
    result = shrink_had_prediction(
        _prediction(),
        {Side.H: D("2.00"), Side.D: D("4.00"), Side.A: D("4.00")},
    )
    assert result is not None
    assert result.model_version == CHALLENGER_MODEL_VERSION
    assert result.p_home == D("0.40")
    assert result.p_draw == D("0.30")
    assert result.p_away == D("0.30")
    assert result.score_distribution[(1, 0)] == D("0.40")
    assert result.score_distribution[(0, 0)] == D("0.30")
    assert result.score_distribution[(0, 1)] == D("0.30")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/models/test_shrinkage.py -v`

Expected: FAIL because `packages.models.shrinkage` does not exist.

- [ ] **Step 3: Implement the helper**

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType

from packages.domain.enums import Side
from packages.models.poisson import HadPrediction

CHALLENGER_MODEL_VERSION = "poisson-v2-shrunk"
HAD_SIDES: tuple[Side, Side, Side] = (Side.H, Side.D, Side.A)
_PROBABILITY_TOLERANCE = Decimal("1e-9")
_ZERO = Decimal(0)


def proportional_devig(
    odds: Mapping[Side, Decimal],
) -> dict[Side, Decimal] | None:
    if set(odds) != set(HAD_SIDES):
        return None
    inverse: dict[Side, Decimal] = {}
    for side in HAD_SIDES:
        value = odds[side]
        if not value.is_finite() or value <= Decimal(1):
            return None
        inverse[side] = Decimal(1) / value
    total = sum(inverse.values(), _ZERO)
    if not total.is_finite() or total <= _ZERO:
        return None
    probabilities = {side: inverse[side] / total for side in HAD_SIDES}
    if abs(sum(probabilities.values(), _ZERO) - Decimal(1)) > _PROBABILITY_TOLERANCE:
        return None
    return probabilities


def _outcome(score: tuple[int, int]) -> Side:
    home, away = score
    if home > away:
        return Side.H
    if home < away:
        return Side.A
    return Side.D


def shrink_had_prediction(
    prediction: HadPrediction,
    odds: Mapping[Side, Decimal],
    weight: Decimal = Decimal("0.50"),
) -> HadPrediction | None:
    if not weight.is_finite() or weight < _ZERO or weight > Decimal(1):
        return None
    market = proportional_devig(odds)
    if market is None:
        return None
    model = {
        Side.H: prediction.p_home,
        Side.D: prediction.p_draw,
        Side.A: prediction.p_away,
    }
    blended = {
        side: weight * model[side] + (Decimal(1) - weight) * market[side]
        for side in HAD_SIDES
    }
    if any(value <= _ZERO for value in blended.values()):
        return None
    if abs(sum(blended.values(), _ZERO) - Decimal(1)) > _PROBABILITY_TOLERANCE:
        return None

    old_totals = {side: _ZERO for side in HAD_SIDES}
    for score, probability in prediction.score_distribution.items():
        old_totals[_outcome(score)] += probability
    scaled: dict[tuple[int, int], Decimal] = {}
    for score, probability in prediction.score_distribution.items():
        side = _outcome(score)
        old = old_totals[side]
        if old <= _ZERO:
            return None
        scaled[score] = probability * blended[side] / old
    scaled_total = sum(scaled.values(), _ZERO)
    if abs(scaled_total - Decimal(1)) > _PROBABILITY_TOLERANCE:
        return None
    return replace(
        prediction,
        p_home=blended[Side.H],
        p_draw=blended[Side.D],
        p_away=blended[Side.A],
        score_distribution=MappingProxyType(scaled),
        model_version=CHALLENGER_MODEL_VERSION,
        tail_handling="market_shrunk",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/models/test_shrinkage.py -v`

Expected: PASS.

---

### Task 2: Challenger decision path in `packages/decision/service.py`

**Files:**
- Modify: `packages/decision/service.py:136-460`
- Test: `tests/decision/test_service.py`

**Interfaces:**
- Consumes: `proportional_devig`, `shrink_had_prediction`, `CHALLENGER_MODEL_VERSION`.
- Produces:
  - `decide_challenger_match(session, match, snapshot, *, now=None) -> DecisionResult | None`
  - Existing `decide_match(session, match, snapshot, *, now=None) -> DecisionResult` keeps g1 behaviour and runs the challenger after the g1 log.

- [ ] **Step 1: Write the failing test**

Add a test that seeds a challenger `LedgerExperiment` and a T-30m snapshot, calls `decide_match`, then asserts:

```python
from packages.ledger.experiments import create_next_experiment

experiment = create_next_experiment(
    session,
    label="v2-market-shrunk",
    model_version="poisson-v2-shrunk",
    strategy_version="g1",
    lane="challenger",
)
_ = decide_match(session, match, snapshot, now=NOW)
challenger_bet = session.scalar(
    select(PaperBet).where(PaperBet.experiment_id == experiment.id)
)
assert challenger_bet is not None
assert challenger_bet.decision_slot_key.startswith(f"g1:{experiment.id}:")
```

Also assert:
- g1 bet still uses the deterministic active experiment.
- challenger `ModelPrediction` rows have `model_version == "poisson-v2-shrunk"`.
- with no challenger experiment, no challenger bet/log is created.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_service.py -k challenger -v`

Expected: FAIL because no challenger decision exists.

- [ ] **Step 3: Implement**

Add imports and constants:

```python
from packages.models.shrinkage import (
    CHALLENGER_MODEL_VERSION,
    shrink_had_prediction,
)
from packages.ledger.experiments import active_experiment
```

Add `model_version: str | None = None` and `market_weight: Decimal | None = None` parameters to `_decide_match`. After `prediction = predict_had(...)`:

```python
if model_version == CHALLENGER_MODEL_VERSION:
    market_odds = {
        side: lines[side].odds_decimal for side in _HAD_SIDES
    }
    shrunken = shrink_had_prediction(
        prediction,
        market_odds,
        market_weight if market_weight is not None else Decimal("0.50"),
    )
    if shrunken is None:
        return _skipped("market shrinkage unavailable")
    prediction = shrunken
```

Keep all later g1 EV/Kelly/stake logic unchanged. Add:

```python
def decide_challenger_match(
    session: Session,
    match: Match,
    snapshot: OddsSnapshot | None,
    *,
    now: datetime | None = None,
) -> DecisionResult | None:
    experiment = active_experiment(session, "challenger")
    if experiment is None:
        return None
    result = _decide_match(
        session,
        match,
        snapshot,
        now=now,
        experiment_id=experiment.id,
        experiment_is_legacy=False,
        model_version=CHALLENGER_MODEL_VERSION,
        market_weight=Decimal("0.50"),
    )
    _log_decision(
        session,
        match,
        snapshot,
        result,
        now=now,
        experiment_id=experiment.id,
        experiment_is_legacy=False,
    )
    return result
```

At the end of `decide_match`, after the g1 `_log_decision`, run the challenger in an isolated savepoint:

```python
try:
    with session.begin_nested():
        decide_challenger_match(session, match, snapshot, now=now)
except Exception:  # noqa: BLE001 - challenger must not break g1
    logger.exception("challenger decision failed for match %s", match.id)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/decision/test_service.py tests/decision/test_decision_log.py -v`

Expected: PASS, including existing g1 tests.

---

### Task 3: Challenger experiment creation

**Files:**
- Modify: `scripts/new_ledger_experiment.py:24-28`
- Test: `tests/ledger/test_ledger_experiments.py`

**Interfaces:**
- Produces: CLI accepts `--lane challenger`.

- [ ] **Step 1: Write failing test**

```python
def test_challenger_lane_keeps_deterministic_active():
    deterministic = create_next_experiment(
        session,
        label="baseline",
        model_version="poisson-v1",
        strategy_version="g1",
        lane="deterministic",
    )
    challenger = create_next_experiment(
        session,
        label="v2-market-shrunk",
        model_version="poisson-v2-shrunk",
        strategy_version="g1",
        lane="challenger",
    )
    assert active_experiment(session, "deterministic").id == deterministic.id
    assert active_experiment(session, "challenger").id == challenger.id
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run pytest tests/ledger/test_ledger_experiments.py -k challenger -v`

Expected: FAIL before the lane helper supports it (if the lane is already generic, keep the test as regression coverage).

- [ ] **Step 3: Implement**

Change CLI choices to:

```python
choices=("deterministic", "llm", "challenger"),
```

No schema migration.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ledger/test_ledger_experiments.py -v`

Expected: PASS.

---

### Task 4: Challenger backend API

**Files:**
- Modify: `apps/api/dashboard.py`
- Test: `tests/api/test_dashboard.py`

**Interfaces:**
- Produces:
  - `GET /dashboard/challenger` -> experiment, ledger, bankroll, counts
  - `GET /dashboard/challenger/bets?limit=100` -> challenger bets

- [ ] **Step 1: Write failing API test**

Create a challenger experiment, one challenger bet, and assert:

```python
response = client.get("/dashboard/challenger").json()
assert response["experiment"]["lane"] == "challenger"
assert response["ledger"]["pending_bets"] == 1

bets = client.get("/dashboard/challenger/bets").json()
assert len(bets) == 1
assert bets[0]["bet_id"] == str(challenger_bet.id)
```

Also assert `/dashboard/bets` still returns only deterministic g1 bets.

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/api/test_dashboard.py -k challenger -v`

Expected: FAIL with 404.

- [ ] **Step 3: Implement**

Extract the body of `bets()` into a helper:

```python
def _bets_for_experiment(
    session: Session,
    experiment: LedgerExperiment | None,
    limit: int,
) -> list[dict[str, Any]]:
    ...
```

Keep `@router.get("/bets")` calling `_bets_for_experiment(session, active_experiment(session), clamped)`.

Add:

```python
@router.get("/challenger")
def challenger(session: SessionDep) -> dict[str, Any]:
    experiment = active_experiment(session, "challenger")
    if experiment is None:
        return {"experiment": None, "ledger": None, "bankroll": None, "counts": None}
    ledger = LedgerService(session, experiment_id=experiment.id).summary()
    return {
        "experiment": {...},
        "ledger": {...},
        "bankroll": {...},
        "counts": {...},
    }


@router.get("/challenger/bets")
def challenger_bets(session: SessionDep, limit: int = 100) -> list[dict[str, Any]]:
    clamped = max(1, min(limit, 500))
    return _bets_for_experiment(
        session,
        active_experiment(session, "challenger"),
        clamped,
    )
```

Use the existing `_bankroll`, `_scoped_count`, and `LedgerService.summary()` shapes so the future UI can reuse them.

- [ ] **Step 4: Run API tests**

Run: `uv run pytest tests/api/test_dashboard.py -v`

Expected: PASS.

---

### Task 5: Backend verification and experiment bootstrap

**Files:**
- No source changes.
- Verify: full backend suite, ruff.
- Create: challenger experiment on the target DB only when the user asks to deploy.

- [ ] **Step 1: Run backend checks**

```bash
uv run ruff check .
uv run pytest -p no:warnings
```

Expected: all tests pass; ruff clean.

- [ ] **Step 2: Create challenger experiment when deploying**

```bash
uv run python scripts/new_ledger_experiment.py \
  --lane challenger \
  --label v2-market-shrunk \
  --model-version poisson-v2-shrunk \
  --strategy-version g1
```

- [ ] **Step 3: Verify one T-30m match**

Expected:
- g1 decision and bet unchanged.
- challenger decision and bet created with `poisson-v2-shrunk`.
- challenger API returns its own bankroll/ROI.
- settlement updates both bets independently.

## Self-review

- Spec coverage: lane/experiment, formula, g1 isolation, failure handling, API, settlement, tests are all mapped.
- No UI implementation is included.
- No schema migration is required.
- No live weight tuning is included.
- g1 remains the existing active deterministic experiment.
