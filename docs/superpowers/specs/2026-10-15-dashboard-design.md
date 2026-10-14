# Web dashboard (Sub-system D)

> Date: 2026-10-15
> Scope: a **new sibling service** (`web`, Next.js) that reads the existing read-only API
> and the separately-specified read-only `/ops/*` endpoints. No change to the model, the
> ledger, the scheduler, or any write path. No schema change, no migration.
> Related: `docs/superpowers/specs/2026-10-14-ledger-execution-price-design.md` (the
> execution-price semantics this dashboard surfaces), `2026-10-12-paper-ledger-design.md`
> (sub-system C), `2026-10-12-football-agent-ml-engine-design.md` (the market prior and CLV),
> `deploy/cloudflare-tunnel.md` (the public entry this spec repoints).

---

## 1. Context and problem

Sub-systems A (data), B (ML), and C (paper ledger) are live. The system already produces
everything a human needs to judge it: predictions, bets, settlements, an equity curve, model
metrics, and a scheduler that runs inside the app process. What is missing is a way to **see
the system think**. Today the only windows are `docker compose logs` and ad-hoc SQL.

The brief is a two-tab dashboard with one shared header:

- **Part 1, general performance monitor**: every match, every prediction, every bet placed,
  every outcome (loss or profit), and an overview of money (a chart of total money over time).
- **Part 2, technical monitor**: logs and the more technical surface (scheduler, ingestion,
  freshness, DB size, model versions, environment).

The style is a technical trading terminal / mission control: dark, dense, animated, and
built so you can watch the pipeline move. This spec fixes the architecture, the exact data
surface, the page structure, the visual thesis, and the acceptance steps. It does not write
implementation code.

## 2. Decision (architecture)

| Concern | Decision |
| --- | --- |
| Hosting | A **new compose service `web`** (Next.js, App Router + TypeScript + Tailwind + shadcn/ui + Recharts), built from its own `web/Dockerfile`, joining the existing default compose network. |
| API reachability | The `web` container calls the API at `http://app:8000` over service-name DNS. The app keeps publishing only `127.0.0.1:8000:8000` (`docker-compose.yml:58`); `web` does not need a host port. |
| Where API calls happen | **Server-side only** (React Server Components and, where needed, route handlers). The browser never calls the API directly. |
| Why server-side | The FastAPI app has **no CORS configured** and **must not be modified**. Server-side proxying avoids CORS entirely and keeps zero tokens or secrets in the browser. |
| App changes | None, except the separate, already-approved read-only `/ops/*` endpoints (a different spec and PR). |
| Public entry | The existing Cloudflare Tunnel public hostname is **repointed** from `app:8000` to `web:3000`. The API becomes internal-only. Cloudflare Access (email OTP) stays the only auth. |
| Auth | Cloudflare Access only. The dashboard implements no login, no session, no token handling. |

The single-writer rule is untouched: `web` is a read-only consumer. It never writes to the
database, never calls a mutating endpoint, and never touches the scheduler.

## 3. Public entry and the tunnel change

Current state (`deploy/cloudflare-tunnel.md:42-50`): the Tunnel's Public Hostname points its
Service URL at `app:8000`, so the public hostname currently serves the raw FastAPI app.

Change:

1. Repoint the Public Hostname Service URL from `app:8000` to `web:3000`. `cloudflared` and
   `web` share the compose network, so the service name resolves.
2. The API is now reachable only from inside the compose network (`app:8000`) and from the
   host loopback (`127.0.0.1:8000`). It is no longer a public hostname.
3. Cloudflare Access (email OTP) is unchanged and remains the only gate. The dashboard adds
   no auth of its own.

Note on `deploy/cloudflare-tunnel.md` section 5: that section describes hosting sub-system D
on Cloudflare Pages and calling the API with a Service Token plus CORS. That approach is
**superseded**. D now runs as a compose service and proxies the API server-side, so there is
no cross-origin call, no Service Token, and no CORS change. The tunnel doc should be updated
to reflect the repoint when this ships.

## 4. Data surface (exact, verified)

All fields below are the exact names returned by the current API (`app/api/schemas.py`,
`app/api/routes.py`). The dashboard must not invent fields or routes.

### 4.1 Non-ops surface (existing, read-only)

