# Shadow ledger and Performance book switch

> Date: 2026-10-26
> Status: implemented locally (tests green); not committed or deployed
> Scope: sub-system C (paper ledger) and D (Performance UI); no production-ledger
> behaviour change, no model/CLV threshold change.
> Related: `2026-10-12-paper-ledger-design.md`,
> `2026-10-14-ledger-execution-price-design.md`,
> `2026-10-16-model-value-repair-design.md`.

---

## 1. Context

The production ledger uses the strict value rule:

- champion 1X2 prediction
- `edge > ML_VALUE_EDGE_THRESHOLD` (default 2%)
- `prob * market_odds > 1 + ML_EXEC_EDGE_BUFFER` (default 3%)
- `recommended_fraction > 0`

As of 2026-10-21 the deployed configuration has placed **0 production bets** while
CLV has `n = 264` observations. The stop/go gate therefore can never satisfy its
`n_settled_bets >= 500` criterion: waiting does not change a zero-bet ledger.

The model also has no demonstrated probability edge: at `n = 264` the CLV beat rate is
55.3% but the Wilson lower bound is 49.3%, the mean edge is ~0, and the 88-match
calibration sample has worse Brier/logloss than the de-vigged market. The shadow ledger
is therefore a **validation instrument**, not evidence that the model is profitable.

## 2. Goal

Add a separate paper-only ledger that:

1. Accumulates forward, one 1X2 bet per match, using a relaxed but explicit value rule.
2. Leaves the production ledger untouched.
3. Is visible in the Performance page via a URL-backed `Production / Shadow` switch.
4. Lets the stop/go gate evaluate the shadow book's ROI and settled-bet count while
   keeping CLV and calibration model-level.
5. Can be reset independently.

## 3. Non-goals

- No change to production selection, staking, settlement, or `ledger_bets`.
- No change to CLV definitions, gate thresholds, model features, or champion selection.
- No historical backfill: shadow bets start at deployment.
- No handicap shadow bets in this increment; 1X2 only.
- No shadow-specific `ClvRecord` rows. The CLV “value bets” line remains the
  production `is_value` filter (strict rule); shadow validation uses the shadow
  ledger’s ROI and settled-bet count.
- No claim that the shadow ledger will make the gate pass. The Wilson-lower and
  calibration criteria can still fail.

## 4. Approaches considered

| Approach | Description | Verdict |
| --- | --- | --- |
| **A. Separate table + shared generic helpers** | New `shadow_ledger_bets`; settlement/summary/equity helpers accept a bet model | **Chosen** |
| B. `book` column on `ledger_bets` | One table for both books, every query filters by book | Rejected: a missed filter leaks shadow rows into production |
| C. Separate table + duplicated ledger code | Copy settlement/summary/equity | Rejected: two implementations drift |

Approach A gives real isolation while keeping the settlement and aggregation logic in
one place. Production callers keep the existing defaults.

## 5. Data model

New table `shadow_ledger_bets` (`ShadowLedgerBet`), same columns as `ledger_bets`:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `match_id` | FK `matches.id`, indexed | **unique**: one shadow bet per match |
| `target` | string(20) | `1x2` in this increment |
| `outcome` | string(10) | `H` / `D` / `A` |
| `model_version_id` | FK `model_versions.id` | champion at placement |
| `line` | float nullable | null for 1X2 |
| `odds` | float | execution price |
| `stake` | float | whole HKD |
| `bankroll_at_place` | float | shadow bankroll at batch start |
| `edge` | float nullable | `prob - execution implied_prob` |
| `kelly_multiplier` | float | same setting as production |
| `result_source` | string(20) nullable | set on settlement |
| `status` | string(20) | `pending` / `won` / `lost` |
| `placed_at` | timestamptz | server default now |
| `settled_at` | timestamptz nullable | |
| `payout` | float nullable | |
| `profit` | float nullable | |

Migration: `0006_shadow_ledger_bets.py`, down-revision `0005_match_stats`.

Unique constraint name: `uq_shadow_ledger_bets_match` on `match_id`.

## 6. Shadow selection rule

Candidates are queried once per batch:

