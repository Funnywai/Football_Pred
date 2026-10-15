import "server-only";

import { getBetSummary, getBets, getEquityCurve, getModels, getPredictions } from "./api";
import { getOpsData, getOpsJobs, getOpsRuns } from "./ops";
import type {
  Bet,
  BetSummary,
  EquityPoint,
  ModelVersion,
  OpsData,
  OpsJob,
  OpsRun,
  Prediction,
} from "./types";

// The API's default page size is 50; the performance views request a larger page so the
// tables and the win-rate derivation see the whole (small) dataset. The page size is
// stated on screen.
export const BETS_PAGE_SIZE = 200;
export const PREDICTIONS_PAGE_SIZE = 200;
export const RUNS_PAGE_SIZE = 200;

export interface PerformanceData {
  now: Date;
  summary: BetSummary | null;
  bets: Bet[] | null;
  equity: EquityPoint[] | null;
  predictions: Prediction[] | null;
  jobs: OpsJob[] | null;
  runs: OpsRun[] | null;
  data: OpsData | null;
  models: ModelVersion[] | null;
}

/**
 * Fetch every source the performance tab needs, in parallel, degrading gracefully: a
 * failed fetch becomes `null` and the section renders an explicit unavailable state.
 * Never throws, so the production build succeeds with the API down.
 */
export async function loadPerformanceData(): Promise<PerformanceData> {
  const now = new Date();
  const [summary, bets, equity, predictions, jobs, runs, data, models] = await Promise.all([
    getBetSummary(),
    getBets(BETS_PAGE_SIZE),
    getEquityCurve(),
    getPredictions(PREDICTIONS_PAGE_SIZE, false),
    getOpsJobs(),
    getOpsRuns(RUNS_PAGE_SIZE),
    getOpsData(),
    getModels(),
  ]);

  return {
    now,
    summary: summary.ok ? summary.data : null,
    bets: bets.ok ? bets.data : null,
    equity: equity.ok ? equity.data : null,
    predictions: predictions.ok ? predictions.data : null,
    jobs: jobs.ok ? jobs.data.jobs : null,
    runs: runs.ok ? runs.data.runs : null,
    data: data.ok ? data.data : null,
    models: models.ok ? models.data : null,
  };
}
