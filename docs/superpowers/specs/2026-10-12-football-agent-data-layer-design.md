# Football Betting AI Agent — Sub-system A: Data Layer — Design Spec

> Status: **Draft v1 — pending user approval**
> Date: 2026-10-12
> Project: rebuild of the WorldCup Discord bot into a FastAPI + Postgres + Next.js web app
> Scope: **Sub-system A (Data Layer) only.** ML engine, paper ledger, UI, orchestration, and the self-improvement loop are separate specs.

---

## 1. Context

The existing bot (`/Users/Kenny/Desktop/Discord Bot/WorldCup`) is a TypeScript Discord bot that
fetched HKJC odds for the **2026 World Cup** and produced DeepSeek LLM analysis. Two facts make it
unusable as-is:

1. **The 2026 World Cup is over** (Jun–Jul 2026; today is 2026-10-12). Its fixture filter only matches
   世盃/world cup, so it now returns nothing.
2. **HKJC results fetch fails after a match ends.** The main `matches(...)` GraphQL query only returns
   scheduled/live fixtures; finished games are dropped, so bets cannot be settled from the same call.

This spec rebuilds the data layer from scratch in **Python (FastAPI)** with a clean provider
abstraction, keeping the current bot only as a reference for fetch behaviour.

## 2. Goals / Non-goals

**Goals**
- Ingest HKJC **odds** for EPL + Big-5 leagues + UCL, continuously, as time-stamped snapshots.
- Reliably ingest **results for finished matches** (the flagged blocker), HKJC-first with external fallback.
- Provide a one-time historical backfill (football-data.co.uk, ~1993→present) for later ML training.
- Expose a stable internal data model + read API the ML/ledger/UI subsystems consume.
- Legal/low-risk: respect robots.txt, throttle, no commercial redistribution of raw odds.

**Non-goals (YAGNI, v1)**
- No ML/model training, no predictions, no betting ledger, no UI (later subsystems).
- No live/real-time streaming (HKJC Stream API) — deferred to a future upgrade.
- No multi-user/auth — single operator.

## 3. Verified technical facts (evidence-based)

- **HKJC GraphQL endpoint is live:** `POST https://info.cld.hkjc.com/graphql/base/` returned
  `{"data":{"__typename":"Query"}}` from `curl` with headers `Content-Type: application/json`,
  `Referer: https://bet.hkjc.com/`, `Origin: https://bet.hkjc.com`, browser `User-Agent`. No
  browser/session cookie required for reads.
- **⚠️ HKJC rejects hand-written / reduced GraphQL documents (probed 2026-10-12):** `{ matches { id } }`
  → `"doesn't match the schema"`; a valid-but-reduced `matches(...)` query → `Internal server error -
  WHITELIST_ERROR`; `{ __typename }` succeeds. ⇒ **You must send HKJC's exact query documents**;
  ad-hoc/minimal variations are refused. (An earlier reading of this as "Python is blocked" was WRONG.)
- **✅ CORRECTED + VERIFIED (2026-10-12):** with the package's **byte-exact** query documents, the
  endpoint works from **any HTTP client — including plain Python (`urllib`), no special headers**:
  `footballMatchesQuery` → **59 live matches** (Betis vs Osasuna); `historicFootballMatchesQuery` →
  **20 finished results** incl. `payoutConfirmed:true` (Liverpool 0-0 Man City). The `hkjc-api` npm
  package works because it sends exactly those documents. **⇒ DECIDED (2026-10-12): implement a
  self-written Python HKJC fetcher that ports these exact query documents. No Node sidecar.**
- **Introspection is disabled** (`__schema` query rejected) → field names must come from the
  reference client, not runtime introspection.
- **Live fixtures:** `matches(startDate, endDate, matchIds, tournIds, fbOddsTypes, inplayOnly,
  featuredMatchesOnly, showAllMatch, ...)` → scheduled/live; includes `foPools` (odds) and
  `runningResult` (live score), plus a `showAllMatch` flag worth testing for finished coverage.
- **Finished results (the fix):** `matchResult(startDate, endDate, startIndex, endIndex, matchId,
  teamId)` returns finished matches with `results { homeResult, awayResult, ttlCornerResult,
  payoutConfirmed, resultConfirmType, resultType }`. Per-match payout detail via
  `matchResult(matchId) { foPools(resultOnly:true) { ... winOrd } }`.
