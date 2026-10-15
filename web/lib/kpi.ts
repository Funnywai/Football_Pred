// KPI derivation for the performance strip. Pure functions over the real API fields only.
//
// `roi` and `yield_pct` from /bets/summary are FRACTIONS (app/services/ledger.py:
// roi = realized/settled_stakes, yield_pct = realized/stakes_total), so the formatter
// multiplies by 100. Win rate is not in the summary; it is derived from the settled rows
// of /bets (wins = settled bets with positive profit; pushes are excluded from the
// denominator and labelled).

import type { Bet } from "./types";

export interface WinRate {
  wins: number;
  losses: number;
  pushes: number;
  settled: number;
  denominator: number;
  rate: number | null;
}

export function winRateFrom(bets: Bet[]): WinRate {
  const settled = bets.filter((bet) => bet.status !== "pending");
  const pushes = settled.filter((bet) => bet.status === "push");
  const wins = settled.filter((bet) => (bet.profit ?? 0) > 0);
  const losses = settled.filter((bet) => (bet.profit ?? 0) < 0);
  const denominator = settled.length - pushes.length;
  return {
    wins: wins.length,
    losses: losses.length,
    pushes: pushes.length,
    settled: settled.length,
    denominator,
    rate: denominator === 0 ? null : wins.length / denominator,
  };
}

// A bullet bar needs a real range and a real target. Only two thresholds exist in the
// data: bankroll against the initial bankroll (breakeven), and ROI/yield against 0.
export interface BulletSpec {
  value: number;
  target: number;
  min: number;
  max: number;
  origin: number;
}

export function bankrollBullet(bankroll: number, initialBankroll: number): BulletSpec {
  return {
    value: bankroll,
    target: initialBankroll,
    min: 0,
    max: Math.max(bankroll, initialBankroll),
    origin: 0,
  };
}

export function breakevenBullet(value: number): BulletSpec {
  const radius = Math.abs(value);
  return { value, target: 0, min: -radius, max: radius, origin: 0 };
}

export function bulletIsDegenerate(spec: BulletSpec): boolean {
  return spec.max === spec.min;
}
