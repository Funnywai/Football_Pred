// Ingestion run derivation for the runs timeline. Statuses are the four the recorder
// writes (app/services/runs.py): running, success, failed, flagged.

import { JOB_STAGE } from "./header-model";
import type { OpsRun } from "./types";

export type RunStatusKind = "running" | "success" | "failed" | "flagged" | "unknown";

export function runStatusKind(status: string): RunStatusKind {
  switch (status) {
    case "running":
      return "running";
    case "success":
      return "success";
    case "failed":
      return "failed";
    case "flagged":
      return "flagged";
    default:
      return "unknown";
  }
}

/** Map a run's job to its pipeline stage; tracked variants (settle_results_hkjc) match by prefix. */
export function runStage(job: string): string {
  const exact = JOB_STAGE[job];
  if (exact !== undefined) return exact;
  const prefix = Object.keys(JOB_STAGE).find((key) => job.startsWith(`${key}_`));
  return prefix === undefined ? job : (JOB_STAGE[prefix] ?? job);
}

/** Honest window label: a truncated tail must never read as "all runs". */
export function runsWindowLabel(runs: OpsRun[], total: number | null, limit: number): string {
  const shown = runs.length;
  if (total === null) {
    return `showing the newest ${shown} runs (API max limit ${limit}; total unavailable)`;
  }
  if (total > shown) {
    return `showing the newest ${shown} of ${total} runs (API max limit ${limit})`;
  }
  return `all ${total} run${total === 1 ? "" : "s"} (API max limit ${limit})`;
}