| Route | Returns | Filters / params |
| --- | --- | --- |
| `GET /health` | `{"status":"ok"}` | none |
| `GET /bets/summary` | `initial_bankroll, bankroll, n_bets, n_settled, n_open, stakes_total, open_stakes, realized_profit, roi, yield_pct` | none |
| `GET /bets/equity-curve` | `[{t: datetime \| null, bankroll: float}]`, one point per settlement plus an initial point where `t` is null | **none** (no date range) |
| `GET /bets` | per bet: `id, match_id, target, outcome, model_version_id, line, odds, stake, bankroll_at_place, edge, kelly_multiplier, status, placed_at, settled_at, payout, profit, kickoff_time, league_code, home_team, away_team` | `status, match_id, target, limit (default 50), offset` (no date filter) |
| `GET /predictions` | `id, match_id, target, outcome, model_version_id, prob, implied_prob, edge, fair_odds, market_odds, recommended_fraction, kickoff_time, league_code, home_team, away_team` | `match_id, target, value_only, champion_only (default true), limit (default 50), offset` |
| `GET /models` | `id, target, algorithm, status, metrics, artifact_path, created_at, promoted_at`. `metrics` for 1x2: `brier, logloss, n, clv_fraction, clv_mean_edge, clv_n`; for handicap: `brier, logloss, n` | none |
| `GET /matches` | `id, league_code, league_name, kickoff_time, status, home_team{id,name_en,name_ch}, away_team{...}, venue, round, hkjc_match_id` | `date_from, date_to, league, status, limit (default 100), offset` |
| `GET /matches/{id}/odds` | `odds_type, inplay, source, captured_at, snapshot_bucket, payload` | `odds_type, inplay, history` |
| `GET /results` | `match_id, home_score, away_score, ttl_corner, source, confirmed, payout_confirmed, confirmed_at, kickoff_time, league_code, home_team{...}, away_team{...}` | `date_from, date_to, league, limit (default 100), offset` |

### 4.2 Ops surface (separate spec and PR, read-only)

The dashboard's technical tab depends on these endpoints. They are specified elsewhere and
are **not** part of this spec's implementation scope; this spec only consumes them.

| Route | Supplies |
| --- | --- |
| `GET /ops/status` | app version, git SHA, alembic revision, DB connectivity |
| `GET /ops/jobs` | each scheduled job: interval/trigger, `next_run_time`, last status, `finished_at`, `records_upserted`, error |
| `GET /ops/runs` | ingestion run history (timeline), including failures |
| `GET /ops/logs` | recent log lines with level, for the live log stream |
| `GET /ops/data` | row counts per table, `odds_snapshot` counts by source/odds_type, post-compaction anchors |

### 4.3 Semantics the dashboard must state on screen

These are not cosmetic. They change how a number should be read, and the UI must say so.

1. **Execution price vs signal price.** `ledger_bets.odds` is the **execution price**: the
   latest pre-kickoff HKJC HAD snapshot, taken at placement time. `predictions.market_odds`
   is the **48h prior (signal) price**. Since 2026-10-14 these differ by design, so a
   "signal price vs execution price" comparison is a first-class view, not a debug detail.
2. **Edge is measured at the execution price.** `ledger_bets.edge` is `prob - implied` at the
   execution price. It is not the signal edge. Bets placed before 2026-10-14 carry the old
   meaning (edge against the prior price); there was no backfill, so cross-period comparison
   must consider the placement date.
3. **CLV is the ML-layer proxy.** `clv_mean_edge` and `clv_n` come from the ML layer
   (model fair price vs closing price). The ledger's execution price **never** enters CLV.
4. **No CLV time series and no per-bet CLV.** No endpoint exposes either. This is a known
   gap. v1 shows the current scalars only. A time series is deferred until `clv_n` grows past
   roughly 100.
5. **`match_features` and `ingestion_runs` are not exposed** by the non-ops surface. The
   `/ops/*` endpoints supply them (row counts via `/ops/data`, run history via `/ops/runs`).
6. **No runtime counters exist.** There are no API-call counters and no error counters
   anywhere in the system. The dashboard therefore shows **no** request-rate or error-rate
   charts. Do not invent them.

## 5. Page structure (two tabs, one shared header)

