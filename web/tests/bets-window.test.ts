import { describe, expect, it } from "vitest";

import {
  betsWindowPhrase,
  isTruncated,
  newestPageOffset,
  sortBetsNewestFirst,
  type BetsWindow,
} from "@/lib/bets-window";
import type { Bet } from "@/lib/types";

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

function windowOf(rows: Bet[], total: number | null, newestFirst = true): BetsWindow {
  return { rows, total, newestFirst };
}

describe("newestPageOffset", () => {
  it("returns 0 for an empty ledger", () => {
    expect(newestPageOffset(0, 200)).toBe(0);
  });

  it("returns 0 when the ledger fits in one page", () => {
    expect(newestPageOffset(2, 200)).toBe(0);
  });

  it("returns 0 when the ledger is exactly one page", () => {
    expect(newestPageOffset(200, 200)).toBe(0);
  });

  it("returns the tail offset when the ledger exceeds one page", () => {
    expect(newestPageOffset(250, 200)).toBe(50);
  });
});

describe("sortBetsNewestFirst", () => {
  it("orders by placed_at descending", () => {
    const older = bet({ id: 1, placed_at: "2026-10-13T00:00:00Z" });
    const newer = bet({ id: 2, placed_at: "2026-10-14T00:00:00Z" });
    expect(sortBetsNewestFirst([older, newer]).map((row) => row.id)).toEqual([2, 1]);
  });

  it("breaks placed_at ties by id descending", () => {
    const first = bet({ id: 7, placed_at: "2026-10-14T00:00:00Z" });
    const second = bet({ id: 9, placed_at: "2026-10-14T00:00:00Z" });
    expect(sortBetsNewestFirst([first, second]).map((row) => row.id)).toEqual([9, 7]);
  });

  it("does not mutate the input array", () => {
    const rows = [
      bet({ id: 1, placed_at: "2026-10-13T00:00:00Z" }),
      bet({ id: 2, placed_at: "2026-10-14T00:00:00Z" }),
    ];
    sortBetsNewestFirst(rows);
    expect(rows.map((row) => row.id)).toEqual([1, 2]);
  });
});

describe("isTruncated", () => {
  it("is true when the summary total exceeds the fetched rows", () => {
    expect(isTruncated(windowOf([bet({}), bet({ id: 2 })], 250))).toBe(true);
  });

  it("is false when the fetched rows cover the total", () => {
    expect(isTruncated(windowOf([bet({}), bet({ id: 2 })], 2))).toBe(false);
  });

  it("is false when the total is unknown", () => {
    expect(isTruncated(windowOf([bet({})], null, false))).toBe(false);
  });
});

describe("betsWindowPhrase", () => {
  it("names the fetched slice of a truncated window", () => {
    const rows = Array.from({ length: 200 }, (_, index) => bet({ id: index + 1 }));
    expect(betsWindowPhrase(windowOf(rows, 250))).toBe("the 200 most recent of 250 bets");
  });

  it("names a complete window", () => {
    expect(betsWindowPhrase(windowOf([bet({}), bet({ id: 2 })], 2))).toBe("all 2 bets");
  });

  it("names the oldest-page fallback", () => {
    expect(betsWindowPhrase(windowOf([bet({}), bet({ id: 2 })], null, false))).toBe(
      "the oldest 2 bets",
    );
  });
});
