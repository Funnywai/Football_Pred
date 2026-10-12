# Football Betting AI Agent — Sub-system B: Prediction Engine (v1) — Design Spec

> Status: **Draft v1 — pending user approval of the written spec**
> Date: 2026-10-12
> Project: football-betting AI agent (rebuild of the WorldCup Discord bot into FastAPI + Postgres + Next.js)
> Scope: **Sub-system B (ML prediction engine, v1) only.** Data layer (A) is complete on branch `rebuild`. Paper ledger (C), Web UI (D), orchestration (E), self-improvement loop upgrades (F) are separate specs.
> Depends on: Sub-system A (`docs/superpowers/specs/2026-10-12-football-agent-data-layer-design.md`)

---

## 1. Context

Sub-system A delivers, in PostgreSQL: `leagues`, `seasons`, `teams`, `matches`, `odds_snapshots`
(raw HKJC/football-data payloads, odds types HAD/HDC/HIL/CRS/HHA/CHD/CHL), `results` (HKJC-first,
`confirmed`/`payout_confirmed`, `home_score`/`away_score`), `ingestion_runs`, a read API
(`/matches`, `/matches/{id}/odds`, `/results`, `/health`), and an in-process APScheduler.

Sub-system B consumes that data to **predict matches, detect value vs HKJC odds, and improve itself**.
v1 deliberately uses the *proven* approach for tabular sports data (gradient-boosted trees + calibration)
rather than the more ambitious NN/RL methods, so it is calibratable, testable and honest.

## 2. Goals / Non-goals

**Goals (v1)**
- Predict **1X2** (HAD) probabilities and **Asian-handicap** (HDC main line) cover probabilities for
  EPL + Big-5 + UCL matches.
- Detect **value** vs HKJC odds (de-vigged) and emit per-outcome predictions + recommended stake fractions.
- **Self-improve**: scheduled retrain with a **champion/challenger** gate, versioned + rollback-able.
- Be **measurably good**: calibration (Brier/log-loss vs the market) and **beat the closing line** (CLV).

**Non-goals (YAGNI, v1)**
- No neural nets, no unsupervised learning, no RL (deferred to v2 / sub-system F).
- No other markets (over/under HIL, correct score CRS, corner markets).
- No real-money staking execution, no bankroll/ledger (sub-system C), no UI (D), no orchestration beyond A's scheduler.
- No live in-play modeling.

## 3. Locked decisions (from brainstorming)

| # | Decision |
|---|---|
| 1 | v1 core: **supervised model + value detection + periodic retrain** |
| 2 | Markets: **1X2 (HAD) + 讓球 (HDC main line)** |
| 3 | Success: **calibration (Brier/log-loss) + beat the closing line** |
| 4 | Self-improving: **retrain + champion/challenger gate** (promote only if better; rollback-able) |
| 5 | Location: **same repo, `app/ml/`**; reuse A's `Database` + APScheduler |
| 6 | Modeling: **gradient boosting + probability calibration** |

## 4. Architecture & components (`app/ml/`)

| Module | Responsibility |
|---|---|
| `app/ml/features.py` | Build a feature row for a match from A's tables, **strictly as-of kickoff** (no leakage). |
| `app/ml/dataset.py` | Assemble train/calibration/eval datasets from historical matches (temporal split). |
| `app/ml/labels.py` | Derive 1X2 and handicap-cover labels from `results`. |
| `app/ml/models.py` | Train GBT models (1X2 multiclass, handicap binary) + calibration; return artifact + metrics. |
| `app/ml/deviq.py` | De-vig odds → fair implied probabilities (multiplicative; Shin/log cited as future). |
| `app/ml/value.py` | `edge`, `fair_odds`, value flag, recommended Kelly fraction. |
| `app/ml/registry.py` | `model_versions` table access + champion/challenger evaluation gate + promote/rollback. |
| `app/ml/predict.py` | Serve predictions with the current champion; upsert `predictions`. |
| `app/ml/jobs.py` | Job functions for A's scheduler: `predict_upcoming`, `retrain`. |
| `app/api/routes.py` (extend) | Add `GET /predictions`, `GET /models`. |
| `alembic/versions/0002_*` | Migration for `model_versions`, `predictions`, `match_features`. |