### 5.1 Shared header (always visible, both tabs)

A single sticky header, dense, one row on wide screens. It carries:

- **Money**: bankroll, realised profit, open exposure (from `/bets/summary`:
  `bankroll`, `realized_profit`, `open_stakes`).
- **Scheduler heartbeat dot**: green/amber/red derived from `/ops/jobs` (`next_run_time` per
  job) and `/ops/runs` (recency of the newest `finished_at`, plus any `failed`/`flagged`/stuck
  `running` rows).
- **Build identity**: git SHA and the champion model's `target` and `status` (from
  `/ops/status` and `/models`).
- **Data freshness**: last data arrival, from `/ops/data` (`last_arrived.odds_captured_at`,
  `features_built_at`, `results_confirmed_at`) and the newest `ml_predict` row in `/ops/runs`
  for prediction freshness.
- **System-thinking indicator**: which pipeline stage is currently active, derived from
  `/ops/jobs` and `/ops/runs` (see 5.2c).

### 5.2 Tab 1, Performance

| # | Section | Source |
| --- | --- | --- |
| a | **KPI strip** as bullet-chart style indicators: bankroll, realised profit, ROI, yield %, open stakes, n bets, win rate | `/bets/summary` (`bankroll, realized_profit, roi, yield_pct, open_stakes, n_bets`); win rate derived from settled bets in `/bets` |
| b | **Equity / money curve**: line chart from `/bets/equity-curve`, including the initial point where `t` is null | `/bets/equity-curve` |
| c | **AI pipeline visual**: six stages `INGEST -> FEATURES -> PREDICT -> BET -> SETTLE -> RETRAIN`, each with last action time and live status | `/ops/jobs` + `/ops/runs` |
| d | **Signal vs execution price table**, per bet: prior `market_odds` -> execution `odds` -> % difference | `/bets` joined to `/predictions` on `(match_id, target, outcome, model_version_id)` |
| e | **All bets table**: odds, edge, stake, payout, profit, status, kickoff | `/bets` |
| f | **All matches x predictions table**: model `prob` vs `implied_prob` vs `edge` vs whether a bet was placed | `/predictions` joined to `/bets` on `(match_id, target, outcome)` |
| g | **Results**: score, `confirmed`, `payout_confirmed` | `/results` |
| h | **CLV card**: `clv_mean_edge`, `clv_fraction`, `clv_n`, `brier`, `logloss`, with a note that CLV is the only evidence available before wins and losses accumulate | `/models` (champion 1x2 `metrics`) |

The join in (d) and (f) is done server-side. The API has no join endpoint, so the server
fetches both lists and merges them in memory by the keys above. Both lists are paginated
(`limit`/`offset`); v1 fetches the first page of each and states the page size on screen.

### 5.3 Tab 2, Technical

| # | Section | Source |
| --- | --- | --- |
| a | **Live log stream**: level filter, auto-refresh, pause | `/ops/logs` |
| b | **Scheduler table**: each job's interval/trigger, `next_run_time`, last status, `finished_at`, `records_upserted`, error | `/ops/jobs` |
| c | **Ingestion runs timeline**, failures highlighted | `/ops/runs` |
| d | **Data freshness panel**: last snapshot / feature / result / prediction arrival, ageing red past threshold | `/ops/data` (`last_arrived`) + newest `ml_predict` row in `/ops/runs` |
| e | **DB size table**: row counts per table, `odds_snapshot` counts by source/odds_type, post-compaction anchors | `/ops/data` |
| f | **Model version timeline**: champion/challenger, `promoted_at`, `metrics`, `artifact_path`, params | `/models` + `/ops/data` (`params`) |
| g | **Environment**: app version, git SHA, alembic revision, DB connectivity. **Never any secret or env value.** | `/ops/status` |

## 6. Visual and style spec (the design thesis)

### 6.1 Thesis

Technical trading terminal / mission control. Dark, dense, monospace tabular numerals so
numbers never jitter. Hairline dividers instead of a sea of identical rounded cards.
Information hierarchy by weight and scale, not by decoration. The screen should read like an
instrument panel: quiet chrome, loud data.

### 6.2 Density

