// The window of predictions the performance tab actually fetched. `/predictions` orders
// by (Match.kickoff_time, target, outcome) ascending and exposes no ordering parameter and
// no total-count endpoint, so the first page is the EARLIEST kickoffs and the newest page
// cannot be located by offset. Pure and free of `server-only` so the components and tests
// can share it.

export const PREDICTIONS_PAGE_SIZE = 200;

/**
 * "the first 200 champion and challenger predictions by kickoff time (earliest first);
 * the API exposes no ordering parameter, so newer fixtures may fall outside this window"
 * | "all 54 champion and challenger predictions by kickoff time (earliest first)".
 * A full page is never stated as a total.
 */
export function predictionsWindowPhrase(fetched: number, pageSize: number): string {
  const base = `${fetched} champion and challenger predictions by kickoff time (earliest first)`;
  if (fetched < pageSize) return `all ${base}`;
  return `the first ${base}; the API exposes no ordering parameter, so newer fixtures may fall outside this window`;
}
