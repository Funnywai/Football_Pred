# Football_Pred

Paper-only football research system for **EPL + HAD** (Home / Draw / Away), using free data sources and HKJC odds.

> **No real money. No automatic HKJC login or bet placement.**
> The current model has not passed profitability validation. Treat every output as research, not a betting recommendation.

## What It Does

The system:

1. Collects free football data and HKJC odds.
2. Links EPL fixtures to HKJC matches.
3. Builds a deterministic Poisson score distribution for every eligible match.
4. Saves H/D/A model predictions.
5. Computes EV and Kelly sizing against the current HKJC line.
6. Records paper bets in a double-entry-style ledger.
7. Settles against HKJC 90-minute results.
8. Tracks Brier, CLV, ROI, drawdown, and calibration.
9. Records every decision — including no-bets and skipped matches — for audit.

The first validated slice is **EPL + HAD**. HDC, HIL, UCL, and LLM agents are not production paths.

## Architecture

```text
football-data.org ─┐
Understat ─────────┤
FotMob / PL / FPL ─┤
HKJC GraphQL ──────┤
RSS / Open-Meteo ──┘
                    │
                    ▼
             packages/adapters
                    │
                    ▼
             packages/ingest
       normalize · link · quality · raw store
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
  packages/models      packages/decision
  Poisson HAD          EV / Kelly / policy
          │                   │
          └─────────┬─────────┘
                    ▼
             packages/ledger
       bankroll · paper bets · settlement
                    │
                    ▼
             packages/feedback
       Brier · CLV · calibration · versions
                    │
                    ▼
             apps/api + web
          read-only dashboard
```

### Runtimes

| Path | Purpose |
|---|---|
| `apps/api` | FastAPI health, readiness, and read-only `/dashboard/*` endpoints |
| `apps/worker` | RQ jobs: daily ingest, trigger odds, decisions, settlement, reports |
| `apps/scheduler` | APScheduler: daily ingest, 60-second trigger scan, 5-minute reconciliation, 6-hour settlement scan, weekly calibration |
| `web` | Next.js server-rendered dashboard; server-side API only |
| `postgres` | Canonical data, predictions, ledger, calibration |
| `redis` | RQ queue |
| `cloudflared` | Optional Cloudflare Tunnel for `fp.funnywai.tech` |

## Prediction Workflow

### 1. Daily ingest

`run_daily_ingest`:

- fetches EPL fixtures from football-data.org;
- bootstraps teams;
- upserts canonical matches;
- links EPL matches to HKJC;
- writes raw payload and source-fetch audit rows.

### 2. Match-day triggers

| Trigger | Action |
|---|---|
| T-24h | initial odds, news, weather |
| T-3h | refresh odds and availability |
| T-75m | lineup check |
| T-30m | **official deterministic decision** |
| T-5m | closing odds snapshot for CLV |

### 3. Modeling

The production model is `poisson-v1`:

- fit team attack / defense from finished matches before `decision_at`;
- apply shrinkage toward league average;
- produce a 0–10 goal score grid;
- aggregate to `p_home`, `p_draw`, `p_away`.

The score distribution is persisted with every prediction.

### 4. Decision

For each HAD selection:

```text
EV = probability × odds − 1
```

The policy:

- choose the highest-EV side;
- require `EV ≥ 3%`;
- require positive Kelly fraction;
- stake = `available_bankroll × kelly × 0.25`;
- cap at **2% of bankroll**;
- minimum stake **HK$1**;
- otherwise no bet.

No-bet when:

- EV is below threshold;
- Kelly is non-positive;
- odds are below 1.01;
- the HAD line is missing, suspended, or not selling;
- the odds snapshot is older than 10 minutes;
- the match is not EPL / not scheduled;
- `first_seen_at > decision_at`;
- the quality gate vetoes the decision.

Every attempt writes a `DecisionLog` row, including skip reasons.

### 5. Ledger and settlement

- `PaperBet` stores the decision-time odds, stake, selection, and snapshot.
- `decision_slot_key` is unique: one official paper decision per match/slot.
- `bet_intent_key` prevents duplicate bets.
- Settlement uses HKJC 90-minute results.
- VOID/PUSH refunds use exact stake accounting to avoid 10-cent rounding artifacts.
- Settlement records Brier and CLV.

### 6. Feedback

- `model_versions`, `strategy_versions`, and `weight_snapshots` are versioned.
- `calibration_metrics` aggregates Brier, log-loss, ROI, CLV, and calibration bins.
- This layer **does not auto-change production weights**.

## API

Read-only dashboard endpoints:

```text
GET /healthz
GET /readyz
GET /dashboard/overview
GET /dashboard/predictions?limit=50
GET /dashboard/bets?limit=100
GET /dashboard/equity
GET /dashboard/calibration
GET /dashboard/technical
```

The browser never calls the API directly. The Next.js server fetches it server-side using `API_BASE_URL`.

## Repository Layout

```text
apps/
  api/          FastAPI app and dashboard endpoints
  worker/       RQ jobs
  scheduler/    APScheduler jobs
packages/
  adapters/     External data adapters
  backtest/     Historical walk-forward experiments
  db/           SQLAlchemy models and sessions
  decision/     T-30m decision, coverage, reconciliation
  domain/       Enums, errors, market parsing
  feedback/     Calibration and model/strategy versioning
  ingest/       Normalization, linking, quality, triggers
  ledger/       Paper bankroll, bets, settlement, metrics
  models/       Poisson model and prediction persistence
  payoff/       HAD/HDC/HIL return distributions and Kelly
  shared/       Config, time, logging
alembic/        Database migrations
scripts/        Operational and research scripts
tests/          Pytest suite
web/            Next.js dashboard
```

## Local Development

### Backend

```bash
cp .env.example .env
# Fill POSTGRES_PASSWORD, FP_DATABASE_URL, and FP_FOOTBALL_DATA_ORG_API_KEY.
chmod 600 .env

uv sync
uv run alembic upgrade head
uv run uvicorn apps.api.main:app --reload
```

The API runs at `http://127.0.0.1:8000`.

### Frontend

```bash
cd web
npm ci
API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

The dashboard runs at `http://127.0.0.1:3000`.

## Docker Compose

```bash
cp .env.example .env
# Fill secrets.
docker compose --env-file .env build
docker compose --env-file .env up -d postgres redis
docker compose --env-file .env run --rm api uv run alembic upgrade head
docker compose --env-file .env run --rm api uv run python -c "from apps.worker.jobs import run_daily_ingest; print(run_daily_ingest())"
docker compose --env-file .env up -d
```

Default services:

```text
postgres
redis
api
worker
scheduler
web
cloudflared   # profile: tunnel
```

Cloudflare Tunnel is optional and enabled with `COMPOSE_PROFILES=tunnel` plus `TUNNEL_TOKEN` in `.env`.

## Environment

| Variable | Purpose |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Postgres container |
| `FP_DATABASE_URL` | SQLAlchemy DSN; compose host must be `postgres` |
| `FP_REDIS_URL` | Redis DSN |
| `FP_FOOTBALL_DATA_ORG_API_KEY` | Free football-data.org key |
| `FP_INITIAL_BANKROLL` | Paper bankroll (default 10000.00) |
| `FP_FEE_RATE` | Ledger fee rate (default 0) |
| `FP_HTTP_TIMEOUT_SECONDS` | Adapter timeout |
| `FP_HKJC_GRAPHQL_URL` | HKJC endpoint |
| `FP_HKJC_QUERIES_DIR` | Captured official GraphQL queries |
| `FP_HKJC_QUERY_VERSION` | Query-capture version |
| `TUNNEL_TOKEN` | Cloudflare Tunnel token |
| `COMPOSE_PROFILES` | Set `tunnel` to start cloudflared |

Never commit `.env` or real credentials.

## Testing

Backend:

```bash
uv run pytest -p no:warnings
uv run ruff check packages tests apps scripts alembic
```

Frontend:

```bash
cd web
npm run typecheck
npm run lint
npm test
npm run build
```

## Current Model Status

The current deterministic Poisson baseline does **not** beat the closing market.

Historical EPL validation:

| Variant | Holdout Brier | Market Brier | Holdout Log-loss | Market Log-loss | ROI |
|---|---:|---:|---:|---:|---:|
| Poisson | 0.6251 | 0.6115 | 1.0388 | 1.0185 | -20.11% |
| Time-decay | 0.6165 | 0.6115 | 1.0276 | 1.0185 | -12.65% |
| Dixon-Coles | 0.6232 | 0.6115 | 1.0357 | 1.0185 | -26.01% |

These are research results, not a claim of profitability. Time-decay, Dixon-Coles, Elo, and temperature calibration are research variants; they are not promoted to production.

## Safety and Scope

- Paper-only ledger; no real wagers.
- No automated HKJC login or bet placement.
- No paid data dependency.
- LLM agents are not used in the production decision path.
- LLM production weight is zero.
- Do not promote a model or strategy based on in-sample or holdout-tuned results.
- Weight changes require time-block out-of-sample evidence and a new versioned evaluation period.

## Git

The deployed branch is `main`; the single `init` commit contains the new method.

The previous system is preserved in the `archive/agent-v1` branch.