Target the ui-ux-pro-max `--density 8` setting (dense/dashboard, 8-32px spacing scale). Use
it to pull chart and density guidance. The skill's own `SKILL.md` prints a Claude-only
`CLAUDE_PLUGIN_ROOT` path that does **not** work here; the working path is
`~/.agents/skills/ui-ux-pro-max/scripts/search.py`. See section 11 for the exact commands.

### 6.3 Charts

- **KPI comparisons -> bullet chart**, not gauges. The guidance returns "Bullet Chart" for
  compact multi-KPI dashboards and warns that a gauge is too large for a grid.
- **Money over time -> line chart**, not candlestick. The guidance is explicit that
  candlestick is for financial audiences; this is a non-financial audience watching a paper
  ledger. Line chart, with the initial point included.
- **Every chart must have an accessible table fallback.** The guidance's a11y fallback for
  both chart types is a visible data table plus a short summary.
- **Colour must never be the only carrier of meaning.** Pair colour with a shape, a label, or
  text (for example, a loss is red **and** carries a minus sign and a "loss" label).

### 6.4 Motion rules

Animate **only state changes**:

- Number roll on change (KPI values, bankroll).
- A brief row highlight when a new bet appears.
- A pipeline node lighting up when its stage becomes active.
- The equity curve extending at the right edge when a new settlement lands.

**Banned** (these are the generic AI tells named by the anti-slop design guidance):

- Scroll-triggered section fade or slide-in entrances.
- Hover-transition-everything (every element animating on hover).

Respect `prefers-reduced-motion`: when set, disable all of the above and render final states
directly.

### 6.5 Typography and colour tokens

The token set is defined in **`web/DESIGN.md`**, which is the single source of truth for every
colour, font size, spacing value, and component pattern. This spec does not duplicate the token
values; it states the direction only.

Direction: a dark terminal aesthetic, deliberately **not** the default AI palette (no cream +
serif + terracotta, no identical-card SaaS kit). The canvas is void-black, the accent is a single
emerald signal used with intent, and the palette is emerald plus warm neutrals on near-black.
Data and UI use a terminal monospace with tabular numerals on every numeric cell so digits never
jitter; prose uses a geometric sans. Status colours are always paired with a label or sign, never
colour alone.

See `web/DESIGN.md` sections 2 (colour), 3 (typography), and 4 (spacing) for the exact tokens and
scale.

### 6.6 Design System Gate

`web/DESIGN.md` is the implementation contract and MUST exist before any component is written.
Every colour, font size, spacing value, and component pattern traces back to a token in that
file. If a component needs a token that does not exist, the token is added to `web/DESIGN.md`
first, then used. No raw hex, no arbitrary px, and no ad-hoc component pattern may bypass the
system.

### 6.7 React Dev Tooling Gate

The `web` service ships React, so three dev-only tools are installed before any UI
implementation, all gated behind `process.env.NODE_ENV === 'development'` so they never reach
production:

- `react-grab` (`npx grab@latest init`): UI element to AI source context.
- `react-doctor` (`npx react-doctor@latest install`): agent-skill install plus static scan.
- `react-scan` (`npx react-scan@latest init`): render highlighter.

Verify the gate by grepping `app/layout.tsx` for `react-grab` and `react-scan` and confirming
each sits behind the development check. The user opts out, not in.

### 6.8 Performance gate

The dashboard must reach **Lighthouse 100 in every category**, measured against a **production
build** with **real Playwright Chromium** (never the `lighthouse` CLI, never a dev server). The
score is achieved through architecture (server components, minimal client JS, no layout thrash),
never by weakening UX, dropping animation, or hiding content. A page that reaches 100 by removing
the pipeline motion or the equity curve has failed the gate.

## 7. Skills that drive each phase

| Phase | Skill | Purpose |
| --- | --- | --- |
| Direction | `impeccable` (Operate mode) | Sets the mission-control direction and the density/quiet-chrome stance. |
| Chart and density data | `ui-ux-pro-max` | Pulls chart-type, colour, typography, and UX guidance at `--density 8`. |
| Implementation | `frontend` | Builds the Next.js app and runs the Lighthouse / Core Web Vitals pass. |
| Visual QA | `visual-qa` | Screenshot and pixel QA of both tabs. |
| Compliance | `web-design-guidelines` | The accessibility and UX compliance pass. |

