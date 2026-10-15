// The window of bets the performance tab actually fetched. `/bets` orders by
// (placed_at, id) ascending and has no ordering parameter, so the newest bets are the
// TAIL of the list: the server computes `offset = max(0, n_bets - pageSize)` from
// `/bets/summary.n_bets` and fetches that tail. `total` is the true ledger size when the
// summary was available; `newestFirst` is false when only the first (oldest) page could
// be fetched because the summary was unavailable. Pure and free of `server-only` so the
// components and tests can share it.

import type { Bet } from "./types";

export interface BetsWindow {
  /** Display order: newest first within the fetched window. */
  rows: Bet[];
  /** True ledger size from /bets/summary.n_bets; null when the summary was unavailable. */
  total: number | null;
  /** True when the fetched page is the newest page; false for the oldest-page fallback. */
  newestFirst: boolean;
}

/** Offset of the newest page in the ascending /bets list. Never negative. */
export function newestPageOffset(nBets: number, pageSize: number): number {
  return Math.max(0, nBets - pageSize);
}

/** Newest-first display order: placed_at descending, then id descending. */
export function sortBetsNewestFirst(bets: Bet[]): Bet[] {
  return [...bets].sort((a, b) => {
    const at = placedAtMs(a);
    const bt = placedAtMs(b);
    if (at !== bt) return bt - at;
    return b.id - a.id;
  });
}

function placedAtMs(bet: Bet): number {
  const parsed = Date.parse(bet.placed_at);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** True when the fetched rows are a subset of the ledger (the summary total is larger). */
export function isTruncated(window: BetsWindow): boolean {
  return window.total !== null && window.total > window.rows.length;
}

/**
 * "the 200 most recent of 250 bets" | "all 2 bets" | "the oldest 200 bets".
 * Never states a count as a total when it is not one.
 */
export function betsWindowPhrase(window: BetsWindow): string {
  const fetched = window.rows.length;
  if (!window.newestFirst) return `the oldest ${fetched} bets`;
  const total = window.total;
  if (total !== null && total > fetched) return `the ${fetched} most recent of ${total} bets`;
  return `all ${fetched} bets`;
}
