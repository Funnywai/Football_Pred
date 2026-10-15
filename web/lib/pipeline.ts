// Six-stage AI pipeline derivation. Every field comes from the real /ops/* surface:
// /ops/jobs (each job's normalised last_run and next_run_time), /ops/runs (stuck-running
// detection), and /ops/data (the features-built timestamp). No heartbeat or status field
// is invented.
//
// The API layer already normalises the settle_results job-id mismatch, so the SETTLE
// stage reads job.last_run directly; this module never rebuilds that mapping.

import { formatRelative } from "./format";
import { ageMs, HOUR, MINUTE, type AgeThresholds } from "./freshness";
import type { OpsData, OpsJob, OpsRun } from "./types";

const DAY = 24 * HOUR;
const STUCK_RUN_MS = 30 * MINUTE;
// A scheduled job whose next_run_time is past by more than this grace period did not
// fire: the scheduler is stalled, which must not read as healthy.
const OVERDUE_GRACE_MS = 5 * MINUTE;

export type StageStatus =
  | "active"
  | "success"
  | "failed"
  | "ageing"
  | "stale"
  | "overdue"
  | "never-tracked"
  | "unavailable";

export interface PipelineStage {
  id: string;
  label: string;
  status: StageStatus;
  lastActionAt: string | null;
  detail: string;
}

// Per-stage ageing windows, derived from each job's real cadence (README scheduler table).
export const STAGE_THRESHOLDS: Record<string, AgeThresholds> = {
  INGEST: { degradedMs: 30 * MINUTE, staleMs: 3 * HOUR },
  FEATURES: { degradedMs: 2 * HOUR, staleMs: 6 * HOUR },
  PREDICT: { degradedMs: 2 * HOUR, staleMs: 6 * HOUR },
  BET: { degradedMs: 2 * HOUR, staleMs: 6 * HOUR },
  SETTLE: { degradedMs: 1 * HOUR, staleMs: 6 * HOUR },
  RETRAIN: { degradedMs: 8 * DAY, staleMs: 15 * DAY },
};

interface StageDef {
  id: string;
  label: string;
  jobId: string | null;
}

const STAGE_DEFS: StageDef[] = [
  { id: "INGEST", label: "INGEST", jobId: "sync_odds" },
  { id: "FEATURES", label: "FEATURES", jobId: null },
  { id: "PREDICT", label: "PREDICT", jobId: "ml_predict" },
  { id: "BET", label: "BET", jobId: "ledger_update" },
  { id: "SETTLE", label: "SETTLE", jobId: "settle_results" },
  { id: "RETRAIN", label: "RETRAIN", jobId: "ml_retrain" },
];

export interface PipelineInput {
  jobs: OpsJob[] | null;
  runs: OpsRun[] | null;
  data: OpsData | null;
  now: Date;
}

export function pipelineStages({ jobs, runs, data, now }: PipelineInput): PipelineStage[] {
  return STAGE_DEFS.map((def) => deriveStage(def, jobs, runs ?? [], data, now));
}

function deriveStage(
  def: StageDef,
  jobs: OpsJob[] | null,
  runs: OpsRun[],
  data: OpsData | null,
  now: Date,
): PipelineStage {
  const thresholds = STAGE_THRESHOLDS[def.id] ?? { degradedMs: 2 * HOUR, staleMs: 6 * HOUR };
  if (def.jobId === null) {
    if (data === null) {
      return stage(def, "unavailable", null, "the /ops/data source is unavailable");
    }
    return fromTimestamp(def, data.last_arrived.features_built_at, thresholds, now);
  }
  if (jobs === null) {
    return stage(def, "unavailable", null, "the /ops/jobs source is unavailable");
  }
  const job = jobs.find((candidate) => candidate.id === def.jobId) ?? null;
  return fromJob(def, job, runs, thresholds, now);
}

function fromTimestamp(
  def: StageDef,
  iso: string | null,
  thresholds: AgeThresholds,
  now: Date,
): PipelineStage {
  if (iso === null) {
    return stage(def, "never-tracked", null, "no features built yet");
  }
  const age = ageMs(iso, now);
  if (age === null) return stage(def, "never-tracked", iso, "no features built yet");
  if (age >= thresholds.staleMs) return stage(def, "stale", iso, "features are stale");
  if (age >= thresholds.degradedMs) return stage(def, "ageing", iso, "features are ageing");
  return stage(def, "success", iso, "features built");
}

function fromJob(
  def: StageDef,
  job: OpsJob | null,
  runs: OpsRun[],
  thresholds: AgeThresholds,
  now: Date,
): PipelineStage {
  if (job === null) {
    return stage(def, "never-tracked", null, "no run recorded");
  }
  const lastRun = job.last_run;
  if (lastRun !== null) {
    const lastActionAt = lastRun.finished_at;
    if (lastRun.status === "running") {
      const stuck = runs.some(
        (run) => matchesStage(run, def) && run.status === "running" && isStuck(run, now),
      );
      return stuck
        ? stage(def, "failed", lastActionAt, "a run is stuck")
        : stage(def, "active", lastActionAt, "running now");
    }
    if (lastRun.status === "failed") {
      return stage(def, "failed", lastActionAt, lastRun.error ?? "last run failed");
    }
    if (lastRun.status === "flagged") {
      return stage(def, "ageing", lastActionAt, "flagged for review");
    }
  }
  if (isOverdue(job.next_run_time, now)) {
    return stage(
      def,
      "overdue",
      lastRun?.finished_at ?? null,
      `next run was due ${formatRelative(job.next_run_time, now)}`,
    );
  }
  if (lastRun === null) {
    return stage(def, "never-tracked", null, "no run recorded");
  }
  const age = ageMs(lastRun.finished_at, now);
  if (age === null) return stage(def, "never-tracked", lastRun.finished_at, "no finish time");
  if (age >= thresholds.staleMs) return stage(def, "stale", lastRun.finished_at, "last run is stale");
  if (age >= thresholds.degradedMs) return stage(def, "ageing", lastRun.finished_at, "last run is ageing");
  return stage(def, "success", lastRun.finished_at, "last run succeeded");
}

// A job whose scheduled next_run_time is past by more than the grace period did not fire.
function isOverdue(nextRunTime: string | null, now: Date): boolean {
  if (nextRunTime === null) return false;
  const parsed = Date.parse(nextRunTime);
  if (Number.isNaN(parsed)) return false;
  return now.getTime() - parsed > OVERDUE_GRACE_MS;
}

// Generic run-to-stage match: a run belongs to a stage when its job id equals the stage's
// job id or is a tracked variant of it (e.g. settle_results_hkjc). This is not the API's
// JOB_RUN_KEYS dict; it is a prefix rule used only for stuck-run detection.
function matchesStage(run: OpsRun, def: StageDef): boolean {
  if (def.jobId === null) return false;
  return run.job === def.jobId || run.job.startsWith(`${def.jobId}_`);
}

function isStuck(run: OpsRun, now: Date): boolean {
  const age = ageMs(run.started_at, now);
  return age !== null && age >= STUCK_RUN_MS;
}

function stage(
  def: StageDef,
  status: StageStatus,
  lastActionAt: string | null,
  detail: string,
): PipelineStage {
  return { id: def.id, label: def.label, status, lastActionAt, detail };
}