- `ModelVersion.status = 'champion'`
- `Match.kickoff_time > now(UTC)`
- `Prediction.target = '1x2'`
- `Prediction.edge IS NOT NULL AND Prediction.edge > 0`
- no existing `shadow_ledger_bets` row for the match

For each match, candidates are ordered by `Prediction.edge DESC`, then `outcome ASC` for
determinism. The first candidate that passes execution checks is placed; at most one bet
per match.

Execution checks, using the latest pre-kickoff HKJC HAD snapshot
(`load_hkjc_priors(..., lead_hours=0)`):

1. Require `had_odds[outcome]` and `had_probs[outcome]`.
2. `fraction = kelly_fraction(prediction.prob, execution_odds)`.
3. Require `fraction > 0`; otherwise try the next candidate in the same match.
4. `execution_edge = prediction.prob - implied_prob`; require `execution_edge > 0`.
5. `stake = _size_stake(shadow_bankroll_batch_start, fraction, settings)`.
6. Require `stake >= settings.ledger_min_stake`; otherwise try the next candidate.
7. Insert one `ShadowLedgerBet` and stop processing that match.

Notes:

- `prediction.prob` is the blended probability; `prediction.edge` is the
  prediction-time signal edge. The stored shadow `edge` is recomputed at execution.
- `prediction.recommended_fraction` is deliberately ignored; it encodes the strict
  production rule and is normally zero for shadow candidates.
- Sizing uses the same `LEDGER_KELLY_MULTIPLIER`, `LEDGER_MAX_STAKE_FRACTION`,
  `LEDGER_MIN_STAKE`, and `LEDGER_INITIAL_BANKROLL` as production.
- The shadow bankroll is derived only from `shadow_ledger_bets`.

## 7. Services and scheduling

`app/services/ledger.py`:

- Introduce a small bet-model type alias covering `LedgerBet | ShadowLedgerBet`.
- `settle_bets(session, bet_model=LedgerBet)` — production default unchanged.
- `_bankroll_now(session, settings, bet_model=LedgerBet)`.
- `summary(session, settings, bet_model=LedgerBet)`.
- `equity_curve(session, settings, bet_model=LedgerBet)`.
- `place_shadow_bets(session, settings)` — new, rule in §6.
- `shadow_ledger_update(session_factory, settings)` — settle shadow bets, then place;
  tracked with job id `shadow_ledger_update`.

`app/scheduler.py`:

- If `settings.ledger_enable` and `settings.shadow_ledger_enable`, register
  `shadow_ledger_update` on `settings.ledger_update_interval`, `max_instances=1`,
  `coalesce=True`.
- Production `ledger_update` remains unchanged.

Config:

- `SHADOW_LEDGER_ENABLE` (default `true`; documented in `.env.example` and deploy env).
- No new threshold settings; the rule is edge > 0 and no buffer by design.

Ops:

- Add `shadow_ledger_update` to `JOB_RUN_KEYS`.
- Add `shadow_ledger_bets` to the `/ops/data` table counts.

## 8. API contract

All ledger reads accept `book`:

```
GET /bets?book=production|shadow
GET /bets/summary?book=production|shadow
GET /bets/equity-curve?book=production|shadow
GET /clv/summary?book=production|shadow
```

- Default is `production`.
- Invalid values return 422 (query pattern `^(production|shadow)$`).
- `BetOut` rows keep the same shape; the selected book is path context.
- `/clv/summary` uses the selected book only for `roi_real`, `roi_real_ci95`,
  `n_settled_bets`, and `settled_stakes`. CLV metrics and calibration stay model-level.
- Add `book` to the `/clv/summary` response and `ClvSummaryOut` so the UI can label the
  gate source.

## 9. Web UI

Performance page:

- `?book=shadow` selects the shadow book; absent or `production` selects production.
- Add a `LedgerBookToggle` server component with two links:
  - `Production` → `/performance`
  - `Shadow · paper` → `/performance?book=shadow`
- Active item uses `aria-current="page"` and the existing segmented-control styling.
- Shadow view shows a persistent banner:
  “Shadow ledger — paper only. Production bankroll is unchanged.”
- Header bankroll remains production on both views.

Data plumbing:

