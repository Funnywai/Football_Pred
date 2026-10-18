// Matches x predictions: joins /predictions to /bets in memory on (match_id, target,
// outcome, model_version_id) — the same key the ledger and signal-vs-execution join use.
// `/predictions` is fetched with champion_only=false, so the same match/outcome appears
// once per model version; the version is part of the key so a bet only marks its own
// version's row. The API has no join endpoint. The ledger places at most one bet per key
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
    const key = joinKey(bet.match_id, bet.target, bet.outcome, bet.model_version_id);
    const current = index.get(key);
    if (current === undefined || placedAtMs(bet) >= placedAtMs(current)) {
      index.set(key, bet);
    }
  }

  const rows = predictions.map((prediction) => ({
    prediction,
    bet:
      index.get(
        joinKey(
          prediction.match_id,
          prediction.target,
          prediction.outcome,
          prediction.model_version_id,
        ),
      ) ?? null,
  }));
  return rows.sort(byKickoffDesc);
}

function joinKey(
  matchId: number,
  target: string,
  outcome: string,
  modelVersionId: number,
): string {
  return `${matchId}|${target}|${outcome}|${modelVersionId}`;
}

function placedAtMs(bet: Bet): number {
  const parsed = Date.parse(bet.placed_at);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function kickoffMs(prediction: Prediction): number {
  const parsed = Date.parse(prediction.kickoff_time);
  return Number.isNaN(parsed) ? 0 : parsed;
}

const OUTCOME_RANK: Record<string, number> = { H: 0, D: 1, A: 2 };

function outcomeRank(outcome: string): number {
  return OUTCOME_RANK[outcome] ?? 3;
}

function byKickoffDesc(a: PredictionBetRow, b: PredictionBetRow): number {
  const at = kickoffMs(a.prediction);
  const bt = kickoffMs(b.prediction);
  if (at !== bt) return bt - at;
  const match = a.prediction.match_id - b.prediction.match_id;
  if (match !== 0) return match;
  const target = a.prediction.target.localeCompare(b.prediction.target);
  if (target !== 0) return target;
  const outcome = outcomeRank(a.prediction.outcome) - outcomeRank(b.prediction.outcome);
  if (outcome !== 0) return outcome;
  const version = a.prediction.model_version_id - b.prediction.model_version_id;
  if (version !== 0) return version;
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
  const query = base.query?.trim();
  const filtered = query !== undefined && query !== "";
  if (betsWindowTruncated) {
    // The clause after the semicolon is byte-identical to the pre-change truncation wording (the
    // unfiltered assertions at matches-predictions.test.tsx:123 and :150 must keep passing). When a
    // query is active the counts come from the filtered set, so the sentence must name that base
    // (spec section 4.2/4.3) - otherwise it reads as a claim about the whole window.
    const lead = filtered
      ? `of the ${matched + unmatched} rows matching "${query}" in this window, ${matched} matched a placed bet in the fetched bets window`
      : `${matched} matched a placed bet in the fetched bets window`;
    return `${lead}; ${unmatched} ${verb} no match there — a bet outside the fetched window would not be seen.`;
  }
  const tally =
    query === undefined || query === ""
      ? `${unmatched} of the ${base.fetched} fetched rows`
      : `of the ${matched + unmatched} rows matching "${query}" in this window, ${unmatched}`;
  return `${tally} ${verb} no place in the ledger; ${matched} matched a placed bet.`;
}
