import "server-only";

import { getBetSummary, getBets, getEquityCurve, getModels, getPredictions } from "./api";
import { newestPageOffset, sortBetsNewestFirst, type BetsWindow } from "./bets-window";
import { getOpsData, getOpsJobs, getOpsRuns } from "./ops";
import type {
  BetSummary,
  EquityPoint,
  ModelVersion,
  OpsData,
  OpsJob,
  OpsRun,
  Prediction,
} from "./types";

// The API's default page size is 50; the performance views request a larger page. `/bets`
// is ordered oldest-first, so the newest bets are the tail of the list: the bets fetch
// uses `/bets/summary.n_bets` to compute the offset of the newest page. The page size is
// stated on screen.
export const BETS_PAGE_SIZE = 200;
export const PREDICTIONS_PAGE_SIZE = 200;
export const RUNS_PAGE_SIZE = 200;

export interface PerformanceData {
  now: Date;
  summary: BetSummary | null;
  bets: BetsWindow | null;
  equity: EquityPoint[] | null;
  predictions: Prediction[] | null;
  jobs: OpsJob[] | null;
  runs: OpsRun[] | null;
  data: OpsData | null;
  models: ModelVersion[] | null;
}

/**
 * Fetch every source the performance tab needs, degrading gracefully: a failed fetch
 * becomes `null` and the section renders an explicit unavailable state. Never throws, so
 * the production build succeeds with the API down.
 */
export async function loadPerformanceData(): Promise<PerformanceData> {
  const now = new Date();
  const [summary, equity, predictions, jobs, runs, data, models] = await Promise.all([
    getBetSummary(),
    getEquityCurve(),
    getPredictions(PREDICTIONS_PAGE_SIZE, false),
    getOpsJobs(),
    getOpsRuns(RUNS_PAGE_SIZE),
    getOpsData(),
    getModels(),
  ]);

  const bets = await loadBetsWindow(summary.ok ? summary.data.n_bets : null);

  return {
    now,
    summary: summary.ok ? summary.data : null,
    bets,
    equity: equity.ok ? equity.data : null,
    predictions: predictions.ok ? predictions.data : null,
    jobs: jobs.ok ? jobs.data.jobs : null,
    runs: runs.ok ? runs.data.runs : null,
    data: data.ok ? data.data : null,
    models: models.ok ? models.data : null,
  };
}

/**
 * Fetch the newest page of bets. With the summary total known, the offset is the tail of
 * the ascending list; without it the newest page cannot be located, so the first (oldest)
 * page is fetched and the window is labelled as such. A failed /bets fetch is `null`.
 */
async function loadBetsWindow(nBets: number | null): Promise<BetsWindow | null> {
  const offset = nBets === null ? 0 : newestPageOffset(nBets, BETS_PAGE_SIZE);
  const result = await getBets(BETS_PAGE_SIZE, offset);
  if (!result.ok) return null;
  return {
    rows: sortBetsNewestFirst(result.data),
    total: nBets,
    newestFirst: nBets !== null,
  };
}
