// Pure derivation of the shared header's view model from the real API fields. Kept free
// of `server-only` so it is unit-testable; the fetching lives in lib/header-data.ts.

import { formatRelative } from "./format";
import {
  FRESHNESS_THRESHOLDS,
  heartbeatFrom,
  statusForAge,
  type FreshnessStatus,
  type HeartbeatResult,
} from "./freshness";
import type { BetSummary, ModelVersion, OpsData, OpsJob, OpsRun, OpsStatus } from "./types";

export interface HeaderMoney {
  bankroll: number;
  realizedProfit: number;
  openStakes: number;
}

export interface HeaderBuild {
  gitSha: string;
  appVersion: string;
  championTarget: string | null;
  championStatus: string | null;
}

export interface HeaderFreshness {
  status: FreshnessStatus;
  label: string;
  detail: string;
}

export interface HeaderThinking {
  active: boolean;
  stage: string | null;
  label: string;
}

export interface HeaderData {
  apiReachable: boolean;
  money: HeaderMoney | null;
  build: HeaderBuild | null;
  heartbeat: HeartbeatResult;
  freshness: HeaderFreshness;
  thinking: HeaderThinking;
}

// Scheduler job id -> pipeline stage (app/api/ops.py JOB_RUN_KEYS + app/scheduler.py).
export const JOB_STAGE: Record<string, string> = {
  sync_odds: "INGEST",
  prune_odds: "INGEST",
  ml_predict: "PREDICT",
  ledger_update: "BET",
  settle_results: "SETTLE",
  ml_retrain: "RETRAIN",
};

/** The active stage is the newest run still marked `running`; otherwise the system is idle. */
export function thinkingFrom(runs: OpsRun[]): HeaderThinking {
  const running = runs.find((run) => run.status === "running");
  if (running === undefined) {
    return { active: false, stage: null, label: "idle" };
  }
  const stage = JOB_STAGE[running.job] ?? running.job;
  return { active: true, stage, label: `thinking · ${stage}` };
}

/** Worst-of the four arrival streams; detail names the freshest one. */
export function freshnessFrom(data: OpsData, runs: OpsRun[], now: Date): HeaderFreshness {
  const newestPredict =
    runs
      .filter((run) => run.job === "ml_predict")
      .map((run) => run.finished_at)
      .filter((value): value is string => value !== null)
      .sort()
      .at(-1) ?? null;

  const arrivals = [
    { label: "odds", iso: data.last_arrived.odds_captured_at, thresholds: FRESHNESS_THRESHOLDS.odds },
    {
      label: "features",
      iso: data.last_arrived.features_built_at,
      thresholds: FRESHNESS_THRESHOLDS.features,
    },
    {
      label: "results",
      iso: data.last_arrived.results_confirmed_at,
      thresholds: FRESHNESS_THRESHOLDS.results,
    },
    { label: "predictions", iso: newestPredict, thresholds: FRESHNESS_THRESHOLDS.predictions },
  ];

  const statuses = arrivals.map((arrival) =>
    statusForAge(arrival.iso, arrival.thresholds, now),
  );
  const status: FreshnessStatus = statuses.includes("stale")
    ? "stale"
    : statuses.includes("degraded")
      ? "degraded"
      : "healthy";

  const newest = arrivals
    .filter((arrival): arrival is typeof arrival & { iso: string } => arrival.iso !== null)
    .sort((a, b) => Date.parse(b.iso) - Date.parse(a.iso))[0];

  return {
    status,
    label: status,
    detail: newest === undefined ? "no data yet" : `${newest.label} ${formatRelative(newest.iso, now)}`,
  };
}

export interface HeaderInputs {
  summary: BetSummary | null;
  status: OpsStatus | null;
  jobs: OpsJob[] | null;
  runs: OpsRun[] | null;
  data: OpsData | null;
  models: ModelVersion[] | null;
  now: Date;
}

export function buildHeaderData(inputs: HeaderInputs): HeaderData {
  const { summary, status, jobs, runs, data, models, now } = inputs;

  const apiReachable =
    summary !== null ||
    status !== null ||
    jobs !== null ||
    runs !== null ||
    data !== null ||
    models !== null;

  const money =
    summary === null
      ? null
      : {
          bankroll: summary.bankroll,
          realizedProfit: summary.realized_profit,
          openStakes: summary.open_stakes,
        };

  const champion = models?.find((model) => model.status === "champion") ?? null;
  const build =
    status === null
      ? null
      : {
          gitSha: status.git_sha,
          appVersion: status.app_version,
          championTarget: champion?.target ?? null,
          championStatus: champion?.status ?? null,
        };

  const heartbeat: HeartbeatResult =
    jobs !== null && runs !== null
      ? heartbeatFrom({ jobs, runs, now })
      : { status: "stale", label: "unavailable", detail: "ops surface unreachable" };

  const freshness: HeaderFreshness =
    data !== null
      ? freshnessFrom(data, runs ?? [], now)
      : { status: "stale", label: "unavailable", detail: "ops surface unreachable" };

  return {
    apiReachable,
    money,
    build,
    heartbeat,
    freshness,
    thinking: thinkingFrom(runs ?? []),
  };
}