Note: `frontend-design` must **not** be loaded at the same time as `impeccable`. They are two
competing design doctrines; loading both produces contradictory direction.

## 8. Data-mapping table (section -> route -> fields)

| Page section | Route(s) | Fields used |
| --- | --- | --- |
| Header money | `/bets/summary` | `bankroll, realized_profit, open_stakes` |
| Header heartbeat | `/ops/jobs`, `/ops/runs` | `next_run_time` per job; newest `finished_at`; `failed`/`flagged`/stuck `running` rows |
| Header build identity | `/ops/status`, `/models` | git SHA; champion `target`, `status` |
| Header freshness | `/ops/data`, `/ops/runs` | `last_arrived.odds_captured_at`, `features_built_at`, `results_confirmed_at`; newest `ml_predict` run `finished_at` |
| Header thinking indicator | `/ops/jobs`, `/ops/runs` | active job, latest run stage |
| 1a KPI strip | `/bets/summary`, `/bets` | `bankroll, realized_profit, roi, yield_pct, open_stakes, n_bets`; win rate from settled `status` |
| 1b Equity curve | `/bets/equity-curve` | `t, bankroll` |
| 1c Pipeline | `/ops/jobs`, `/ops/runs` | job status, `finished_at`, run stage |
| 1d Signal vs execution | `/bets`, `/predictions` | bet `odds`; prediction `market_odds`; difference |
| 1e Bets table | `/bets` | `odds, edge, stake, payout, profit, status, kickoff_time` |
| 1f Matches x predictions | `/predictions`, `/bets` | `prob, implied_prob, edge`; bet presence |
| 1g Results | `/results` | `home_score, away_score, confirmed, payout_confirmed` |
| 1h CLV card | `/models` | `clv_mean_edge, clv_fraction, clv_n, brier, logloss` |
| 2a Log stream | `/ops/logs` | level, message, timestamp |
| 2b Scheduler table | `/ops/jobs` | interval/trigger, `next_run_time`, status, `finished_at`, `records_upserted`, error |
| 2c Ingestion timeline | `/ops/runs` | run start/end, status, failure |
| 2d Freshness panel | `/ops/data`, `/ops/runs` | `last_arrived` timestamps; newest `ml_predict` run |
| 2e DB size | `/ops/data` | row counts, `odds_snapshot` counts by source/odds_type, anchors |
| 2f Model timeline | `/models`, `/ops/data` | `status, promoted_at, metrics, artifact_path`; `params` from `/ops/data` |
| 2g Environment | `/ops/status` | app version, git SHA, alembic revision, DB connectivity |

## 9. Proposed file and module layout for the `web` service

```
web/
  Dockerfile
  package.json
  next.config.ts
  tsconfig.json
  tailwind.config.ts
  postcss.config.mjs
  app/
    layout.tsx                 # root layout, fonts, tokens
    globals.css                # CSS variables (tokens defined in web/DESIGN.md)
    page.tsx                   # redirects to /performance
    performance/page.tsx       # Tab 1
    technical/page.tsx         # Tab 2
  components/
    header/SystemHeader.tsx
    header/HeartbeatDot.tsx
    header/PipelineIndicator.tsx
    kpi/KpiStrip.tsx
    kpi/BulletChart.tsx
    charts/EquityCurve.tsx
    charts/ChartTableFallback.tsx
    pipeline/PipelineFlow.tsx
    pipeline/PipelineNode.tsx
    tables/BetsTable.tsx
    tables/SignalVsExecutionTable.tsx
    tables/MatchesPredictionsTable.tsx
    tables/ResultsTable.tsx
    clv/ClvCard.tsx
    technical/LogStream.tsx
    technical/SchedulerTable.tsx
    technical/IngestionRunsTimeline.tsx
    technical/FreshnessPanel.tsx
    technical/DbSizeTable.tsx
    technical/ModelTimeline.tsx
    technical/EnvironmentPanel.tsx
  lib/
    api.ts                     # server-side fetch wrapper, reads API_BASE_URL
    ops.ts                     # /ops/* fetchers
    types.ts                   # TS types mirroring app/api/schemas.py
    format.ts                  # HKD, %, odds, datetime formatters
    freshness.ts               # ageing thresholds for the freshness panel
```