- **robots.txt of `bet.hkjc.com` explicitly ALLOWS `/football`** (disallows only `/info/*`,
  `/ContentServer/*`).
- **No maintained Python HKJC wrapper exists**, but the exact GraphQL documents port cleanly to Python
  (verified above). Source of the exact queries to copy: `Bobosky2005/hkjc-api` (MIT, TS) —
  `footballMatchesQuery`, `historicFootballMatchesQuery`, `historicFootballMatchDetailsQuery`.
- **Historical/backup source:** `football-data.co.uk` — free, keyless CSV, 22 European divisions back
  to 1993/94, with ~10 bookmakers' opening + closing odds. Used for backfill + result fallback.
  **Verified 2026-10-12:** Big-5 current-season CSVs are live (`mmz4281/2627/E0|SP1|I1|D1|F1.csv`
  → HTTP 200); **UCL/European competitions are NOT in this set (404)** → they need a separate source
  (e.g. football-data's `new/` UEFA files or API-Football).

## 4. Architecture

```
                 ┌──────────────────────────────────────────┐
                 │            Scheduler (APScheduler)        │
                 │  sync_odds (10m) · settle (15m) · backfill│
                 └───────────────┬──────────────────────────┘
                                 │
                 ┌───────────────▼──────────────────────────┐
                 │          Ingestion Services              │
                 │  FixtureSync · OddsSync · ResultReconciler│
                 └───────┬───────────────┬──────────────────┘
                         │               │
        ┌────────────────▼───┐   ┌───────▼────────────────┐
        │  HkjcProvider      │   │ FootballDataProvider   │
        │  (GraphQL)         │   │ (CSV/HTTP)             │
        └────────────────────┘   └────────────────────────┘
                         │               │
                 ┌───────▼───────────────▼──────────────────┐
                 │        PostgreSQL (SQLAlchemy)           │
                 │  leagues seasons teams matches           │
                 │  odds_snapshots results ingestion_runs   │
                 └───────────────┬──────────────────────────┘
                                 │
                 ┌───────────────▼──────────────────────────┐
                 │     Read API (FastAPI routers)          │
                 │  /matches /odds /results  (consumed by    │
                 │  ML engine, ledger, UI in later specs)    │
                 └──────────────────────────────────────────┘
```

**Design principles**
- **Provider abstraction**: each source implements one `Provider` Protocol; reconcilers/services are
  source-agnostic. Adding API-Football or an HKJC Stream upgrade = one new provider.
- **Idempotent upserts**: re-running any job never duplicates rows (natural keys + snapshot buckets).
- **Raw retention**: every fetched payload stored in JSONB for audit + replay, even if parsing changes.
- **Fail soft**: a source outage degrades (fallback / skip) rather than crashing the pipeline.

## 5. Data model (PostgreSQL)

| Table | Key columns | Notes |
|---|---|---|
| `leagues` | `id`, `code` (EPL/LALIGA/…), `name_en`, `name_ch`, `country`, `hkjc_tourn_id`, `active` | one row per competition |
| `seasons` | `id`, `league_id`, `label` ("2026/27"), `start_date`, `end_date` | |
| `teams` | `id`, `name_en`, `name_ch`, `hkjc_team_id`, `aliases text[]`, `external_ids jsonb` | alias set used for cross-source matching |
| `matches` | `id`, `season_id`, `league_id`, `hkjc_match_id` UNIQUE, `kickoff_time`, `status`, `home_team_id`, `away_team_id`, `venue`, `round`, `created_at`, `updated_at` | `status`: scheduled/live/finished/postponed/abandoned/cancelled |
| `odds_snapshots` | `id`, `match_id`, `captured_at`, `snapshot_bucket`, `source`, `inplay bool`, `odds_type` (HAD/HDC/HIL/CRS/HHA/CHD/CHL), `payload jsonb` | UNIQUE(`match_id`,`odds_type`,`inplay`,`snapshot_bucket`), where `snapshot_bucket` = `captured_at` truncated to the sync interval (makes re-runs idempotent). Enables open→close line features. |
| `results` | `id`, `match_id` UNIQUE, `home_score`, `away_score`, `ttl_corner`, `source` (hkjc/football_data), `confirmed bool`, `payout_confirmed bool`, `confirmed_at`, `raw jsonb` | HKJC row wins on conflict |
| `ingestion_runs` | `id`, `job`, `started_at`, `finished_at`, `status`, `records_upserted`, `error` | observability |

Notes:
- Odds are stored **raw-normalized** (one snapshot row per capture), not pre-flattened per selection —
  flattening/featurization belongs to the ML layer.
- `ttl_corner` only populated by HKJC (needed to settle CHD/CHL); external fallback leaves it null.
- **Timezones**: `kickoff_time`/`captured_at` are `timestamptz` (UTC); convert to Asia/Hong_Kong only for display.
- **Volume/retention**: raw snapshots grow fast (leagues × matches × odds types × every 10 min). Keep full history for the current season and training windows; roll up/archive older snapshots. A retention job is in scope.

## 6. Provider interface

```python
class League(BaseModel): ...
class FixtureRecord(BaseModel): ...
class OddsRecord(BaseModel): ...      # match_hkjc_id, odds_type, inplay, payload
class ResultRecord(BaseModel): ...    # match_hkjc_id | (date,home,away), home_score, away_score, ttl_corner

class Provider(Protocol):
    name: str
    async def fetch_leagues(self) -> list[League]: ...
    async def fetch_fixtures(self, date_from: date, date_to: date) -> list[FixtureRecord]: ...
    async def fetch_odds(self, fixtures: list[FixtureRecord]) -> list[OddsRecord]: ...
    async def fetch_results(self, date_from: date, date_to: date) -> list[ResultRecord]: ...
```

- **`HkjcProvider`**: GraphQL client. `fetch_fixtures` → `matches(...)`; `fetch_odds` → `matches(...)`
  with `fbOddsTypes` split into the two batches the reference client uses (API caps odds types per
  call); `fetch_results` → `matchResult(...)`; optional `fetch_result_details(match_id)` for payout.
  **Access note (§3):** `HkjcProvider` is a **self-written Python client** that sends the exact query
  documents ported from `hkjc-api` (verified working from plain Python); **no Node sidecar**. Keep all
  HKJC specifics behind this one interface.
- **`FootballDataProvider`**: downloads season CSVs (`https://www.football-data.co.uk/mmz4281/{season}/{div}.csv`).
  `fetch_results` parses latest-season CSV; `fetch_historical(...)` used by backfill.

## 7. Ingestion jobs & the result-reconciliation fix

**`sync_odds` — every ~10 min**
1. `fetch_fixtures(today, today+3d)` from HKJC for whitelisted tournaments.
2. Upsert `matches` (key `hkjc_match_id`), resolving teams/leagues via alias map.
3. `fetch_odds(fixtures)` → insert one `odds_snapshots` row per odds type per run.

**`settle_results` — every ~15 min during match windows (else daily)**
1. Candidate = matches with `kickoff_time < now` and no HKJC result yet.
2. `HkjcProvider.fetch_results(now-2d, now)` via **`matchResult`** → upsert `results` (source=hkjc,
   confirmed=true, payout_confirmed from payload; carry `ttl_corner`).
3. **Fallback**: matches still missing a result and older than kickoff+4h → `FootballDataProvider`,
   match by (date, home, away) via alias set → upsert (source=football_data, confirmed=false,
   ttl_corner=null). Never overwrite an existing HKJC row.
4. Anything still unresolved after 48h → flag in `ingestion_runs` for manual review.

**`backfill_history` — manual CLI (`python -m app.cli backfill --from 2010`)**
- Bulk-load football-data.co.uk seasons → results + (match-level) closing odds. Training corpus only.

## 8. Error handling, resilience, legal

- **Request hygiene**: always send the four required headers; browser UA; `Origin`/`Referer`.
- **Throttle**: max ~1 request / 1–2 s to HKJC; exponential backoff on 5xx/timeout; cap retries.
- **Raw audit**: store raw GraphQL/CSV payloads (`odds_snapshots.payload`, `results.raw`).
- **Isolation**: all HKJC specifics live only in `HkjcProvider` (the internal endpoint may change or
  block at any time — the legacy `getJSON.aspx` died this way).
- **Compliance**: obey `bet.hkjc.com/robots.txt` (`/football` allowed); personal/analytical use only;
  do **not** redistribute raw HKJC odds commercially.
- **Observability**: every job writes an `ingestion_runs` row; failures are recorded, not swallowed.

## 9. Testing strategy

- **Provider contract tests** against **recorded fixtures** (VCR-style cassettes of real HKJC GraphQL
  + football-data CSVs) — no live calls in CI.
- **Reconciliation tests**: HKJC hit; HKJC miss → football-data fallback; both miss → flagged;
  HKJC row never overwritten by fallback.
- **Idempotency tests**: running each job twice changes row counts only by new snapshots, not duplicates.
- **Alias-matching tests**: known tricky team-name pairs (e.g. 曼聯/Man Utd/Manchester United).
- **Opt-in live smoke test** (`pytest -m live`) hitting the real endpoint, run manually.

## 10. Configuration (env)

`DATABASE_URL`, `HKJC_GRAPHQL_URL`, `HKJC_REFERER`, `HKJC_ORIGIN`, `HKJC_USER_AGENT`,
`FOOTBALL_DATA_BASE`, `SYNC_ODDS_INTERVAL`, `SYNC_SETTLE_INTERVAL`, `LEAGUE_WHITELIST`,
`HKJC_THROTTLE_SECONDS`.

## 11. Risks & open questions

| Risk | Mitigation |
|---|---|
| HKJC internal endpoint changes/blocks | isolate in one provider; raw logging; external fallback for results |
| **HKJC rejects ad-hoc queries (§3)** | use the exact query documents ported from `hkjc-api` (verified working from Python); Node sidecar is an optional fallback; isolate HKJC specifics in one provider |
| `matchResult` payout confirmation lags | retry window (up to 48h) + `payoutConfirmed` flag; settle P&L on `confirmed` only |
| Team-name matching errors across sources | curated alias table + fuzzy match + manual-review queue |
| odds-types-per-call cap | two-batch fetch like the reference client |
| Legal exposure | robots.txt-compliant, throttled, non-commercial, no redistribution |

**Probe results (2026-10-12):**
1. `showAllMatch` / raw GraphQL schema — **moot**: raw custom queries are allowlist-blocked, but the
   `hkjc-api` package works, so we use it (no need for `showAllMatch`).
2. `hkjc_tourn_id` for EPL/Big-5/UCL — **now obtainable** from `getAllFootballMatches` results
   (`tournament.id`); capture during first sync.
3. `matchResult` payout latency after full-time — **not yet measured**; the 48h retry window is the safe
   default (observed results already carry `payoutConfirmed:true`).
4. `football-data.co.uk` coverage — **RESOLVED**: Big-5 current-season CSVs live (HTTP 200); UCL absent (404).

**Remaining open questions:**
- ✅ HKJC access route — **RESOLVED: plain Python works with the exact query documents** (verified
  2026-10-12: `footballMatchesQuery` → 59 live matches; `historicFootballMatchesQuery` → 20 finished
  results with `payoutConfirmed`). No Node sidecar required; port the exact query strings from `hkjc-api`.
- The exact `hkjc_tourn_id` values for EPL/Big-5/UCL (readable from `getAllFootballMatches` results).
- `matchResult` payout latency after full-time (the 48h retry window is the safe default).
- **Implementation gotcha:** the `getHistoricFootballMatches` convenience wrapper returned 0 rows for
  2026-10-04→10-07, while `searchHistoricFootballMatches` with explicit `startIndex`/`endIndex` returned
  the data (507 rows for 10-04→10-11). **Use `searchHistoricFootballMatches` with explicit pagination.**

## 12. Delivered in this sub-system

- `HkjcProvider` (self-written Python GraphQL client; exact queries ported from `hkjc-api`) +
  `FootballDataProvider` + provider Protocol
- Postgres schema + SQLAlchemy models + migrations
- `sync_odds` / `settle_results` / `backfill_history` jobs
- FastAPI read endpoints: `/matches`, `/matches/{id}/odds`, `/results` (for later subsystems)
- Test suite (contract + reconciliation + idempotency + alias)

**Out of scope (later specs):** ML/RL engine (B), paper ledger (C), Web UI (D), orchestration (E),
self-improvement loop (F).
