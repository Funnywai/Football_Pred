import { describe, expect, it } from "vitest";

import { signalExecutionRows } from "@/lib/signal-execution";
import type { Bet, Prediction } from "@/lib/types";

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
    home_team: "A",
    away_team: "B",
    ...overrides,
  };
}

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
    home_team: "A",
    away_team: "B",
    ...overrides,
  };
}

describe("signalExecutionRows", () => {
  it("joins on (match_id, target, outcome, model_version_id)", () => {
    const rows = signalExecutionRows(
      [bet({ id: 1, match_id: 29164, odds: 2.48 })],
      [prediction({ match_id: 29164, market_odds: 2.48 })],
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]?.matched).toBe(true);
    expect(rows[0]?.signalOdds).toBe(2.48);
    expect(rows[0]?.executionOdds).toBe(2.48);
    expect(rows[0]?.absDiff).toBe(0);
  });

  it("computes the absolute and percentage difference for the execution-price bet", () => {
    const rows = signalExecutionRows(
      [bet({ id: 2, match_id: 29160, odds: 4.0 })],
      [prediction({ match_id: 29160, market_odds: 3.9 })],
    );
    expect(rows[0]?.absDiff).toBeCloseTo(0.1);
    expect(rows[0]?.pctDiff).toBeCloseTo(0.1 / 3.9);
    expect(rows[0]?.againstUs).toBe(false);
  });

  it("flags a price that moved against us", () => {
    const rows = signalExecutionRows(
      [bet({ id: 3, match_id: 1, odds: 3.5 })],
      [prediction({ match_id: 1, market_odds: 4.0 })],
    );
    expect(rows[0]?.againstUs).toBe(true);
    expect(rows[0]?.absDiff).toBeCloseTo(-0.5);
  });

  it("leaves an unmatched bet with a null signal and sorts it last", () => {
    const rows = signalExecutionRows(
      [
        bet({ id: 1, match_id: 29160, odds: 4.0 }),
        bet({ id: 2, match_id: 999, odds: 2.0 }),
      ],
      [prediction({ match_id: 29160, market_odds: 3.9 })],
    );
    expect(rows[0]?.betId).toBe(1);
    expect(rows[1]?.betId).toBe(2);
    expect(rows[1]?.matched).toBe(false);
    expect(rows[1]?.signalOdds).toBeNull();
    expect(rows[1]?.absDiff).toBeNull();
  });

  it("sorts by absolute difference descending", () => {
    const rows = signalExecutionRows(
      [
        bet({ id: 1, match_id: 1, odds: 2.5 }),
        bet({ id: 2, match_id: 2, odds: 4.0 }),
      ],
      [
        prediction({ match_id: 1, market_odds: 2.48 }),
        prediction({ match_id: 2, market_odds: 3.9 }),
      ],
    );
    expect(rows.map((row) => row.betId)).toEqual([2, 1]);
  });

  it("does not match a prediction with a different model_version_id", () => {
    const rows = signalExecutionRows(
      [bet({ id: 1, match_id: 29164, model_version_id: 2 })],
      [prediction({ match_id: 29164, model_version_id: 1 })],
    );
    expect(rows[0]?.matched).toBe(false);
  });
});
