import { describe, expect, it } from "vitest";

import { buildBetsTsv, type ExportBet } from "../lib/bets-export";

const sample: ExportBet = {
  bet_id: "bet-1",
  match_id: "match-1",
  kickoff_at: "2026-11-08T20:00:00+00:00",
  competition: "LALIGA",
  home_team: "Club Atlético de Madrid",
  away_team: "FC Barcelona",
  match_status: "finished",
  home_goals_90: 2,
  away_goals_90: 1,
  home_goals_final: 2,
  away_goals_final: 1,
  market: "HAD",
  selection: "H",
  line_key: "0.0",
  odds: "2.10",
  stake: "74.88",
  status: "won",
  placed_at: "2026-11-08T19:20:00+00:00",
  settled_at: "2026-11-08T22:00:00+00:00",
  payout: "157.25",
  profit: "82.37",
  clv: "-0.010582",
  brier: "0.3219",
  model_version: "llm-assistant-v2",
  decision_slot_key: "g1:match-1:T-30m",
  displayLane: "V1",
};

describe("bet ledger TSV export", () => {
  it("copies the filtered bets with stable headers and result columns", () => {
    const tsv = buildBetsTsv([sample]);
    const [header, row] = tsv.split("\n");

    expect(header).toBe(
      [
        "lane",
        "bet_id",
        "match_id",
        "kickoff_hkt",
        "competition",
        "home_team",
        "away_team",
        "result",
        "result_type",
        "market",
        "selection",
        "line_key",
        "odds",
        "stake",
        "status",
        "placed_at",
        "settled_at",
        "payout",
        "profit",
        "clv_pct",
        "brier",
        "model_version",
        "decision_slot_key",
      ].join("\t"),
    );
    const cells = row?.split("\t") ?? [];
    expect(cells).toHaveLength(23);
    expect(cells[0]).toBe("V1");
    expect(cells[7]).toBe("2-1");
    expect(cells[8]).toBe("FT");
    expect(cells[19]).toBe("-1.06");
    expect(row).toContain("22:00:00");
  });

  it("keeps missing values empty and defuses spreadsheet formulas", () => {
    const tsv = buildBetsTsv([
      {
        ...sample,
        displayLane: undefined,
        lane: "legacy",
        match_status: "scheduled",
        home_goals_90: null,
        away_goals_90: null,
        home_goals_final: null,
        away_goals_final: null,
        home_team: "=Atlético",
        profit: "=SUM(A1)\tbroken\nline",
        clv: null,
        settled_at: null,
        status: "pending",
      },
    ]);
    const cells = tsv.split("\n")[1]?.split("\t") ?? [];

    expect(cells[0]).toBe("legacy");
    expect(cells[5]).toBe("'=Atlético");
    expect(cells[7]).toBe("");
    expect(cells[8]).toBe("");
    expect(cells[19]).toBe("");
    expect(cells[18]).toBe("'=SUM(A1) broken line");
  });

  it("returns only the header for an empty filtered list", () => {
    expect(buildBetsTsv([]).split("\n")).toHaveLength(1);
  });
});
