// Freshness and heartbeat derivation. Pure functions over the real /ops/* fields only —
// no invented heartbeat timestamp. Thresholds are named constants so the UI can explain
// why a value is degraded or stale.

import type { OpsData, OpsJob, OpsRun } from "./types";

export type FreshnessStatus = "healthy" | "degraded" | "stale";

export interface AgeThresholds {
  degradedMs: number;
  staleMs: number;
}

export const MINUTE = 60_000;
export const HOUR = 60 * MINUTE;

// Odds sync runs every 600s; predict/ledger hourly; settle every 900s (see README).
export const FRESHNESS_THRESHOLDS = {
  odds: { degradedMs: 30 * MINUTE, staleMs: 3 * HOUR },
  features: { degradedMs: 2 * HOUR, staleMs: 6 * HOUR },
  results: { degradedMs: 1 * HOUR, staleMs: 6 * HOUR },
  predictions: { degradedMs: 2 * HOUR, staleMs: 6 * HOUR },
  heartbeat: { degradedMs: 30 * MINUTE, staleMs: 3 * HOUR },
} satisfies Record<string, AgeThresholds>;

const STUCK_RUN_MS = 30 * MINUTE;
const FAILURE_WINDOW_MS = 24 * HOUR;

export function ageMs(iso: string | null, now: Date): number | null {
  if (iso === null) return null;
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return null;
  return now.getTime() - parsed;
}

export function statusForAge(
  iso: string | null,
  thresholds: AgeThresholds,
  now: Date,
): FreshnessStatus {
  const age = ageMs(iso, now);
  if (age === null) return "stale";
  if (age >= thresholds.staleMs) return "stale";
  if (age >= thresholds.degradedMs) return "degraded";
  return "healthy";
}

export type FreshnessRowState =
  | FreshnessStatus
  | "never-tracked"
  | "unavailable"
  | "not-in-window";

export interface FreshnessRow {
  id: "odds" | "features" | "results" | "predictions";
  label: string;
  source: string;
  iso: string | null;
  state: FreshnessRowState;
  thresholds: AgeThresholds;
}

/** Format a threshold duration for the on-screen "degraded > 30m · stale > 3h" label. */
export function formatDuration(ms: number): string {
  const minutes = Math.round(ms / MINUTE);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

/**
 * The four arrival streams of the freshness panel. `runs` is nullable: when /ops/runs is
 * unreachable the prediction arrival cannot be derived and is marked unavailable, never
 * "never tracked" (which would claim no prediction ever ran). A fetched window that holds
 * no ml_predict run is a window miss, not a never-tracked source: the window is a
 * truncated tail, so the run may exist outside it.
 */
export function freshnessRows(data: OpsData, runs: OpsRun[] | null, now: Date): FreshnessRow[] {
  const newestPredict =
    runs === null
      ? null
      : (runs
          .filter((run) => run.job === "ml_predict")
          .map((run) => run.finished_at)
          .filter((value): value is string => value !== null)
          .sort()
          .at(-1) ?? null);

  const defs: Array<Omit<FreshnessRow, "state">> = [
    {
      id: "odds",
      label: "Odds snapshot",
      source: "/ops/data.last_arrived.odds_captured_at",
      iso: data.last_arrived.odds_captured_at,
      thresholds: FRESHNESS_THRESHOLDS.odds,
    },
    {
      id: "features",
      label: "Features",
      source: "/ops/data.last_arrived.features_built_at",
      iso: data.last_arrived.features_built_at,
      thresholds: FRESHNESS_THRESHOLDS.features,
    },
    {
      id: "results",
      label: "Confirmed result",
      source: "/ops/data.last_arrived.results_confirmed_at",
      iso: data.last_arrived.results_confirmed_at,
      thresholds: FRESHNESS_THRESHOLDS.results,
    },
    {
      id: "predictions",
      label: "Prediction",
      source: "newest ml_predict run in /ops/runs",
      iso: newestPredict,
      thresholds: FRESHNESS_THRESHOLDS.predictions,
    },
  ];

  return defs.map((def) => {
    if (def.id === "predictions") {
      if (runs === null) return { ...def, state: "unavailable" };
      if (def.iso === null) return { ...def, state: "not-in-window" };
    }
    if (def.iso === null) return { ...def, state: "never-tracked" };
    return { ...def, state: statusForAge(def.iso, def.thresholds, now) };
  });
}

export interface HeartbeatResult {
  status: FreshnessStatus;
  label: string;
  detail: string;
}

export interface HeartbeatInput {
  jobs: OpsJob[];
  runs: OpsRun[];
  now: Date;
}

/**
 * Heartbeat is derived only from fields that exist: `/ops/jobs` (job presence and
 * `next_run_time`) and `/ops/runs` (recency of the newest `finished_at`, plus any
 * `failed`/`flagged` rows and any `running` row that has been open too long).
 */
export function heartbeatFrom({ jobs, runs, now }: HeartbeatInput): HeartbeatResult {
  if (jobs.length === 0) {
    return { status: "stale", label: "stale", detail: "no scheduled jobs" };
  }

  const newestFinished =
    runs
      .map((run) => run.finished_at)
      .filter((value): value is string => value !== null)
      .sort()
      .at(-1) ?? null;

  const recentFailure = runs.some((run) => {
    if (run.status !== "failed" && run.status !== "flagged") return false;
    const age = ageMs(run.finished_at ?? run.started_at, now);
    return age !== null && age <= FAILURE_WINDOW_MS;
  });

  const stuck = runs.some((run) => {
    if (run.status !== "running") return false;
    const age = ageMs(run.started_at, now);
    return age !== null && age >= STUCK_RUN_MS;
  });

  if (recentFailure) {
    return { status: "degraded", label: "degraded", detail: "a recent run failed" };
  }
  if (stuck) {
    return { status: "degraded", label: "degraded", detail: "a run is stuck" };
  }

  const recency = statusForAge(newestFinished, FRESHNESS_THRESHOLDS.heartbeat, now);
  if (recency === "stale") {
    return { status: "stale", label: "stale", detail: "no recent run" };
  }
  if (recency === "degraded") {
    return { status: "degraded", label: "degraded", detail: "runs are ageing" };
  }
  return { status: "healthy", label: "healthy", detail: "scheduler active" };
}
