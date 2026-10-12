# Quarter-Line Handicap Support (Phase 1: parse + settle) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the system *correct* about HKJC quarter handicap lines (`condition` like `-0.5/-1.0`) in the two places where being wrong silently corrupts data — **parsing** and **ledger settlement** — while keeping the v1 "no quarter-line bets" placement guard in place.

**Architecture:** A quarter line is not one bet but **two half-stakes** on the two adjacent half-lines (`-0.5/-1.0` → `-0.5` and `-1.0`). Phase 1 adds (a) parsing that yields the **midpoint** for feature storage plus a `quarter_halves()` helper that recovers the two halves, and (b) settlement that splits the stake across the halves and records `won` / `half_won` / `half_lost` / `lost`. It also hardens `temporal_split` so a match's rows can never straddle two splits (needed before Phase 2 emits more than one row per match). **No database migration.**

**Tech Stack:** unchanged (Python 3.11+, async SQLAlchemy 2.x, pytest, ruff).

## Global Constraints

- **Keep v1 semantics byte-for-byte for whole/half lines.** `parse_handicap_line("-1") == -1.0`, `" +0.5" == 0.5`, `"0" == 0.0`, `"" / None / "abc" -> None` must not change. Whole-line push stays `status="push"`, `payout=stake`.
- **Do NOT change `handicap_label`.** It is used by `app/ml/dataset.py:_frame` (training labels) and `app/services/ledger.py:settle_bets`. Quarter support goes in *new* functions.
- **Do NOT add `line` to `predictions` uniqueness.** One `H` and one `A` prediction per (match, target, model_version) stays.
- **Do NOT auto-correct or re-settle any existing `ledger_bets` row.** Settlement is idempotent by design (`status == "pending"` filter); once a row leaves `pending` it is history.
- **Placement guard stays:** `place_bets` keeps skipping handicap when `not is_whole_or_half(line)`. Phase 1 makes the ledger *capable* of settling quarter lines; it does not start betting them.
- **No schema change / no migration.** `LedgerBet.status` is `String(20)` (`half_won` = 8 chars), `payout`/`profit` are floats. `summary()`, `_bankroll_now`, `equity_curve`, `/bets/summary` (roi, yield_pct) and `BetOut.status` already aggregate on `status != "pending"` + `stake`/`profit`, so nothing else changes.
- **Float discipline:** quarter lines are odd multiples of `0.25`; all half-line arithmetic is exact in binary floating point. Round reconstructed values to 10 decimals and never compare money with `==` across independent computations.
- Gates: `uv run pytest` (live deselected) + `uv run ruff check .`. Chinese `type: 描述` commits. Branch `feat/quarter-line-handicap`. Never commit to `main`.

## Confirmed payout math (Oracle-verified, verbatim)

Stake `S`, odds `O`, split `S/2` per half, same odds on both halves:

```
both halves win:     payout = S*O            profit = S*(O-1)
one win + one push:  payout = S*(O+1)/2      profit = S*(O-1)/2      -> half_won
one push + one loss: payout = S/2            profit = -S/2           -> half_lost
both halves lose:    payout = 0              profit = -S             -> lost
both halves push:    impossible (adjacent lines cannot both push)
```

Statuses for a quarter line: `won`, `half_won`, `half_lost`, `lost` (never `push`).

---

### Task 1: Quarter-line parsing

**Files:**
- Modify: `app/ml/labels.py` (add `QUARTER_STEP`, `quarter_halves()`, extend `parse_handicap_line`)
- Modify: `tests/test_ml_labels.py` (append)
- Modify: `tests/test_hkjc_provider.py:100-112` (the test that currently pins "quarter main line is unreadable")

**Interfaces:**
- Produces: `quarter_halves(line: float) -> tuple[float, float] | None` (returns `(low, high)` half-lines); `parse_handicap_line(condition: str | None) -> float | None` now also accepts `"a/b"` and returns the **midpoint**.
- Consumes: existing `is_whole_or_half(line: float) -> bool`, `QUARTER_EPSILON`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ml_labels.py`:

```python
from app.ml.labels import parse_handicap_line, quarter_halves


def test_parse_handicap_line_keeps_whole_and_half_exact():
    assert parse_handicap_line("-1") == -1.0
    assert parse_handicap_line("+0.5") == 0.5
    assert parse_handicap_line("0") == 0.0
    assert parse_handicap_line("-1.5") == -1.5
    assert parse_handicap_line("") is None
    assert parse_handicap_line(None) is None
    assert parse_handicap_line("abc") is None


