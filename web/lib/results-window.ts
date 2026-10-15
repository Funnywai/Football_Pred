// The window of results the performance tab actually fetched. `/results` orders by
// Match.kickoff_time descending, so the first page IS the newest page: newer rows cannot
// fall outside the window, older ones can. There is no total-count endpoint, so a full
// page is never stated as a total. Pure and free of `server-only`.

export const RESULTS_PAGE_SIZE = 200;

/**
 * "the newest 200 results by kickoff time (newest first); newer results cannot fall
 * outside this window, older ones can" | "all 54 results by kickoff time (newest first)".
 */
export function resultsWindowPhrase(fetched: number, pageSize: number): string {
  const base = `${fetched} results by kickoff time (newest first)`;
  if (fetched < pageSize) return `all ${base}`;
  return `the newest ${base}; newer results cannot fall outside this window, older ones can`;
}
