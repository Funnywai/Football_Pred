# Agent + Performance redesign

> Date: 2026-10-29
> Status: design draft; Phase 1 (deterministic risk + audit) is implemented locally.
> Scope: paper-only agent workflow and a Performance information architecture that can
> carry production, shadow, and agent books without mixing them.

---

## 1. Why this redesign

The current Performance page is already carrying too many concepts:

- production ledger
- shadow ledger
- CLV / calibration
- stop/go gate
- predictions / results / pipeline

Adding A/B/C/D agents as another `book` query would make the page unreadable and make
it too easy to confuse paper decisions with real money. The backend should expose
separate resources; the UI should expose separate top-level workflows.

## 2. Agent responsibilities

| Agent | Role | Model | Authority |
|---|---|---|---|
| **A. Risk / Execution** | edge, odds cap, Kelly, max stake, one bet/match, data freshness, duplicate check | **No LLM** — deterministic code | Can veto; always final on execution |
| **B. Analyst** | injuries, lineups, odds movement, news; structured brief with timestamps and uncertainty | Strong tool-use LLM (GPT-5 / Claude Sonnet / Gemini Pro class) | Advisory only |
| **C. Decision** | choose bet/no-bet among A-approved candidates | Small/medium structured-output LLM (GPT-5-mini / Claude Haiku / Gemini Flash / DeepSeek-chat class), temperature 0 | Paper-only; cannot override A |
| **D. Research** | data/feature experiments, walk-forward evaluation, candidate models | Strongest reasoning + tools, offline | Cannot write production or place bets |

Prediction itself stays statistical: LightGBM / Dixon-Coles / Elo / xG ensemble.
**An LLM is not the probability model.**

## 3. Hard rules

1. C cannot create a bet that A did not approve.
2. C cannot change odds, stake, or bankroll rules.
3. A is deterministic and auditable.
4. C is paper-only until A-only vs A+B+C has 500 settled paper bets and C is
   demonstrably better on ROI/CLV.
5. Agents may only see point-in-time inputs. No results, no closing odds, no future
   data, no free web browsing inside C.
6. Every decision stores its input snapshot, prompt/model version, output, and reason.
7. No real money in this phase.

## 4. Backend data model

### Existing, keep

- `predictions`, `model_versions`, `matches`, `results`
- `ledger_bets` (production paper book)
- `shadow_ledger_bets` (shadow book)
- `clv_records`
- `agent_decisions` (Phase 1 audit trail)

### Add

**`agent_runs`**

```text
id, run_id, agent_version, mode, started_at, finished_at,
matches_considered, candidates_evaluated, bets_allowed, no_bets,
summary JSON
```

**`analyst_briefs`**

```text
id, run_id, match_id, source, captured_at,
facts JSON, uncertainties JSON, missing JSON,
trust_score, raw_snapshot JSON
```

**`agent_bets`** (paper only; separate from `ledger_bets` / `shadow_ledger_bets`)

```text
id, run_id, match_id, model_version_id, target, outcome,
variant ("a_only" | "abc"), odds, stake, edge,
status, placed_at, settled_at, payout, profit
```

`variant` is required so the A-only baseline and the A+B+C treatment can be compared
on the same matches and prices.

### Do not

- Do not add another `book` value to `ledger_bets`.
- Do not reuse `shadow_ledger_bets` for agent decisions.
- Do not let `agent_bets` affect the production bankroll.

## 5. API shape

Use resources, not one overloaded endpoint:

```text
GET /agent/runs
GET /agent/runs/{run_id}
GET /agent/decisions?run_id=&match_id=&action=&agent=
GET /agent/briefs?match_id=&run_id=
GET /agent/bets?variant=a_only|abc
GET /agent/summary?variant=a_only|abc
```

The existing `/bets`, `/bets/summary`, `/bets/equity-curve` and `/clv/summary` keep
`book=production|shadow` for compatibility. Agent data is a separate namespace.

## 6. UI information architecture

Top-level navigation:

```text
Overview
Predictions
Agent
Performance
Research
```

### Overview

- system status / data freshness
- production bankroll
- gate verdict
- agent status (A/B/C/D)
- no action buttons that can place real money