- `loadPerformanceData(book)` passes `book` to:
  - `getBetSummary(book)`
  - `getEquityCurve(book)`
  - `getBets(limit, offset, book)`
  - `loadBetsWindow(nBets, book)`
  - `getClvSummary("hkjc", book)`
- `PerformanceData` carries `book`.

Panels switched by `book`:

- KPI strip (summary + bets)
- Equity / money curve
- Signal vs execution price
- All bets
- Matches × predictions (bets join)
- CLV card's ROI, settled-bets and gate section

Panels not switched:

- Pipeline, results, predictions themselves, header.

Shadow-specific copy:

- `BetsTable` empty state: “Shadow ledger has not placed a bet.”
- `BetsTable` caption: “All shadow ledger bets (paper only).”
- `ClvCard` note: “ROI and settled bets come from the selected ledger book; CLV and
  calibration are model-level.”

## 10. Reset and CLI

- `python -m app.cli shadow-ledger` — run one shadow settle + place cycle.
- `python -m app.cli reset-shadow --yes` — delete only `shadow_ledger_bets`;
  dry-run by default, prints the row count.
- `reset-paper` includes `shadow_ledger_bets` because it also deletes predictions and
  models, which would invalidate shadow bets.
- No backup is required for `reset-shadow` (paper-only, separate table).

## 11. Tests

Backend:

1. One bet per match; highest positive signal edge wins.
2. Candidate with `edge <= 0` is not bet.
3. Highest candidate whose execution Kelly is <= 0 is skipped; the next candidate in
   the same match may be bet.
4. No execution price or missing outcome → no bet.
5. Stake uses shadow bankroll and the same Kelly/cap/min rules.
6. Settlement uses confirmed results and never touches `ledger_bets`.
7. `summary` / `equity_curve` filter to the requested model; production unaffected.
8. `/bets*` and `/clv/summary` default to production; `book=shadow` returns shadow;
   invalid book returns 422.
9. `clv.summary(book="shadow")` takes ROI/settled from shadow, not production.
10. Scheduler registers `shadow_ledger_update` only when both ledger flags are on.
11. `reset-shadow` deletes shadow rows only; `reset-paper` clears both.

Frontend:

1. Toggle links, active state and `aria-current`.
2. Shadow banner renders only for `book=shadow`.
3. Shadow empty-state copy.
4. `loadPerformanceData` passes `book` to each fetcher.
5. CLV card labels the selected gate book.

Verification:

```bash
uv run pytest -q
uv run ruff check .
cd web && npm test && npm run typecheck && npm run lint
```

## 12. Acceptance

On the host after deploy:

1. `alembic upgrade head` shows `0006_shadow_ledger_bets`.
2. `python -m app.cli shadow-ledger` places at least one shadow bet when an upcoming
   champion prediction has positive signal edge and a valid execution price.
3. `GET /bets?book=shadow` returns shadow rows; `GET /bets` still returns production
   rows (currently zero).
4. `GET /bets/summary?book=shadow` bankroll starts at `LEDGER_INITIAL_BANKROLL`.
5. `GET /clv/summary?book=shadow` reports shadow `n_settled_bets`/ROI and `book=shadow`.
6. `/performance?book=shadow` shows the banner, the shadow KPI/bets/equity, and a gate
   whose ROI/settled values come from shadow; `/performance` remains production.
7. A settlement cycle increases shadow `n_settled_bets` without creating or modifying
   any `ledger_bets` row.

## 13. Risks and open monitoring

- **Model edge is still unproven.** The shadow book can reach 500 bets and still fail
  Wilson-lower or calibration. That is a valid fail, not a reason to loosen the gate.
- **Volume estimate.** At roughly 11 matches/day and one bet per match, 500 settled bets
  is about 45–60 days if most matches carry a positive signal edge. If the positive-edge
  rate is lower, the 90-day window may expire before 500 settle.
- **Correlation avoided.** One bet per match avoids the unrealistic double exposure of
  betting multiple outcomes in the same match, at the cost of slower accumulation.
- **No backfill.** The first shadow bet is post-deploy; historical data is not used to
  inflate the sample.
- **Production isolation.** All production call sites keep `LedgerBet` as the default;
  tests must assert that a shadow settlement leaves `ledger_bets` untouched.
