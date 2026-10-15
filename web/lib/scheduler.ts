// Scheduler table derivation. The per-job status comes from the SAME function the pipeline
// uses (lib/pipeline.ts jobStatus), so a job cannot read as healthy in one place and
// overdue in another. Thresholds follow each job's real cadence (README scheduler table).

import { HOUR, type AgeThresholds } from "./freshness";
import { STAGE_THRESHOLDS, jobStatus, type StageStatus } from "./pipeline";
import type { OpsJob, OpsRun } from "./types";

const DEFAULT_THRESHOLDS: AgeThresholds = { degradedMs: 2 * HOUR, staleMs: 6 * HOUR };

function stageThresholds(stage: string): AgeThresholds {
  return STAGE_THRESHOLDS[stage] ?? DEFAULT_THRESHOLDS;
}

export const JOB_THRESHOLDS: Record<string, AgeThresholds> = {
  sync_odds: stageThresholds("INGEST"),
  // prune_odds runs daily at 04:00 UTC and never records an ingestion run.
  prune_odds: { degradedMs: 26 * HOUR, staleMs: 50 * HOUR },
  ml_predict: stageThresholds("PREDICT"),
  ledger_update: stageThresholds("BET"),
  settle_results: stageThresholds("SETTLE"),
  ml_retrain: stageThresholds("RETRAIN"),
};

export interface SchedulerRow {
  job: OpsJob;
  status: StageStatus;
  detail: string;
}

export function schedulerRows(jobs: OpsJob[], runs: OpsRun[], now: Date): SchedulerRow[] {
  return jobs.map((job) => {
    const thresholds = JOB_THRESHOLDS[job.id] ?? DEFAULT_THRESHOLDS;
    const { status, detail } = jobStatus(job, runs, thresholds, now);
    return { job, status, detail };
  });
}
