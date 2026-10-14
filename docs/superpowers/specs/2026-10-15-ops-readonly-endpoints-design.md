# Ops read-only endpoints (sub-system D groundwork)

> Date: 2026-10-15
> Scope: **additive read-only `/ops/*` HTTP surface only** — five GET routes in a new
> `app/api/ops.py` module, plus a bounded in-memory log ring buffer. No schema change, no
> migration, no change to the existing nine routes or their schemas, no writes anywhere.
> Related: `docs/superpowers/specs/2026-10-12-paper-ledger-design.md` (sub-system C),
> `docs/superpowers/specs/2026-10-14-ledger-execution-price-design.md`.

---

## 1. Context and problem

The app already exposes nine read routes (`app/api/routes.py`): `health`, `matches`,
`matches/{id}/odds`, `results`, `predictions`, `models`, `bets`, `bets/summary`,
`bets/equity-curve`. The router has no prefix and no auth, and is mounted in `create_app`
(`app/api/main.py:57`). Those routes answer "what is the data", not "is the system healthy".

A future Next.js dashboard (sub-system D) needs the operational view: is the process up,
which scheduled jobs are live and when did each last run, what did recent ingestion runs
do, what is in the log right now, and how fresh is the data. None of that is exposed today.

Three facts shape the design:

1. **There is no log file.** `configure_logging` (`app/config.py:75-85`) calls
   `logging.basicConfig(level, format=...)` with no `handlers` argument, so the only sink is
   the default `StreamHandler` to stderr. There is no `FileHandler` anywhere, and the compose
   `app` service mounts only `artifacts:/app/artifacts` (`docker-compose.yml:61`). Logs are
   visible only through `docker compose logs app`.
2. **There are no runtime counters.** No Prometheus, no StatsD, no in-process counters. The
   only per-run number that exists is `ingestion_runs.records_upserted`.
3. **Run state is persisted, but not for every job.** `ingestion_runs`
   (`app/db/models.py:146-155`) is written only by `track_run` (`app/services/runs.py:10-44`)
   and `flag_manual_review` (`app/services/runs.py:47-67`). `prune_odds` does not call
   `track_run` (`app/scheduler.py:91-102`), so it has no persisted row.

## 2. Decision: routes, module, and mounting

Five new GET routes, all under the `/ops` prefix, in a **new module `app/api/ops.py`** with
its own `APIRouter(prefix="/ops", tags=["ops"])`. The router is included in `create_app`
(`app/api/main.py`) with `app.include_router(ops_router)` next to the existing
`app.include_router(router)`. The existing `app/api/routes.py` and `app/api/schemas.py` are
**not modified**: no route, no schema, no import changes there.

| Route | Query params | Purpose |
| --- | --- | --- |
| `GET /ops/status` | none | process identity, DB connectivity, scheduler flag |
| `GET /ops/jobs` | none | live scheduler jobs + last persisted run per job |
| `GET /ops/runs` | `limit` (default 50, max 200) | recent `ingestion_runs` rows |
| `GET /ops/logs` | `limit` (default 100, max 500), `level` (optional) | in-memory log tail |
| `GET /ops/data` | none | table counts, freshness, model params, alembic revision |

All responses are JSON. All datetimes are ISO 8601 strings in UTC (for example
`2026-10-15T04:00:00+00:00`). All routes are read-only: no `POST`, `PUT`, `PATCH`, or
`DELETE`, and no route issues an `INSERT`, `UPDATE`, or `DELETE`.

The routes reuse the existing session dependency pattern. `app/api/ops.py` defines its own
`get_session` (identical to `routes.py:36-38`, reading `request.app.state.db.session_factory`)
so the two modules stay independent. The scheduler is read defensively:
`getattr(request.app.state, "scheduler", None)`, because the lifespan that sets
`app.state.scheduler` (`app/api/main.py:42`) does not run under the test transport.

## 3. `GET /ops/status`

| Field | Type | Source |
| --- | --- | --- |
| `app_version` | `str` | `pyproject.toml` `[project].version` |
| `git_sha` | `str` | `GIT_SHA` environment variable |
| `alembic_revision` | `str \| null` | `SELECT version_num FROM alembic_version` |
| `uptime_seconds` | `float` | `time.monotonic()` minus module import time |
| `db_ok` | `bool` | `SELECT 1` succeeds |
| `scheduler_enabled` | `bool` | `settings.enable_scheduler` |

**App version, single source of truth.** Read `pyproject.toml` `[project].version` with the
stdlib `tomllib`, resolving the path relative to the module
(`Path(__file__).resolve().parents[2] / "pyproject.toml"`). Justification: `pyproject.toml`
is the canonical declaration of the package version, it is copied into the image
(`Dockerfile:21`), and `tomllib` is stdlib on Python 3.11+ (`requires-python = ">=3.11"`).
This avoids depending on installed distribution metadata, which is unreliable here because
the image runs `uv sync --frozen --no-dev` (`Dockerfile:22`) before `app/` is copied
(`Dockerfile:26`). On any read or parse failure the value is `"unknown"`.

