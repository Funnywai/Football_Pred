# Football Betting Agent — Sub-system C (Paper Ledger) Design

> Date: 2026-10-12
> Project: football-betting AI agent — rebuild of the WorldCup Discord bot into **FastAPI + Postgres + Next.js**
> Scope: **Sub-system C (paper ledger) only.** Data layer (A) and ML engine (B) are complete and merged (PR #1, merge commit `04b8136`). Web UI (D), orchestration (E), self-improvement upgrades (F) are separate specs.
> Depends on: Sub-system A (`docs/superpowers/specs/2026-10-12-football-agent-data-layer-design.md`) and Sub-system B (`docs/superpowers/specs/2026-10-12-football-agent-ml-engine-design.md`).

---

## 1. Context

Sub-system B already produces, per upcoming match × target × outcome, a versioned prediction row: calibrated model probability, de-vigged implied probability, edge, fair odds, the market odds used at prediction time, and a Kelly `recommended_fraction` (a fixed 0.0 whenever the bet is not a value bet).

What is missing is the **bankroll loop**: turn those outputs into a simulated staking history and judge the strategy by realized performance. Sub-system C is that loop — a paper trading ledger. No real money, no user-facing writes, no UI; the ledger is fully automated and judged from data alone. B's design explicitly draws this boundary: *"B only emits the recommended fraction; applying it to a bankroll is sub-system C."*

## 2. Scope

**In:**
- One automated staking strategy: champion-model value bets, i.e. the exact champion predictions with `recommended_fraction > 0`.
- Stake sizing by **fractional Kelly** with min/max caps (see §6).
- **Automatic settlement** of placed bets once the authoritative result is confirmed, including handicap pushes.
- Bankroll, performance summary and equity curve — **derived from the bets table** (single source of truth), exposed via read-only API.
- One scheduled `ledger_update` job wired into the existing APScheduler, observable via `track_run` (`ingestion_runs`).

**Out (by locked decision or later sub-system):**
- Manual bet placement / adjustment APIs (Q1: fully automated).
- Market-baseline / comparison strategies (Q3: champion strategy only; beating-the-market is measured by B's CLV metrics, deferred refinement #5).
- Re-staking when odds move after placement (Q4: bets immutable once placed).
- Stale-bet auto-voiding or cancelled-match state handling.
- UI (sub-system D), orchestration beyond the shared scheduler (E), self-improvement (F), real-money execution.

## 3. Locked decisions (from brainstorming)

| # | Decision |
|---|---|
| 1 | **Fully automated**: scheduled placement + settlement; API stays read-only, consistent with A/B. |
| 2 | **Fractional Kelly**: stake = bankroll × `recommended_fraction` × `ledger_kelly_multiplier` (default 0.5), **capped at** `ledger_max_stake_fraction × batch bankroll`; the minimum is one HKJC bet unit, **HKD 10** (all ledger money is HKD) — a stake below HKD 10 is **skipped entirely, never raised to the minimum**; likewise skipped when the cap itself is below HKD 10. So every placed bet is ≥ HKD 10 and ≤ 5% of the batch bankroll. |
| 3 | **Champion-model strategy only** — one ledger, no built-in market baseline. |
| 4 | **Odds locked at prediction time** (`Prediction.market_odds` of the served row — the same odds the edge/Kelly math used; fully reproducible). |
| 5 | **Delivery = tables + service + scheduler + read-only API** (`/bets`, `/bets/summary`, `/bets/equity-curve`). UI is sub-system D. |
| 6 | **Independent `ledger_update` scheduled job** (settle → place), wrapped in `track_run`, fail-soft like the other jobs; never coupled into B's code path. |

## 4. Architecture

New service `app/services/ledger.py`, following the A-layer conventions (async SQLAlchemy 2.x, `UtcDateTime`, Chinese `type: 描述` commits, job entry takes `session_factory`, inner functions take an `AsyncSession`):

| Function | Responsibility |
|---|---|
| `settle_bets(session) -> int` | Settle pending bets whose match has a confirmed `Result`. |
| `place_bets(session, settings) -> int` | Insert bets for unbet value predictions. |
| `ledger_update(session_factory, settings) -> int` | Job entry; `track_run`-wrapped, runs settle then place, returns processed count. |
| `bet_rows(session, query) -> list[BetView]` | Listing helper for `GET /bets` (joins match/teams like `/predictions`). |
| `summary(session) -> Summary` | Aggregates for the summary endpoint. |
| `equity_curve(session, settings) -> list[EquityPoint]` | Realized-wealth points from settlement events. |

Scheduler wiring (mirrors how ML jobs were wired): in `app/scheduler.py::build_scheduler`, when `settings.ledger_enable` is true, `add_job(ledger_update, "interval", seconds=settings.ledger_update_interval, args=[session_factory, settings], id="ledger_update", max_instances=1, coalesce=True)` — same scheduler instance, after the existing jobs, before `return`.

**Consequence (deliberate, spec-mandated):** `tests/test_scheduler.py::test_build_scheduler_registers_expected_jobs` asserts the job-id set is *exactly* `{"sync_odds", "settle_results", "prune_odds"}`. With `ledger_enable` default true the set gains `ledger_update` — that test is updated to the 4-job set, and a companion test asserts the job is absent when `ledger_enable=False`.

**Data flow:**

```
predictions(champion, fresh)                    results(confirmed) ──┐
        │ filter recommended_fraction > 0, anti-join bets            │
        ▼                                                            ▼
 place_bets ──► ledger_bets(status=pending) ──► settle_bets ──► won/lost/push
        └──── bankroll / summary / equity-curve 演算只讀 ledger_bets ────┘
```

## 5. Data model — Alembic migration `0003_ledger_bets`

Single table `ledger_bets` (no bankroll/snapshot tables — bankroll is always recomputed from bets so it can never drift):

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `match_id` | FK `matches.id`, NOT NULL, index | |
| `target` | String(20) NOT NULL | `"1x2"` \| `"handicap"` |
| `outcome` | String(10) NOT NULL | `H`/`D`/`A` (handicap rows are `H`/`A` only — B never emits handicap `D`) |
| `model_version_id` | FK `model_versions.id`, NOT NULL | Version active at placement (audit) |
| `line` | Float NULL | Locked handicap line for settlement; NULL for `1x2` |
| `odds` | Float NOT NULL | Locked market odds from the prediction row (`> 1` by construction — B only sizes stakes for odds `> 1`) |
| `stake` | Float NOT NULL | Placed stake (`> 0`) |
| `bankroll_at_place` | Float NOT NULL | Batch-start bankroll (§6) — reproduces the sizing |
| `edge` | Float NULL | Edge at placement (audit) |
| `kelly_multiplier` | Float NOT NULL | Setting value at placement (audit) |
| `result_source` | String(20) NULL | `Result.source` at settlement (`hkjc` / `football_data`) |
| `status` | String(20) NOT NULL, default `"pending"` | `pending` / `won` / `lost` / `push` |
| `placed_at` | UtcDateTime NOT NULL, server_default now() | |
| `settled_at` | UtcDateTime NULL | |
| `payout` | Float NULL | Won: `stake × odds`; push: `stake`; lost: `0.0`; NULL while pending |
| `profit` | Float NULL | `payout − stake` (push `= 0`, lost `= −stake`); NULL while pending |

UNIQUE `(match_id, target, outcome)` = `uq_ledger_bets_natural` — **one bet per match × target × direction**, forever. Champion replacement produces *new prediction rows* (different `model_version_id` in B's upsert) but never a new bet.

**Derivations (read-time, no storage):**

```
open_stakes      = Σ stake(status = 'pending')
realized_profit  = Σ profit(status ≠ 'pending')
bankroll_now     = ledger_initial_bankroll + realized_profit − open_stakes
roi              = realized_profit / Σ stake(status ≠ 'pending')          (0 when no settled bets)
yield            = realized_profit / Σ stake(all bets)
```

## 6. Placement rules

**Selection** — a served prediction qualifies when:
1. its prediction row belongs to the **current champion** — `Prediction.model_version_id` joined to `ModelVersion` where `status = 'champion'` (the same join pattern as `GET /predictions`; retired versions' stale rows never bet), and
2. `recommended_fraction > 0.0` (B already computed this: only value bets with odds `> 1` get a Kelly fraction), and
3. no bet exists with the same `(match_id, target, outcome)` in any status.

**Sizing** — one `ledger_update` run places bets as one batch:
1. `bankroll_batch_start = bankroll_now` computed **once at run start** — every bet in the batch uses the same value (deterministic, independent of betting order).
2. `stake = round(bankroll_batch_start × recommended_fraction × ledger_kelly_multiplier, 2)`
3. **Cap only** (downward): `stake = min(stake, ledger_max_stake_fraction × bankroll_batch_start)`.
4. **Skip below minimum**: if the capped stake `< ledger_min_stake` (HKD 10) → **skip the bet** (one info-level log line) — a stake is never raised up to the minimum; likewise skip when the cap itself `< ledger_min_stake` (bankroll below `ledger_min_stake / ledger_max_stake_fraction` = 200 HKD by default).
5. All monetary amounts are **HKD** (paper currency — no FX, no unit conversion) and apply to every market the ledger bets on (HAD today, and the same minimum/units for any later market).

Each inserted bet records: `odds = prediction.market_odds`, `edge = prediction.edge`, `kelly_multiplier`, `bankroll_at_place = bankroll_batch_start`, and `line = the champion's hdc_line recomputed at placement time via `load_market_priors` (a handicap bet is skipped when that recomputed line is unavailable — e.g. the HKJC snapshot is gone). `placed_at = now`.

**Defaults (Settings, env `LEDGER_*`):**

```
ledger_enable: bool = True
ledger_update_interval: int = 3600
ledger_initial_bankroll: float = 1000.0
ledger_kelly_multiplier: float = 0.5
ledger_max_stake_fraction: float = 0.05
ledger_min_stake: float = 10.0              # HKD — one HKJC bet unit; below this the bet is skipped, not clamped up
```

## 7. Settlement rules

Only `Result` rows with `confirmed = True` settle a bet — sub-system A's authority model (HKJC results can never be overwritten by the external fallback) is reused untouched.

- **1x2**: `label_1x2(home_score, away_score) == outcome` → `won` (`payout = stake × odds`); otherwise `lost` (`payout = 0.0`). No push exists.
- **handicap**: reuse `app.ml.labels.handicap_label(home_score, away_score, line)` from B:
  - returns the bet's `outcome` → `won` (`payout = stake × odds`);
  - returns `None` → **`push`** (`payout = stake`, profit 0) — a whole-line push refunds the stake. (Quarter lines can never be bets: B already refuses to serve them; so `None` here can only be a whole-line push.)
  - otherwise → `lost`.
- Each settlement writes `status`, `payout`, `profit = payout − stake`, `settled_at = now`, `result_source = Result.source`.
- **Idempotent**: settled rows are never re-settled; a result that arrives later is picked up by the next run; nothing is silently dropped (pending bets stay visible in the summary).

## 8. API (read-only, follows the `/predictions` style: joins match/league/teams, `limit`/`offset`)

| Endpoint | Query params | Response |
|---|---|---|
| `GET /bets` | `status`, `match_id`, `target`, `limit` (≤500), `offset` | `list[BetOut]` — all locked/settled fields + `kickoff_time`, `league_code`, `home_team`, `away_team` |
| `GET /bets/summary` | — | `BetSummary` — `initial_bankroll`, `bankroll`, `n_bets`, `n_settled`, `n_open`, `stakes_total`, `open_stakes`, `realized_profit`, `roi`, `yield_pct` |
| `GET /bets/equity-curve` | — | `list[EquityPoint]` — `[{t, bankroll}]`: initial point, one point per settlement event (realized bankroll with open stakes deducted), and a final point = `bankroll_now` |

## 9. Error handling & observability

- `ledger_update` is wrapped in `track_run` — failures are recorded in `ingestion_runs` (`status="failed"`) and re-raised so scheduler logs them; other jobs are unaffected (fail-soft isolation).
- Single-writer discipline: `max_instances=1`, hourly cadence; placement is anti-join + insert, and the `uq_ledger_bets_natural` constraint is the belt-and-braces backstop (an `IntegrityError` would indicate a bug, not a race).
- Every run is idempotent; a no-op run returns counts of 0 and still records a successful `ingestion_runs` row.

## 10. Success metrics

1. **Reproducibility** — every placed bet can re-derive its stake from stored fields: `stake = f(bankroll_at_place, recommended_fraction, kelly_multiplier)` with the locked `odds`/`edge`.
2. **Settlement completeness** — 100% of placed bets eventually settle automatically (push included); pending bets are always visible with their stake in the summary.
3. **Accounting correctness** — every summary value is re-derivable by hand from the bets table (definitions §5).
4. Automation — placing + settling require zero manual action; the whole loop is exercised green in tests.

## 11. Testing plan

- **Unit** (`tests/test_ledger.py`): stake math (fraction × multiplier, clamp, round, skip-below-min), settlement three states × two targets (incl. whole-line push), idempotent placement (duplicate prediction rows do not re-bet; re-run no-ops), settlement idempotency, bankroll/roi/yield formulas, equity-curve points (incl. open-stakes deduction and the current-value final point).
- **Integration** (seeded DB via `tests/ml_helpers.py`): champion predictions seeded directly → `place_bets` → seed confirmed result → `settle_bets` → summary/manual check.
- **End-to-end**: extend the existing pattern — seed → `build_dataset` → train → promote → predict → `ledger_update` → assert bets placed, settled correctly, summary/equity-curve consistent.
- **Scheduler**: job-id set = 4 jobs with default settings; `ledger_enable=False` yields the original 3-job set.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Odds move between prediction lock and kickoff | Accepted and documented: the locked odds are the strategy's stated assumption; measuring against a moving book is a later concern (needs execution-time snapshots). |
| Bankroll depletion by a bad streak | `ledger_max_stake_fraction` caps exposure per bet; minimum-stake skip prevents micro-bets when bankroll shrinks. |
| Champion replacement re-triggering bets | Bet identity excludes `model_version_id` — one bet per (match, target, outcome), ever. |
| Stale pending bets (no confirmed result) | No auto-void in v1; summary makes pending exposure explicit. Revisit if fixtures can legitimately disappear. |
| Future re-stake or market-baseline ledgers | Out of scope — separate specs by design; the single `uq_ledger_bets_natural` key would need revisiting them. |