Training runs in a **worker** (thread/process executor) so it never blocks the FastAPI/APScheduler event loop.

## 5. Data & features (`features.py`)

Every feature is computed using only information available **before `match.kickoff_time`** (uses only
`results` whose `kickoff_time < this match` and `confirmed = true`, and odds snapshots with
`captured_at < kickoff_time`). A `feature_version` string tags the feature set.

| Group | Features |
|---|---|
| Team strength | rolling Elo (per-team, updated match-by-match); rolling attack/defense strength (opponent-adjusted goals for/against over last N) |
| Form | points & goal-difference over last 5; home/away splits; days of rest |
| Context | home-advantage indicator, league code, season progress (matchday index) |
| H2H | last-N head-to-head net goal difference |
| Market prior | de-vigged HKJC HAD implied probabilities; for handicap: the main line + de-vigged cover implied |

The built feature row is persisted in `match_features` for reproducibility/audit.

## 6. Labels (`labels.py`)

- **1X2**: from `results.home_score`/`away_score` → `H` (>) / `D` (=) / `A` (<).
- **Handicap**: the HKJC `HDC` **main line** (`main = true`; line from the snapshot `condition`).
  `net = home_score − away_score`; home covers if `net + line > 0` (the `line` is the home handicap). **v1 models the main line only, and only when
  it is a whole or half line**; if a match's main line is a quarter line (`.25`/`.75`), that match's handicap
  target is **skipped** in v1 (no half-bet splitting) — a deliberate simplification.

## 7. Models & calibration (`models.py`)

- **1X2**: LightGBM `objective=multiclass, num_class=3`.
- **Handicap**: LightGBM `objective=binary` (target = home covers the main line).
- Hyperparameters (starting point): `learning_rate≈0.03–0.05`, `num_leaves≈31`, `min_child_samples≈30`,
  `subsample≈0.8`, `colsample_bytree≈0.8`, early stopping on a temporal validation fold.
- **Calibration**: isotonic regression (multiclass: per-class isotonic + renormalize) or Platt/sigmoid,
  fit on a held-out calibration fold — never on training or eval data.
- **Validation**: temporal / walk-forward (train on older seasons, evaluate on newer) — no random splits.

## 8. Value detection (`deviq.py`, `value.py`)

- De-vig (v1, multiplicative): `implied_i = 1/odds_i`; `overround = Σ implied_i`; `fair_i = implied_i / overround`.
- `edge_i = model_prob_i − fair_i`; a **value bet** is flagged when `edge_i > threshold` (default `0.02`, configurable).
- `fair_odds_i = 1 / model_prob_i`.
- **Kelly fraction**: `f = (b·p − q) / b` with `b = odds_i − 1`, `p = model_prob_i`, `q = 1 − p`.
  B **only emits the recommended fraction**; applying it to a bankroll is sub-system C.

## 9. Success metrics

- **Calibration**: multiclass Brier score + log-loss, **compared against the market's** Brier/log-loss
  (using de-vigged implied probabilities as the market's probabilities). A model is "well-calibrated" if it
  approaches/beats the market.
- **Beat the closing line (CLV)**: for flagged value bets, does the model's fair probability ≥ the HKJC
  **closing** de-vigged fair probability (i.e. we secured a better price than closing)? Report the fraction
  and mean edge. Computed only on the subset with HKJC pre-kickoff snapshots (see §11).

## 10. Self-improving — retrain + champion/challenger (`registry.py`)

- Scheduled **retrain** builds a *challenger* (new artifact + metrics).
- **Gate**: promote to *champion* only if, on a recent holdout, `Brier_challenger ≤ Brier_champion`
  (with a configurable margin) **and** the CLV metric is not worse. Otherwise keep the champion.
- All versions recorded in `model_versions` (`champion`/`challenger`/`retired`); promotion/rollback is a
  status change — deterministic and reversible. Prediction always uses the current `champion`.

## 11. Training data — important nuance ⚠️

- **Historical corpus**: from A's football-data.co.uk backfill (2010+ results + per-bookmaker opening/closing
  odds, incl. Pinnacle closing as a sharp prior).