def test_parse_handicap_line_returns_quarter_midpoint():
    assert parse_handicap_line("-0.5/-1.0") == -0.75
    assert parse_handicap_line("-1.0/-0.5") == -0.75
    assert parse_handicap_line("0.0/0.5") == 0.25
    assert parse_handicap_line("-0.5/x") is None


def test_quarter_halves():
    assert quarter_halves(-0.75) == (-1.0, -0.5)
    assert quarter_halves(-0.25) == (-0.5, 0.0)
    assert quarter_halves(0.25) == (0.0, 0.5)
    assert quarter_halves(1.75) == (1.5, 2.0)
    assert quarter_halves(-1.0) is None
    assert quarter_halves(0.0) is None
    assert quarter_halves(0.5) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ml_labels.py -q`
Expected: FAIL — `quarter_halves` is not defined; the quarter-midpoint assertions return `None`.

- [ ] **Step 3: Implement**

In `app/ml/labels.py`, add the constant next to `QUARTER_EPSILON` and replace `parse_handicap_line`, then append `quarter_halves`:

```python
QUARTER_STEP = 0.25


def parse_handicap_line(condition: str | None) -> float | None:
    """Parse an HKJC HDC ``condition`` (e.g. "-1", "+0.5", "0") into a float.

    Quarter lines ("-0.5/-1.0") return their **midpoint** (-0.75) so the value can be
    stored as the ``hdc_line`` feature; ``quarter_halves`` recovers the two halves.
    """
    if condition is None:
        return None
    text = condition.strip()
    if not text:
        return None
    if "/" in text:
        parts = text.split("/")
        if len(parts) != 2:
            return None
        try:
            first, second = float(parts[0]), float(parts[1])
        except ValueError:
            return None
        return round((first + second) / 2.0, 10)
    try:
        return float(text)
    except ValueError:
        return None


def quarter_halves(line: float) -> tuple[float, float] | None:
    """The two half-lines a quarter line splits into, as ``(low, high)``.

    ``-0.75 -> (-1.0, -0.5)``. Returns ``None`` for whole/half lines (they are not
    quarter lines) and for values that are not odd multiples of 0.25.
    """
    if is_whole_or_half(line):
        return None
    low = round(line - QUARTER_STEP, 10)
    high = round(line + QUARTER_STEP, 10)
    if not (is_whole_or_half(low) and is_whole_or_half(high)):
        return None
    return low, high
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ml_labels.py tests/test_ml_features.py -q`
Expected: PASS (feature tests prove the HAD/HDC parsers are untouched).

- [ ] **Step 5: Update the HKJC fixture test that pinned the gap**

In `tests/test_hkjc_provider.py`, replace the body of `test_real_pools_and_quarter_line_main_line` so it now asserts quarter support (the real main line is `-0.5/-1.0` with odds `'1.41'`/`'2.72'`):

```python
async def test_real_pools_and_quarter_line_main_line():
    matches = _load("hkjc_match_details.json")["data"]["matches"]
    pools = {pool["oddsType"]: pool for pool in matches[0]["foPools"]}
    had = hkjc_had_odds(pools["HAD"])
    assert had is not None
    assert set(had) == {"H", "D", "A"}
    main = hkjc_hdc_main(pools["HDC"])
    assert main is not None
    line, odds = main
    assert line == -0.75
    assert set(odds) == {"H", "A"}
    assert quarter_halves(line) == (-1.0, -0.5)
```

Add `from app.ml.labels import parse_handicap_line, quarter_halves` to that file's imports and drop the now-unused `parse_handicap_line(...) is None` / `hkjc_hdc_main(...) is None` assertions.

- [ ] **Step 6: Run the whole suite and lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all pass; no ruff findings.

- [ ] **Step 7: Commit**

```bash
git add app/ml/labels.py tests/test_ml_labels.py tests/test_hkjc_provider.py
git commit -m "feat: 讓球四分一線解析（中點儲存 + quarter_halves 取兩條半線）"
```

---

### Task 2: Quarter-line settlement

**Files:**
- Modify: `app/services/ledger.py` (add `_settle_handicap`, use it in `settle_bets`)
- Test: `tests/test_ledger_quarter.py` (create)

**Interfaces:**
- Consumes: `quarter_halves` (Task 1), existing `handicap_label(home_score, away_score, line) -> str | None`, `LedgerBet(line, odds, stake, outcome, status, payout, profit, settled_at, result_source)`.
- Produces: `_settle_handicap(bet: LedgerBet, home_score: int, away_score: int) -> tuple[str, float]` returning `(status, payout)`; `settle_bets` unchanged in signature.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ledger_quarter.py`:

