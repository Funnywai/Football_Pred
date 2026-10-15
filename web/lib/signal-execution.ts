// Signal price vs execution price. Joins /bets with /predictions on the same key the
// repo's own acceptance SQL uses (docs/superpowers/specs/2026-10-14-ledger-execution-price-design.md):
// (match_id, target, outcome, model_version_id). `ledger_bets.odds` is the execution
// price; `predictions.market_odds` is the 48h prior (signal) price.

import type { Bet, Prediction } from "./types";

export interface SignalExecutionRow {
  betId: number;
  matchId: number;
  target: string;
  outcome: string;
  modelVersionId: number;
  leagueCode: string;
  homeTeam: string;
  awayTeam: string;
  kickoffTime: string;
  signalOdds: number | null;
  executionOdds: number;
  absDiff: number | null;
  pctDiff: number | null;
  againstUs: boolean;
  matched: boolean;
}

export function signalExecutionRows(
  bets: Bet[],
  predictions: Prediction[],
): SignalExecutionRow[] {
  const index = new Map<string, Prediction>();
  for (const prediction of predictions) {
    index.set(
      joinKey(
        prediction.match_id,
        prediction.target,
        prediction.outcome,
        prediction.model_version_id,
      ),
      prediction,
    );
  }

  const rows = bets.map((bet) => {
    const prediction =
      index.get(joinKey(bet.match_id, bet.target, bet.outcome, bet.model_version_id)) ?? null;
    const signalOdds = prediction?.market_odds ?? null;
    const executionOdds = bet.odds;
    const absDiff = signalOdds === null ? null : executionOdds - signalOdds;
    const pctDiff =
      signalOdds === null || signalOdds === 0 ? null : (executionOdds - signalOdds) / signalOdds;
    return {
      betId: bet.id,
      matchId: bet.match_id,
      target: bet.target,
      outcome: bet.outcome,
      modelVersionId: bet.model_version_id,
      leagueCode: bet.league_code,
      homeTeam: bet.home_team,
      awayTeam: bet.away_team,
      kickoffTime: bet.kickoff_time,
      signalOdds,
      executionOdds,
      absDiff,
      pctDiff,
      againstUs: absDiff !== null && absDiff < 0,
      matched: prediction !== null,
    };
  });

  return rows.sort(byAbsDiffDesc);
}

function joinKey(
  matchId: number,
  target: string,
  outcome: string,
  modelVersionId: number,
): string {
  return `${matchId}|${target}|${outcome}|${modelVersionId}`;
}

function byAbsDiffDesc(a: SignalExecutionRow, b: SignalExecutionRow): number {
  const av = a.absDiff === null ? -1 : Math.abs(a.absDiff);
  const bv = b.absDiff === null ? -1 : Math.abs(b.absDiff);
  return bv - av;
}
