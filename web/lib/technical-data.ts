import "server-only";

import { getModels } from "./api";
import type { LogLevel } from "./logs";
import { getOpsData, getOpsJobs, getOpsLogs, getOpsRuns, getOpsStatus } from "./ops";
import type { ModelVersion, OpsData, OpsJob, OpsLogLine, OpsRun, OpsStatus } from "./types";

// The API's /ops/logs default limit is 100 (max 500); /ops/runs default 50 (max 200).
// Both windows are stated on screen.
export const LOGS_LIMIT = 100;
export const RUNS_LIMIT = 200;

export interface TechnicalData {
  now: Date;
  status: OpsStatus | null;
  jobs: OpsJob[] | null;
  runs: OpsRun[] | null;
  logs: OpsLogLine[] | null;
  data: OpsData | null;
  models: ModelVersion[] | null;
  logLevel: LogLevel | null;
}

/**
 * Fetch every source the technical tab needs, degrading gracefully: a failed fetch becomes
 * `null` and the section renders an explicit unavailable state. Never throws, so the
 * production build succeeds with the API down.
 */
export async function loadTechnicalData(level: LogLevel | null): Promise<TechnicalData> {
  const now = new Date();
  const [status, jobs, runs, logs, data, models] = await Promise.all([
    getOpsStatus(),
    getOpsJobs(),
    getOpsRuns(RUNS_LIMIT),
    getOpsLogs(LOGS_LIMIT, level ?? undefined),
    getOpsData(),
    getModels(),
  ]);

  return {
    now,
    status: status.ok ? status.data : null,
    jobs: jobs.ok ? jobs.data.jobs : null,
    runs: runs.ok ? runs.data.runs : null,
    logs: logs.ok ? logs.data.logs : null,
    data: data.ok ? data.data : null,
    models: models.ok ? models.data : null,
    logLevel: level,
  };
}