```python
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.models import LedgerBet, Match, ModelVersion, Result
from app.services.ledger import settle_bets
from tests.ml_helpers import make_db, seed_context, seed_finished_match, seed_team

KICKOFF = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
STAKE = 100.0
ODDS = 1.8


async def _seed_model_version(session) -> None:
    """A LedgerBet references a model version; seed one so FK enforcement (if enabled) holds."""
    session.add(
        ModelVersion(
            id=1,
            target="handicap",
            algorithm="lightgbm",
            params={},
            metrics={},
            artifact_path="artifacts/ml/test.joblib",
        )
    )
    await session.flush()


@pytest.mark.parametrize(
    ("line", "outcome", "home", "away", "expected_status", "expected_payout"),
    [
        (-0.75, "H", 2, 1, "half_won", STAKE * (ODDS + 1.0) / 2.0),
        (-0.75, "H", 3, 1, "won", STAKE * ODDS),
        (-0.75, "H", 1, 1, "lost", 0.0),
        (-0.75, "A", 2, 1, "half_lost", STAKE / 2.0),
        (-0.75, "A", 1, 1, "won", STAKE * ODDS),
        (-0.75, "A", 3, 1, "lost", 0.0),
        (0.25, "H", 0, 0, "half_won", STAKE * (ODDS + 1.0) / 2.0),
        (0.25, "H", 1, 0, "won", STAKE * ODDS),
        (-1.0, "H", 2, 1, "push", STAKE),
        (-1.0, "H", 3, 1, "won", STAKE * ODDS),
    ],
)
async def test_settle_quarter_and_whole_lines(
    tmp_path, line, outcome, home, away, expected_status, expected_payout
):
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home_team = await seed_team(session, "Home FC")
            away_team = await seed_team(session, "Away FC")
            match = await seed_finished_match(
                session,
                league,
                season,
                home_team,
                away_team,
                match_id_label="M-Q1",
                kickoff=KICKOFF,
                home_score=home,
                away_score=away,
            )
            session.add(
                LedgerBet(
                    match_id=match.id,
                    target="handicap",
                    outcome=outcome,
                    model_version_id=1,
                    line=line,
                    odds=ODDS,
                    stake=STAKE,
                    bankroll_at_place=1000.0,
                    edge=0.03,
                    kelly_multiplier=0.5,
                )
            )
            await _seed_model_version(session)
            await session.commit()
        async with db.session_factory() as session:
            assert await settle_bets(session) == 1
            await session.commit()
        async with db.session_factory() as session:
            bet = (await session.execute(select(LedgerBet))).scalar_one()
            assert bet.status == expected_status
            assert bet.payout == pytest.approx(expected_payout)
            assert bet.profit == pytest.approx(expected_payout - STAKE)
    finally:
        await db.dispose()


async def test_settle_is_idempotent_for_quarter_lines(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home_team = await seed_team(session, "Home FC")
            away_team = await seed_team(session, "Away FC")
            match = await seed_finished_match(
                session,
                league,
                season,
                home_team,
                away_team,
                match_id_label="M-Q2",
                kickoff=KICKOFF,
                home_score=2,
                away_score=1,
            )
            session.add(
                LedgerBet(
                    match_id=match.id,
                    target="handicap",
                    outcome="H",
                    model_version_id=1,
                    line=-0.75,
                    odds=ODDS,
                    stake=STAKE,
                    bankroll_at_place=1000.0,
                    edge=0.03,
                    kelly_multiplier=0.5,
                )
            )
            await _seed_model_version(session)
            await session.commit()
        async with db.session_factory() as session:
            assert await settle_bets(session) == 1
            await session.commit()
        async with db.session_factory() as session:
            assert await settle_bets(session) == 0
            await session.commit()
    finally:
        await db.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ledger_quarter.py -q`
