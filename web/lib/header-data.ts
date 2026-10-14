import "server-only";

import { getBetSummary, getModels } from "./api";
import { buildHeaderData, type HeaderData } from "./header-model";
import { getOpsData, getOpsJobs, getOpsRuns, getOpsStatus } from "./ops";

/**
 * Fetch every source the shared header needs, in parallel, and degrade gracefully: a
 * failed fetch becomes `null` and the header renders an explicit unavailable/stale state.
 * Never throws, so the production build succeeds with the API down.
 */
export async function loadHeaderData(): Promise<HeaderData> {
  const now = new Date();
  const [summary, status, jobs, runs, data, models] = await Promise.all([
    getBetSummary(),
    getOpsStatus(),
    getOpsJobs(),
    getOpsRuns(50),
    getOpsData(),
    getModels(),
  ]);

  return buildHeaderData({
    summary: summary.ok ? summary.data : null,
    status: status.ok ? status.data : null,
    jobs: jobs.ok ? jobs.data.jobs : null,
    runs: runs.ok ? runs.data.runs : null,
    data: data.ok ? data.data : null,
    models: models.ok ? models.data : null,
    now,
  });
}
