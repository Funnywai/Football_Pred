import { describe, expect, it } from "vitest";

import { bankrollBullet, breakevenBullet, bulletIsDegenerate, winRateFrom } from "@/lib/kpi";
import type { Bet } from "@/lib/types";

function bet(overrides: Partial<Bet>): Bet {
  return {
    id: 1,
    match_id: 1,
    target: "1x2",
    outcome: "H",
    model_version_id: 1,
    line: null,
    odds: 2.0,
    stake: 10,
    bankroll_at_place: 1000,
    edge: 0.05,
    kelly_multiplier: 0.5,
    status: "won",
    placed_at: "2026-10-01T00:00:00Z",
    settled_at: "2026-10-02T00:00:00Z",
    payout: 20,
    profit: 10,
    kickoff_time: "2026-10-01T12:00:00Z",
    league_code: "EPL",
    home_team: "A",
    away_team: "B",
    ...overrides,
  };
}

describe("winRateFrom", () => {
  it("counts wins as settled bets with positive profit", () => {
    const result = winRateFrom([
      bet({ id: 1, status: "won", profit: 10 }),
      bet({ id: 2, status: "lost", profit: -10 }),
      bet({ id: 3, status: "won", profit: 5 }),
    ]);
    expect(result.wins).toBe(2);
    expect(result.losses).toBe(1);
    expect(result.rate).toBeCloseTo(2 / 3);
  });

  it("excludes pushes from the denominator and labels them", () => {
    const result = winRateFrom([
      bet({ id: 1, status: "won", profit: 10 }),
      bet({ id: 2, status: "push", profit: 0 }),
      bet({ id: 3, status: "lost", profit: -10 }),
    ]);
    expect(result.pushes).toBe(1);
    expect(result.settled).toBe(3);
    expect(result.denominator).toBe(2);
    expect(result.rate).toBeCloseTo(0.5);
  });

  it("excludes pending bets entirely", () => {
    const result = winRateFrom([
      bet({ id: 1, status: "pending", profit: null, settled_at: null, payout: null }),
      bet({ id: 2, status: "won", profit: 10 }),
    ]);
    expect(result.settled).toBe(1);
    expect(result.rate).toBe(1);
  });

  it("returns a null rate when every settled bet is a push", () => {
    const result = winRateFrom([bet({ id: 1, status: "push", profit: 0 })]);
    expect(result.denominator).toBe(0);
    expect(result.rate).toBeNull();
  });

  it("counts half_won as a win and half_lost as a loss", () => {
    const result = winRateFrom([
      bet({ id: 1, status: "half_won", profit: 3 }),
      bet({ id: 2, status: "half_lost", profit: -5 }),
    ]);
    expect(result.wins).toBe(1);
    expect(result.losses).toBe(1);
  });
});

describe("bankrollBullet", () => {
  it("targets the initial bankroll and spans zero to the larger of the two", () => {
    expect(bankrollBullet(1234.5, 1000)).toEqual({
      value: 1234.5,
      target: 1000,
      min: 0,
      max: 1234.5,
      origin: 0,
    });
  });

  it("keeps the target inside the range when the bankroll is below the initial", () => {
    const spec = bankrollBullet(800, 1000);
    expect(spec.max).toBe(1000);
    expect(spec.target).toBe(1000);
  });
});

describe("breakevenBullet", () => {
  it("centres zero and spans the value magnitude", () => {
    expect(breakevenBullet(0.05)).toEqual({
      value: 0.05,
      target: 0,
      min: -0.05,
      max: 0.05,
      origin: 0,
    });
  });

  it("is degenerate at exactly breakeven", () => {
    expect(bulletIsDegenerate(breakevenBullet(0))).toBe(true);
  });
});