Expected: FAIL — every quarter case reports `status="push"` / `payout=100.0` (today's `handicap_label` returns `None` for a quarter line).

- [ ] **Step 3: Implement**

In `app/services/ledger.py`, import `quarter_halves` and add the helper above `settle_bets`:

```python
def _settle_handicap(bet: LedgerBet, home_score: int, away_score: int) -> tuple[str, float]:
    """``(status, payout)`` for a handicap bet: whole/half line, or a quarter line.

    A quarter line is two half-stakes on the two adjacent half-lines; when one half
    pushes and the other wins/loses the bet is ``half_won``/``half_lost``.
    """
    halves = quarter_halves(bet.line) if bet.line is not None else None
    if halves is None:
        if bet.line is None:
            return "push", bet.stake
        cover = handicap_label(home_score, away_score, bet.line)
        if cover is None:
            return "push", bet.stake
        return ("won", bet.stake * bet.odds) if cover == bet.outcome else ("lost", 0.0)

    half_stake = bet.stake / 2.0
    half_results: list[str] = []
    payout = 0.0
    for half_line in halves:
        cover = handicap_label(home_score, away_score, half_line)
        if cover is None:
            half_results.append("push")
            payout += half_stake
        elif cover == bet.outcome:
            half_results.append("won")
            payout += half_stake * bet.odds
        else:
            half_results.append("lost")
    settled_half = set(half_results)
    if settled_half == {"won"}:
        status = "won"
    elif settled_half == {"lost"}:
        status = "lost"
    elif settled_half == {"push"}:
        status = "push"
    elif "won" in settled_half:
        status = "half_won"
    else:
        status = "half_lost"
    return status, payout
```

Then replace the handicap branch inside `settle_bets` (currently `if bet.target == "handicap": ... elif label_1x2(...)`) with:

```python
        if bet.target == "handicap":
            if bet.line is None:
                logger.warning("handicap bet %s has no line; leaving it pending", bet.id)
                continue
            bet.status, bet.payout = _settle_handicap(bet, result.home_score, result.away_score)
        elif label_1x2(result.home_score, result.away_score) == bet.outcome:
```

(leave the `else: lost` branch and the `bet.profit = bet.payout - bet.stake` tail exactly as they are).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ledger_quarter.py tests/test_ledger.py tests/test_ledger_end_to_end.py -q`
Expected: PASS (existing whole/half tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add app/services/ledger.py tests/test_ledger_quarter.py
git commit -m "feat: 支援四分一線結算（won/half_won/half_lost/lost，無需 migration）"
```

---

### Task 3: `temporal_split` never splits a match

**Files:**
- Modify: `app/ml/dataset.py` (replace `temporal_split`, add `_match_starts` + `_snap_up`)
- Modify: `tests/test_ml_dataset.py` (append)

**Interfaces:**
- Produces: `temporal_split(df, calibration_fraction=CALIBRATION_FRACTION, eval_fraction=EVAL_FRACTION) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]` — same signature, now match-safe.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ml_dataset.py`:

```python
def _frame_for_split(match_ids: list[int], per_match: int) -> pd.DataFrame:
    rows = []
    for index, match_id in enumerate(match_ids):
        for line in range(per_match):
            rows.append(
                {
                    "match_id": match_id,
                    "kickoff_time": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index),
                    "label_1x2": "H",
                    "line": float(line),
                }
            )
    return pd.DataFrame.from_records(rows)


def test_temporal_split_keeps_a_match_in_one_split():
    frame = _frame_for_split(list(range(15)), per_match=2)   # 30 rows, 2 per match
    train, calibration, evaluation = temporal_split(frame)
    seen = [set(part["match_id"]) for part in (train, calibration, evaluation)]
    assert not (seen[0] & seen[1] or seen[0] & seen[2] or seen[1] & seen[2])
    assert sorted(seen[0] | seen[1] | seen[2]) == list(range(15))
```

Ensure the file imports `timedelta` alongside `datetime`/`UTC` and `pandas as pd` (add the imports if missing).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ml_dataset.py::test_temporal_split_keeps_a_match_in_one_split -v`
Expected: FAIL — with 30 rows the old code's train slice is `rows[:21]`, so match 10 owns rows 20 and 21 and is split across train (row 20) and calibration (row 21). Use a match count where `int(0.2*m*per_match) + int(0.1*m*per_match)` is **not** a multiple of `per_match`, otherwise the fractional boundaries happen to land on match starts and the test cannot fail.

- [ ] **Step 3: Implement**

Replace `temporal_split` in `app/ml/dataset.py` and add the two helpers directly above it:

