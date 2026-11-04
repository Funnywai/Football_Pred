import { describe, expect, it } from "vitest";

import { buildPredictionsTsv } from "../lib/predictions-export";
import type { Prediction } from "../lib/types";

const sample: Prediction = {
  match_id: "match-1",
  kickoff_at: "2026-11-04T17:45:00+00:00",
  competition: "UCL",
  home_team: "Fenerbahçe SK",
  away_team: "Liverpool FC",
  status: "finished",
  home_goals_90: "2",
  away_goals_90: "1",
  home_goals_final: "2",
  away_goals_final: "1",
  probabilities: { H: "0.42", D: "0.28", A: "0.3" },
  odds: { H: 2.1, D: 3.4, A: 3.6 },
  ev: { H: "0.05", D: "-0.02", A: "-0.01" },
  model_version: "poisson-v1",
  decision_status: "bet",
  decision_reason: "positive\tev\nsignal",
};

describe("prediction TSV export", () => {
  it("copies every feed row with stable headers and clean cells", () => {
    const tsv = buildPredictionsTsv([sample]);
    const [header, row] = tsv.split("\n");

    expect(header).toBe(
      [
        "match_id",
        "kickoff_hkt",
        "competition",
        "home_team",
        "away_team",
        "status",
        "result",
        "result_type",
        "home_goals_90",
        "away_goals_90",
        "home_goals_final",
        "away_goals_final",
        "p_home_pct",
        "p_draw_pct",
        "p_away_pct",
        "odds_home",
        "odds_draw",
        "odds_away",
        "ev_home_pct",
        "ev_draw_pct",
        "ev_away_pct",
        "model_version",
        "decision_status",
        "decision_reason",
      ].join("\t"),
    );
    expect(row?.split("\t")).toHaveLength(24);
    expect(row).toContain("2-1\tFT");
    expect(row).toContain("42.00\t28.00\t30.00");
    expect(row).toContain("2.10\t3.40\t3.60");
    expect(row).toContain("5.00\t-2.00\t-1.00");
    expect(row).toContain("positive ev signal");
  });

  it("exports a live score with a LIVE result type", () => {
    const tsv = buildPredictionsTsv([
      { ...sample, status: "live", home_goals_90: "0", away_goals_90: "3" },
    ]);
    const row = tsv.split("\n")[1] ?? "";

    expect(row).toContain("0-3\tLIVE");
  });

  it("leaves missing numeric fields empty instead of using display dashes", () => {
    const tsv = buildPredictionsTsv([{ match_id: "match-2" }]);
    const row = tsv.split("\n")[1]?.split("\t") ?? [];

    expect(row[12]).toBe("");
    expect(row[15]).toBe("");
    expect(row[18]).toBe("");
  });
});