**Git SHA, baked at build.** `.git` is not in the image, so the SHA is injected at build
time. `Dockerfile` gains, before `USER appuser`:

```dockerfile
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA
```

`docker-compose.yml` `app.build` becomes a mapping that forwards the arg:

```yaml
    build:
      context: .
      args:
        GIT_SHA: ${GIT_SHA:-unknown}
```

The operator builds with `GIT_SHA=$(git rev-parse --short HEAD) docker compose build`. The
route reads `os.environ.get("GIT_SHA", "unknown")`. When the arg is not supplied the value is
`"unknown"`, never a fabricated SHA.

**Alembic revision.** `SELECT version_num FROM alembic_version`. The table is the default
Alembic table (single column `version_num VARCHAR(32)` primary key). Current head is
`0003_ledger_bets` (chain `0001` -> `0002_ml_tables` -> `0003_ledger_bets`). If the table is
missing or empty, return `null` rather than raising.

**Uptime.** Capture `_PROCESS_START = time.monotonic()` at import of `app/api/ops.py` and
return `time.monotonic() - _PROCESS_START`. Module import time is used instead of a lifespan
timestamp so the value is present under the test transport, which does not run the lifespan.

**DB connectivity.** Run `SELECT 1` in a `try/except`; `db_ok` is `true` on success and
`false` on any exception. A failed probe must not raise a 500.

## 4. `GET /ops/jobs`

Returns `{"jobs": [...]}`. One entry per live job from
`request.app.state.scheduler.get_jobs()`. When the scheduler is `None` (disabled, or the
lifespan did not run), return `{"jobs": []}`.

| Field | Type | Source |
| --- | --- | --- |
| `id` | `str` | `job.id` |
| `trigger` | `str` | `str(job.trigger)` |
| `next_run_time` | `str \| null` | `job.next_run_time.isoformat()` or `null` |
| `pending` | `bool` | `job.pending` |
| `last_run` | `object \| null` | latest matching `ingestion_runs` row |

`last_run`, when present, is `{"status": str, "finished_at": str | null,
"records_upserted": int, "error": str | null}`. It is `null` when no matching row exists.

**Job id to run-key mapping.** Scheduler job ids and persisted `ingestion_runs.job` strings
do not line up one-to-one. The scheduler ids are `sync_odds`, `settle_results`, `prune_odds`,
`ledger_update`, `ml_predict`, `ml_retrain` (`app/scheduler.py:24-63`,
`app/ml/jobs.py:259-276`). The persisted job strings are `sync_fixtures`, `sync_odds`,
`settle_results_hkjc`, `settle_results_fallback`, `manual_review`, `backfill_history`,
`ml_predict`, `ml_retrain`, `ledger_update`. The route uses an explicit mapping and picks the
latest row (by `started_at` descending) across the mapped keys:

| Scheduler job id | `ingestion_runs.job` keys |
| --- | --- |
| `sync_odds` | `sync_odds` |
| `settle_results` | `settle_results_hkjc`, `settle_results_fallback` |
| `prune_odds` | (none) |
| `ledger_update` | `ledger_update` |
| `ml_predict` | `ml_predict` |
| `ml_retrain` | `ml_retrain` |

`prune_odds` will always show `last_run: null`: it never calls `track_run`, so it has no
persisted row. This is expected, not a bug. `sync_fixtures`, `manual_review`, and
`backfill_history` have no scheduler job and therefore never appear in `/ops/jobs`; they are
visible in `/ops/runs`.

## 5. `GET /ops/runs`

Returns `{"runs": [...]}`, the most recent `ingestion_runs` rows ordered by `started_at`
descending (newest first). `limit` defaults to 50 and is clamped to `[1, 200]` in the handler
(a plain `int` query param, not a `Query(ge=..., le=...)` constraint, so an out-of-range value
is clamped rather than rejected with 422).

| Field | Type |
| --- | --- |
| `id` | `int` |
| `job` | `str` |
| `started_at` | `str` |
| `finished_at` | `str \| null` |
| `status` | `str` (`running` / `success` / `failed` / `flagged`) |
| `records_upserted` | `int` |
| `error` | `str \| null` |

## 6. `GET /ops/logs`

Returns `{"logs": [...]}`, newest first (most recent entry at index 0). `limit` defaults to
100 and is clamped to `[1, 500]`. `level` is optional and is a **minimum severity** filter:
`DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` (case-insensitive). When omitted, all
buffered records are returned. An unrecognized `level` value returns 422.