- **HKJC odds history** only accumulates once A runs live (backfill has no HKJC historical odds). Therefore:
  - feature **market prior** uses HKJC de-vigged odds **where available**, else football-data (Pinnacle closing);
  - the **"beat HKJC closing"** metric is computed **only on matches with HKJC pre-kickoff snapshots**.

## 12. Data model additions (`0002` migration)

| Table | Columns | Notes |
|---|---|---|
| `model_versions` | `id`, `target`, `algorithm`, `params jsonb`, `metrics jsonb` (`brier`,`logloss`,`clv`,`n`), `artifact_path`, `status` (`champion`/`challenger`/`retired`), `created_at`, `promoted_at` | one champion per `target` |
| `predictions` | `id`, `match_id`, `target`, `outcome`, `model_version_id`, `prob`, `implied_prob`, `edge`, `fair_odds`, `market_odds`, `recommended_fraction`, `created_at` | UNIQUE(`match_id`,`target`,`outcome`,`model_version_id`) |
| `match_features` | `id`, `match_id`, `feature_version`, `built_at`, `features jsonb` | UNIQUE(`match_id`,`feature_version`); reproducibility |

## 13. API additions

- `GET /predictions` — filters: `match_id`, `target`, `value_only` (bool), `limit`/`offset`. Returns prediction rows joined with match info.
- `GET /models` — list `model_versions` (status, metrics).

## 14. Scheduling (`jobs.py`, wired into A's scheduler)

- `predict_upcoming` (default hourly): for matches kicking off soon with no champion prediction → build features
  → predict → upsert `predictions` (idempotent on the UNIQUE key).
- `retrain` (default weekly): build dataset → train challenger → evaluate gate → promote/record. Runs in a worker.

## 15. Configuration (env, extends A's `Settings`)

`ML_ENABLE` (bool), `ML_1X2_MODEL` / `ML_HANDICAP_MODEL` (algorithm id, default `lightgbm`),
`ML_VALUE_EDGE_THRESHOLD` (default 0.02), `ML_RETRAIN_INTERVAL` (seconds), `ML_PREDICT_LOOKAHEAD_HOURS` (default 48),
`ML_MIN_TRAIN_ROWS`, `ML_ARTIFACT_DIR`, `ML_CHAMPION_MARGIN`, `ML_HISTORY_FROM_YEAR`.

## 16. Testing strategy

- **Leakage tests**: a feature row for match M must not use results/odds with `kickoff_time`/`captured_at` ≥ M's kickoff.
- **Label tests**: 1X2 + handicap cover incl. the quarter-line simplification.
- **De-vig tests**: overround removal correctness (sum of fair probs == 1).
- **Calibration tests**: on synthetic data with a known generator, calibrated output beats an uncalibrated one on Brier/log-loss.
- **Registry gate tests**: challenger promoted only when better; rollback restores champion; predictions use champion.
- **End-to-end**: tiny synthetic train → predict → `predictions` rows written (no network).
- Reuse A's VCR-style approach: no live network in the default test run.

## 17. Risks & open questions

| Risk | Mitigation |
|---|---|
| Data leakage (results/odds from the future) | strict as-of-kickoff builders + dedicated leakage tests |
| Tiny data early on (few HKJC snapshots) | train on football-data backfill; gate prevents shipping weak models |
| Overfit / market prior dominates (model just mimics odds) | include odds prior but measure **incremental** skill vs market; report Brier delta |
| Quarter-line handicap complexity | v1 restricts to whole/half lines |
| Long training blocking the app | run in a worker executor |
| Reproducibility | `match_features` snapshots + versioned artifacts + `model_versions` |

**Open questions (resolve during implementation):** exact Elo K/initial params; attack/defense estimator (simple
rolling vs fitted Dixon-Coles); whether the market prior is HKJC-only or includes Pinnacle always; champion margin default.

## 18. Out of scope (v2+)

NN / unsupervised / RL; over-under + other markets; live in-play; real-money staking (C); UI (D); richer
orchestration (E); full self-improvement loop upgrades (F).
