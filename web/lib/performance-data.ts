import "server-only";

import {
  getBetSummary,
  getBets,
  getClvSummary,
  getEquityCurve,
  getModels,
  getPredictions,
  getResults,
} from "./api";
import { newestPageOffset, sortBetsNewestFirst, type BetsWindow } from "./bets-window";
import { getOpsData, getOpsJobs, getOpsRuns } from "./ops";
import { PREDICTIONS_PAGE_SIZE } from "./predictions-window";
import { RESULTS_PAGE_SIZE } from "./results-window";
import type {
  BetSummary,
  ClvSummary,
  EquityPoint,
  LedgerBook,
  ModelVersion,
  OpsData,
  OpsJob,
  OpsRun,
  Prediction,
  Result,
} from "./types";

// The API's default page size is 50; the performance views request a larger page. `/bets`
// is ordered oldest-first, so the newest bets are the tail of the list: the bets fetch
// uses `/bets/summary.n_bets` to compute the offset of the newest page. `/predictions` is
// ordered earliest-first with no total-count endpoint, so its window is the first page.
// `/results` is ordered newest-first, so its window is the newest page. Every page size is
// stated on screen.
export const BETS_PAGE_SIZE = 200;
export const RUNS_PAGE_SIZE = 200;

export interface PerformanceData {
  now: Date;
  book: LedgerBook;
  summary: BetSummary | null;
  bets: BetsWindow | null;
  equity: EquityPoint[] | null;
  predictions: Prediction[] | null;
  results: Result[] | null;
  jobs: OpsJob[] | null;
  runs: OpsRun[] | null;
  data: OpsData | null;
  models: ModelVersion[] | null;
  clv: ClvSummary | null;
}

/**
 * Fetch every source the performance tab needs, degrading gracefully: a failed fetch
 * becomes `null` and the section renders an explicit unavailable state. Never throws, so
 * the production build succeeds with the API down.
 */
export async function loadPerformanceData(
  book: LedgerBook = "production",
): Promise<PerformanceData> {
  const now = new Date();
  const [summary, equity, predictions, results, jobs, runs, data, models, clv] =
    await Promise.all([
      getBetSummary(book),
      getEquityCurve(book),
      getPredictions(PREDICTIONS_PAGE_SIZE, false),
      getResults(RESULTS_PAGE_SIZE),
      getOpsJobs(),
      getOpsRuns(RUNS_PAGE_SIZE),
      getOpsData(),
      getModels(),
      getClvSummary("hkjc", book),
    ]);

  const bets = await loadBetsWindow(summary.ok ? summary.data.n_bets : null, book);

  return {
    now,
    book,
    summary: summary.ok ? summary.data : null,
    bets,
    equity: equity.ok ? equity.data : null,
    predictions: predictions.ok ? predictions.data : null,
    results: results.ok ? results.data : null,
    jobs: jobs.ok ? jobs.data.jobs : null,
    runs: runs.ok ? runs.data.runs : null,
    data: data.ok ? data.data : null,
    models: models.ok ? models.data : null,
    clv: clv.ok ? clv.data : null,
  };
}

/**
 * Fetch the newest page of bets. With the summary total known, the offset is the tail of
 * the ascending list; without it the newest page cannot be located, so the first (oldest)
 * page is fetched and the window is labelled as such. A failed /bets fetch is `null`.
 */
async function loadBetsWindow(
  nBets: number | null,
  book: LedgerBook,
): Promise<BetsWindow | null> {
  const offset = nBets === null ? 0 : newestPageOffset(nBets, BETS_PAGE_SIZE);
  const result = await getBets(BETS_PAGE_SIZE, offset, book);
  if (!result.ok) return null;
  return {
    rows: sortBetsNewestFirst(result.data),
    total: nBets,
    newestFirst: nBets !== null,
  };
}