| Field | Type |
| --- | --- |
| `time` | `str` (ISO 8601 UTC) |
| `level` | `str` |
| `logger` | `str` |
| `message` | `str` |

**Ring buffer mechanics.** A new module `app/log_buffer.py` owns a module-level
`collections.deque(maxlen=500)` of small records (`time`, `level`, `logger`, `message`) and a
`RingBufferHandler(logging.Handler)`. `configure_logging` (`app/config.py:75-85`) calls
`log_buffer.install(level)` after `basicConfig`, so the buffer captures from process start.
`install` is idempotent: if a `RingBufferHandler` is already attached it only updates the
level, so repeated `create_app` calls (as in tests) do not double-record.

**Thread safety.** `logging.Handler.handle` already serializes `emit` under the handler lock,
but the deque is also read from request threads. `app/log_buffer.py` guards both `emit`
(append) and `snapshot` (read) with one `threading.Lock`, and `snapshot` copies the deque
(`list(...)`) before any serialization, so a request never iterates a deque that a logging
thread is mutating.

**Uvicorn caveat.** Uvicorn's default logging config sets `propagate=False` on the
`uvicorn`, `uvicorn.error`, and `uvicorn.access` loggers, so HTTP access lines never reach a
root-logger handler. `install` therefore attaches the same handler to the root logger **and**
explicitly to `logging.getLogger("uvicorn.access")` and `logging.getLogger("uvicorn.error")`.
Without this, `/ops/logs` would show app logs but no request lines.

**Self-traffic is not buffered.** Access lines for `/health` and `/ops/*` are deliberately
skipped: the container healthcheck polls `/health` every 30s, which would otherwise evict all
real logs within hours.

**Known limitation.** The buffer is in-memory and per-process. It is lost on restart, and
after `docker compose restart app` `/ops/logs` is empty until new lines are emitted. This is
accepted: the durable log remains `docker compose logs app` (json-file driver, `max-size 10m`,
`max-file 3`, `docker-compose.yml:19-23`). No log file and no log volume are added.

## 7. `GET /ops/data`

One DB session, a bounded set of aggregate statements (not a single SQL statement). Returns:

| Field | Type | Content |
| --- | --- | --- |
| `table_counts` | `object` | `COUNT(*)` for `leagues`, `seasons`, `teams`, `matches`, `odds_snapshots`, `results`, `predictions`, `match_features`, `model_versions`, `ledger_bets`, `ingestion_runs` |
| `odds` | `object` | `total` (int), `last_captured_at` (str or null), `by_source_type` (list) |
| `match_features` | `object` | `count` (int), `max_built_at` (str or null) |
| `results` | `object` | `total`, `confirmed`, `payout_confirmed` (ints), `max_confirmed_at` (str or null) |
| `model_versions` | `list` | one entry per row (see below) |
| `alembic_revision` | `str \| null` | `SELECT version_num FROM alembic_version` |
| `last_arrived` | `object` | `odds_captured_at`, `features_built_at`, `results_confirmed_at`, `model_created_at`, `model_promoted_at` (each str or null) |

`odds.by_source_type` is one entry per `(source, odds_type, inplay)` group:
`{"source": str, "odds_type": str, "inplay": bool, "count": int, "max_captured_at": str | null}`,
grouped over `odds_snapshots`.

`model_versions` entries are
`{"id": int, "target": str, "algorithm": str, "status": str, "params": object,
"metrics": object, "artifact_path": str, "created_at": str, "promoted_at": str | null}`.
`params` is included here (it is `{"num_trees": int}` only, written at
`app/ml/jobs.py:154` and `app/ml/jobs.py:178`) because `GET /models` deliberately omits it.
Adding `params` to the existing `ModelOut` schema would be a breaking change to a live
contract, so it lives in `/ops/data` instead.

**Accepted cost.** The heaviest statement is `COUNT(*)` on `odds_snapshots`, which is a
sequential scan. The table is bounded by the 120-day retention and the daily compaction
(`prune_odds`), and this endpoint is not on the hot path, so the cost is accepted. No new
indexes are added. The endpoint is intended to be polled by a dashboard on the order of once
per minute, not per request.

## 8. Security and non-goals

- **No auth in the app.** Cloudflare Access (Zero Trust) remains the only gate. The compose
  `app` port is bound to `127.0.0.1:8000` (`docker-compose.yml:58`), so `/ops/*` is reachable
  from inside the compose network and from the host loopback **without** Access. Internal
  compose calls (the healthcheck, other containers) bypass Access by design. `/ops/*` must
  never be published beyond the tunnel.
- **No writes.** Every route is GET and read-only. No route mutates any table.
- **No new volumes.** No log volume, no extra mount. The only volume stays
  `artifacts:/app/artifacts`.