`lib/api.ts` and `lib/ops.ts` run only on the server. They read `API_BASE_URL` from the
environment and never expose it to the client bundle.

## 10. Compose service sketch

Add to `docker-compose.yml` (sketch only; this spec does not edit the file):

```yaml
  web:
    build: ./web
    environment:
      API_BASE_URL: http://app:8000
      NODE_ENV: production
    depends_on:
      app:
        condition: service_healthy
    # No ports: the Cloudflare Tunnel reaches web:3000 over the compose network.
    restart: unless-stopped
    logging: *default-logging
```

Notes:

- Service name `web`, build directory `./web`, internal port `3000`.
- `depends_on: app: condition: service_healthy` reuses the app's existing healthcheck.
- **No host port exposure.** The tunnel reaches `web:3000` over the compose network, exactly
  as it currently reaches `app:8000`.
- No `docker.socket` access, no privileged mode, no extra volumes.

## 11. Local development

Run the API locally, then the dashboard against it:

```bash
# terminal 1: the API (from the repo root)
uv run uvicorn app.api.main:create_app --factory --reload    # http://127.0.0.1:8000

# terminal 2: the dashboard
cd web
npm install
API_BASE_URL=http://127.0.0.1:8000 npm run dev               # http://127.0.0.1:3000
```

To preview the ui-ux-pro-max guidance used in section 6 (the working path, not the
`CLAUDE_PLUGIN_ROOT` path printed by the skill's own `SKILL.md`):

```bash
python3 ~/.agents/skills/ui-ux-pro-max/scripts/search.py "line chart time series" --domain chart --density 8
python3 ~/.agents/skills/ui-ux-pro-max/scripts/search.py "bullet chart KPI comparison" --domain chart --density 8
python3 ~/.agents/skills/ui-ux-pro-max/scripts/search.py "dark terminal dashboard" --domain color --density 8
python3 ~/.agents/skills/ui-ux-pro-max/scripts/search.py "monospace tabular numerals" --domain typography --density 8
python3 ~/.agents/skills/ui-ux-pro-max/scripts/search.py "dashboard density information hierarchy" --domain ux --density 8
```

## 12. Non-goals

- No writes of any kind to the model or the ledger. The dashboard is read-only.
- No auth logic. Cloudflare Access (email OTP) is the only gate.
- No changes to the app service besides the separately-specified read-only `/ops/*`.
- No CLV time series in v1. No endpoint exists; deferred until `clv_n` grows past roughly 100.
- No handicap-specific views beyond reading existing rows.
- No client-side calls to the API. Server-side only.
- No exposing secrets or environment values anywhere in the UI.
- No counters that do not exist (no API-call or error counters).
- No modification of the app's write paths or the single-writer rule.
- No `docker.socket` access.

## 13. Acceptance

On the host, after the `web` service and the `/ops/*` endpoints are in place:

1. **Build and up**: `docker compose build web && docker compose up -d web`. `docker compose ps`
   shows `web` running and `app` healthy.
2. **Open the tunnel URL**: browse to the Cloudflare Access hostname, pass email OTP, and land
   on the dashboard (not the raw API).
3. **Tab 1 renders real numbers**: the KPI strip, equity curve, pipeline, signal-vs-execution
   table, bets table, matches x predictions table, results, and CLV card all show values that
   match `curl -s localhost:8000/bets/summary` and the other endpoints.
4. **Tab 2 renders real numbers**: log stream, scheduler table, ingestion timeline, freshness
   panel, DB size table, model timeline, and environment panel all populate from `/ops/*`.
5. **No API token in the browser**: open devtools, confirm no request goes to `app:8000` or
   any API host from the browser, and no token or secret appears in the client bundle or
   network tab. All API traffic is server-side.
6. **Visual QA is the sole completion authority**: run `/visual-qa` on a real browser at
   375 / 768 / 1280 px, on every page, driving and inspecting interaction states
   (hover / focus / active) and motion, until the dual-oracle pass succeeds on fresh evidence.
   A surface that is bug-free but flat is NOT done. Every chart must have a table fallback,
   colour must never be the sole carrier of meaning, and `prefers-reduced-motion` must disable
   the state-change animations.