```python
def _match_starts(df: pd.DataFrame) -> list[int]:
    """Row indices where a new ``match_id`` begins (df must be sorted by kickoff, match)."""
    starts = [0]
    previous = df["match_id"].iloc[0]
    for index in range(1, len(df)):
        if df["match_id"].iloc[index] != previous:
            starts.append(index)
            previous = df["match_id"].iloc[index]
    return starts


def _snap_up(boundaries: list[int], target: int, total: int) -> int:
    for index in boundaries:
        if index >= target:
            return index
    return total


def temporal_split(
    df: pd.DataFrame,
    calibration_fraction: float = CALIBRATION_FRACTION,
    eval_fraction: float = EVAL_FRACTION,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronological train/calibration/eval split that never splits a match.

    A match can contribute more than one row (a quarter line decomposes into two
    half-lines), so the fractional boundaries are snapped to the next match boundary:
    no match is ever represented in two splits, which would leak its feature vector
    into the evaluation window.
    """
    ordered = df.sort_values(["kickoff_time", "match_id"]).reset_index(drop=True)
    n = len(ordered)
    if n < MIN_DATASET_ROWS:
        raise ValueError(f"need at least {MIN_DATASET_ROWS} rows, got {n}")
    boundaries = _match_starts(ordered)
    cut_cal = _snap_up(boundaries, max(1, n - max(1, int(n * eval_fraction)) - max(1, int(n * calibration_fraction))), n)
    cut_eval = _snap_up(boundaries, max(cut_cal + 1, n - max(1, int(n * eval_fraction))), n)
    train = ordered.iloc[:cut_cal].copy()
    calibration = ordered.iloc[cut_cal:cut_eval].copy()
    evaluation = ordered.iloc[cut_eval:].copy()
    if train.empty or calibration.empty or evaluation.empty:
        raise ValueError(f"split leaves an empty slice (n={n})")
    return train, calibration, evaluation
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ml_dataset.py tests/test_ml_jobs.py tests/test_ml_end_to_end.py -q`
Expected: PASS. If an existing assertion hard-codes a slice length that shifted by at most the last match's row count, update that number and say so in the commit body (do not delete the assertion).

- [ ] **Step 5: Commit**

```bash
git add app/ml/dataset.py tests/test_ml_dataset.py
git commit -m "feat: 時序切分改以比賽為界（避免同一場的列跨 train/eval 洩漏）"
```

---

## Deferred to Phase 2 (separate plan — do NOT start here)

1. **Per-target dataset filtering** (Oracle "Step 0"): filter rows by target *before* splitting so the handicap model can finally train (`train_handicap` currently fails because handicap labels only exist in the newest eval slice). Separate plan.
2. **Features**: keep `hdc_line = midpoint` and `market_hdc_*` for quarter lines (Task 1 already stores the midpoint; Phase 2 decides how the two halves feed the model).
3. **Serving**: evaluate the champion at both half-lines and combine with the split-stake EV —
   `EV/S(H) = p_low*(O-1) + (p_high-p_low)*(O-1)/2 - (1-p_high)`, `p_eff = (1 + EV/S)/O`,
   `edge = p_eff - fair_prob`, `recommended_fraction = kelly_fraction(p_eff, O)`. **Never evaluate at the midpoint.**
4. **Placement**: remove the `is_whole_or_half` guard only after the handicap model trains and settlement is proven in production.
5. **API/summary**: nothing required (new statuses pass through), but Phase 2 should add `half_won`/`half_lost` to any status filter documentation.

## Self-Review

- **Spec coverage:** parsing (Task 1), settlement (Task 2), the leakage guard that Phase 2 depends on (Task 3) — the three items Oracle's ordered first release names ("parsing + settlement only, placement guard kept"). Formulas, statuses and the no-migration claim are copied verbatim from the Oracle review. Deferred items are listed explicitly rather than left implicit.
- **Placeholder scan:** no TBD/TODO; every code step shows the code; every run step shows the command and expected result.
- **Type consistency:** `quarter_halves(line: float) -> tuple[float, float] | None` is used identically in Task 1 (tests), Task 2 (`_settle_handicap`) and the Phase 2 note; `parse_handicap_line` keeps its `str | None -> float | None` signature; `_settle_handicap` returns `tuple[str, float]` and is the only new ledger entry point; `temporal_split`'s signature and return types are unchanged.