### Predictions

- model probability, market probability, edge
- league / kickoff / model version filters
- no ledger mixing

### Agent

- run selector
- decision timeline: match, outcome, A verdict, B brief, C decision, final action
- A rejection reasons
- C rationale and confidence
- filters by agent/action/run
- A/B comparison: A-only vs A+B+C
- audit detail drawer with input snapshot

### Performance

Sub-tabs, not one long page:

```text
Production | Shadow | Agent A/B | CLV & Calibration
```

- each book has an explicit paper/production badge
- each book has its own summary, equity, bets, and empty state
- the header bankroll remains production; sub-tab values are labeled

### Research

- data coverage (Understat, StrikerAPI, API-Football)
- experiment list
- model versions and metrics
- walk-forward reports
- no live betting controls

## 7. Model/provider configuration

Provider-agnostic, OpenAI-compatible:

```text
AGENT_LLM_BASE_URL
AGENT_LLM_API_KEY
AGENT_LLM_MODEL
AGENT_LLM_TEMPERATURE=0
```

Suggested tiers:

- **B analyst**: strong tool-use model; higher cost, low volume.
- **C decision**: small/medium structured-output model; temperature 0; JSON schema.
- **D research**: strongest model; offline only.
- **A risk**: no LLM.

Use PydanticAI for typed outputs and LangGraph for state/checkpoint/audit, or OpenAI
Agents SDK if the provider is OpenAI. Do not use CrewAI role-play for the risk layer.

## 8. Evaluation

- Baseline: A-only deterministic policy
- Treatment: A + B + C
- Same matches, same prices, same bankroll
- Metrics: Brier/logloss (unchanged model), CLV, ROI, max drawdown, decision
  consistency, A-veto rate, C override rate, violation rate
- 500 settled paper bets before any real-money discussion
- If C does not beat A-only, disable C and keep A/B/D

## 9. Phases

1. **Phase 1 (done locally)**: A risk + decision audit + `/agent/decisions` + CLI.
2. **Phase 2**: Performance redesign (backend resources + UI IA), no LLM.
3. **Phase 3**: B analyst with timestamped injuries/lineups/odds movement.
4. **Phase 4**: C decision agent, paper-only, A/B tested.
5. **Phase 5**: D research agent, offline experiments.

## 10. Open decisions

- LLM provider/key and budget for B/C/D.
- Data source for injuries/lineups (API-Football vs StrikerAPI vs Sportmonks).
- Whether `agent_bets` starts as audit-only or immediately creates paper bets.
- Whether C is allowed to rank candidates or only approve/reject A's selected bet.

No production code or real-money behavior changes beyond Phase 1's audited decision
table.

---

## 11. Phase 3a implementation note (2026-10-29)

Phase 3a is implemented locally, still paper-only:

- **A**: deterministic risk engine, HKJC-only execution price.
- **B**: deterministic lineups-only analyst. It reads StrikerAPI `list_games` +
  `get_lineups`; it never reads StrikerAPI odds and never calls API-Football. No LLM
  is used for B in this phase.
- **C**: OpenCode Go `deepseek-v4.1-flash`, approve/reject only. Missing or partial
  lineups are rejected before the LLM call; LLM errors and malformed JSON become
  `no_bet`.
- **`variant=abc`**: A + B + C paper ledger; `variant=a_only` remains the deterministic
  baseline.
- **T-30** is the intended manual run window (lineups are often published 20–60 minutes
  before kickoff; T-60 may be too early). A is re-evaluated at that time with the latest
  HKJC price.
- CLI: `python -m app.cli agent-abc`.
- UI: `/agent` (A-only) and `/agent?variant=abc` (A+B+C); Performance has
  Production / Shadow / CLV sub-tabs.
- Migrations: `0007_agent_decisions`, `0008_agent_bets`, `0009_analyst_briefs`.
- Tests: 421 backend, 308 web; ruff/typecheck/lint/build pass.
- Not deployed: the host is still at `0006_shadow_ledger_bets`.
- Remaining: D research agent; injuries data; deploy and live T-30 smoke test.