- **No `docker.socket`.** The app never talks to the Docker daemon.
- **No schema or migration changes.** No new table, no new column, no new revision.
- **No secrets.** No route returns `DATABASE_URL`, `POSTGRES_PASSWORD`, `TUNNEL_TOKEN`, or any
  environment value other than the non-secret `GIT_SHA`.
- **No counters.** No API-call counts, no error counters, no latency histograms. The only
  per-run number exposed is `ingestion_runs.records_upserted`.
- **Additive only.** The existing nine routes and their response schemas are unchanged. The
  new router is included alongside the existing one; nothing in `app/api/routes.py` or
  `app/api/schemas.py` changes.

## 9. Tests (TDD, each must fail before the implementation)

New file `tests/test_ops.py`, following the existing pattern in `tests/test_api.py` (a
`sqlite+aiosqlite` `Database`, `create_app(settings=Settings(_env_file=None,
enable_scheduler=False), db=db)`, `httpx.ASGITransport`).

1. **Ring buffer captures.** Emit a log record through a logger, then `GET /ops/logs` returns
   it with the right `level`, `logger`, and `message`.
2. **Level filter.** With records at `INFO` and `ERROR` buffered, `GET /ops/logs?level=ERROR`
   returns only the `ERROR` record; `?level=INFO` returns both.
3. **Logs limit clamp.** `GET /ops/logs?limit=9999` returns at most 500 entries;
   `?limit=0` returns at least one (clamped to 1).
4. **Jobs merge.** With a fake scheduler exposing one job and a matching `ingestion_runs` row,
   `GET /ops/jobs` returns that job with `last_run` populated from the row.
5. **Never-tracked job.** A job whose id maps to no run keys (for example `prune_odds`) shows
   `last_run: null`.
6. **No scheduler.** With `app.state.scheduler` absent, `GET /ops/jobs` returns
   `{"jobs": []}` and does not raise.
7. **Runs limit clamp.** `GET /ops/runs?limit=9999` returns at most 200 rows; `?limit=0`
   returns at least one.
8. **Data keys present.** `GET /ops/data` returns all top-level keys (`table_counts`, `odds`,
   `match_features`, `results`, `model_versions`, `alembic_revision`, `last_arrived`) and
   `model_versions` entries include `params`.
9. **Existing routes unaffected.** `GET /health` still returns `{"status": "ok"}` and the
   existing nine routes still respond as before.

Gate commands (both must pass):

```bash
uv run pytest -q
uv run ruff check .
```

## 10. Acceptance

On the host, after building with the SHA baked in and starting the stack:

```bash
GIT_SHA=$(git rev-parse --short HEAD) docker compose build
docker compose up -d
```

Version and SHA sources (fresh `run` containers, so the ring buffer is empty here by design):

```bash
docker compose run --rm app python -c "import tomllib,pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])"
docker compose run --rm app python -c "import os; print(os.environ.get('GIT_SHA','unknown'))"
```

The five endpoints (host loopback, bypassing Access):

```bash
curl -s 127.0.0.1:8000/ops/status | python -m json.tool
curl -s 127.0.0.1:8000/ops/jobs | python -m json.tool
curl -s "127.0.0.1:8000/ops/runs?limit=5" | python -m json.tool
curl -s "127.0.0.1:8000/ops/logs?limit=20&level=WARNING" | python -m json.tool
curl -s 127.0.0.1:8000/ops/data | python -m json.tool
```

Cross-check the alembic revision against the database:

```bash
docker compose exec postgres psql -U football -d football -c "select version_num from alembic_version;"
```

Expected observable output after deploy:

- `/ops/status`: `git_sha` equals the SHA passed to `docker compose build`; `app_version` is
  `0.1.0`; `alembic_revision` is `0003_ledger_bets` and matches the `psql` output; `db_ok` is
  `true`; `scheduler_enabled` is `true`; `uptime_seconds` grows between two calls.
- `/ops/jobs`: lists the live jobs (`sync_odds`, `settle_results`, `prune_odds`,
  `ledger_update`, plus `ml_predict` and `ml_retrain` when `ML_ENABLE=true`); `prune_odds`
  shows `last_run: null`; `sync_odds` and `ledger_update` show a `last_run` once they have run.
- `/ops/runs?limit=5`: at most five rows, newest first, with `status` in
  `running`/`success`/`failed`/`flagged`.
- `/ops/logs?limit=20&level=WARNING`: only `WARNING` and above, newest first, including
  `uvicorn.access` lines once requests have been served.
- `/ops/data`: `table_counts` has all eleven keys; `odds.by_source_type` shows the
  `(source, odds_type, inplay)` groups; `model_versions` entries include `params`;
  `last_arrived` timestamps are non-null once data exists.
