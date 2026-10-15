// Matches x predictions: joins /predictions to /bets in memory on (match_id, target,
// outcome) — the key the spec names (docs/superpowers/specs/2026-10-15-dashboard-design.md
// section 5.2f). The API has no join endpoint. The ledger places at most one bet per key
// (app/services/ledger.py skips keys already in the ledger); if a key ever carries
// several, the most recently placed bet is shown. Pure and free of `server-only`.

import type { Bet, Prediction } from "./types";

export interface PredictionBetRow {
  prediction: Prediction;
  bet: Bet | null;
}

/** One row per prediction, newest kickoff first, with the bet placed on its key if any. */
export function predictionBetRows(predictions: Prediction[], bets: Bet[]): PredictionBetRow[] {
  const index = new Map<string, Bet>();
  for (const bet of bets) {
    const key = joinKey(bet.match_id, bet.target, bet.outcome);
    const current = index.get(key);
    if (current === undefined || placedAtMs(bet) >= placedAtMs(current)) {
      index.set(key, bet);
    }
  }

  const rows = predictions.map((prediction) => ({
    prediction,
    bet: index.get(joinKey(prediction.match_id, prediction.target, prediction.outcome)) ?? null,
  }));
  return rows.sort(byKickoffDesc);
}

function joinKey(matchId: number, target: string, outcome: string): string {
  return `${matchId}|${target}|${outcome}`;
}

function placedAtMs(bet: Bet): number {
  const parsed = Date.parse(bet.placed_at);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function kickoffMs(prediction: Prediction): number {
  const parsed = Date.parse(prediction.kickoff_time);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function byKickoffDesc(a: PredictionBetRow, b: PredictionBetRow): number {
  const at = kickoffMs(a.prediction);
  const bt = kickoffMs(b.prediction);
  if (at !== bt) return bt - at;
  const target = a.prediction.target.localeCompare(b.prediction.target);
  if (target !== 0) return target;
  const outcome = a.prediction.outcome.localeCompare(b.prediction.outcome);
  if (outcome !== 0) return outcome;
  return b.prediction.id - a.prediction.id;
}

/**
 * "54 of the 54 fetched rows have no place in the ledger; 0 matched a placed bet." when the
 * fetched bets window covers the ledger; a truncated window only supports a qualified claim,
 * because a bet outside it would not be seen. With a filter active the tally names the query
 * and its base: `of the 12 rows matching "arsenal" in this window, 11 have no place in the
 * ledger; 1 matched a placed bet.`
 */
export function joinSummaryPhrase(
  matched: number,
  unmatched: number,
  betsWindowTruncated: boolean,
  base: { fetched: number; query?: string },
): string {
  const verb = unmatched === 1 ? "has" : "have";
  if (betsWindowTruncated) {
    // Byte-identical to the pre-change truncation wording: the existing assertions at
    // matches-predictions.test.tsx:123 and :150 must keep passing unchanged.
    return `${matched} matched a placed bet in the fetched bets window; ${unmatched} ${verb} no match there — a bet outside the fetched window would not be seen.`;
  }
  const query = base.query?.trim();
  const tally =
    query === undefined || query === ""
      ? `${unmatched} of the ${base.fetched} fetched rows`
      : `of the ${matched + unmatched} rows matching "${query}" in this window, ${unmatched}`;
  return `${tally} ${verb} no place in the ledger; ${matched} matched a placed bet.`;
}
