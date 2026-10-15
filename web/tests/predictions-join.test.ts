import { describe, expect, it } from "vitest";

import { joinSummaryPhrase, predictionBetRows } from "@/lib/predictions-join";
import type { Bet, Prediction } from "@/lib/types";

function prediction(overrides: Partial<Prediction>): Prediction {
  return {
    id: 1,
    match_id: 29164,
    target: "1x2",
    outcome: "H",
    model_version_id: 1,
    prob: 0.45,
    implied_prob: 0.4,
    edge: 0.05,
    fair_odds: 2.22,
    market_odds: 2.48,
    recommended_fraction: 0.02,
    kickoff_time: "2026-10-14T12:00:00Z",
    league_code: "EPL",
    home_team: "Arsenal",
    away_team: "Chelsea",
    ...overrides,
  };
}

function bet(overrides: Partial<Bet>): Bet {
  return {
    id: 1,
    match_id: 29164,
    target: "1x2",
    outcome: "H",
    model_version_id: 1,
    line: null,
    odds: 2.48,
    stake: 10,
    bankroll_at_place: 1000,
    edge: 0.05,
    kelly_multiplier: 0.5,
    status: "won",
    placed_at: "2026-10-14T00:00:00Z",
    settled_at: "2026-10-15T00:00:00Z",
    payout: 24.8,
    profit: 14.8,
    kickoff_time: "2026-10-14T12:00:00Z",
    league_code: "EPL",
    home_team: "Arsenal",
    away_team: "Chelsea",
    ...overrides,
  };
}

describe("predictionBetRows", () => {
  it("matches a prediction to the bet placed on the same (match_id, target, outcome)", () => {
    const rows = predictionBetRows(
      [prediction({ id: 1, match_id: 29164 })],
      [bet({ id: 7, match_id: 29164 })],
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]?.bet?.id).toBe(7);
  });

  it("leaves a prediction without a bet unmatched", () => {
    const rows = predictionBetRows(
      [prediction({ id: 1, match_id: 29164 })],
      [bet({ id: 7, match_id: 999 })],
    );
    expect(rows[0]?.bet).toBeNull();
  });

  it("does not match across outcomes of the same match", () => {
    const rows = predictionBetRows(
      [
        prediction({ id: 1, match_id: 1, outcome: "H" }),
        prediction({ id: 2, match_id: 1, outcome: "A" }),
      ],
      [bet({ id: 7, match_id: 1, outcome: "H" })],
    );
    const byPrediction = new Map(rows.map((row) => [row.prediction.id, row.bet]));
    expect(byPrediction.get(1)?.id).toBe(7);
    expect(byPrediction.get(2)).toBeNull();
  });

  it("matches every model version's prediction for the same key to the same bet", () => {
    const rows = predictionBetRows(
      [
        prediction({ id: 1, model_version_id: 1 }),
        prediction({ id: 2, model_version_id: 2 }),
      ],
      [bet({ id: 7, model_version_id: 2 })],
    );
    expect(rows.every((row) => row.bet?.id === 7)).toBe(true);
  });

  it("orders rows by kickoff descending, then target and outcome ascending", () => {
    const rows = predictionBetRows(
      [
        prediction({ id: 1, match_id: 1, kickoff_time: "2026-10-10T12:00:00Z", outcome: "H" }),
        prediction({ id: 2, match_id: 2, kickoff_time: "2026-10-12T12:00:00Z", outcome: "A" }),
        prediction({ id: 3, match_id: 1, kickoff_time: "2026-10-10T12:00:00Z", outcome: "A" }),
      ],
      [],
    );
    expect(rows.map((row) => row.prediction.id)).toEqual([2, 3, 1]);
  });

  it("keeps the most recently placed bet when a key somehow carries several", () => {
    const rows = predictionBetRows(
      [prediction({ id: 1, match_id: 1 })],
      [
        bet({ id: 7, match_id: 1, placed_at: "2026-10-13T00:00:00Z" }),
        bet({ id: 9, match_id: 1, placed_at: "2026-10-14T00:00:00Z" }),
      ],
    );
    expect(rows[0]?.bet?.id).toBe(9);
  });
});

describe("joinSummaryPhrase", () => {
  it("claims no ledger place only when the fetched bets window covers the ledger", () => {
    expect(joinSummaryPhrase(0, 54, false)).toBe(
      "54 of these have no place in the ledger; 0 matched a placed bet.",
    );
  });

  it("qualifies the counts when the fetched bets window is truncated", () => {
    expect(joinSummaryPhrase(2, 52, true)).toBe(
      "2 matched a placed bet in the fetched bets window; 52 have no match there — a bet outside the fetched window would not be seen.",
    );
  });
});
