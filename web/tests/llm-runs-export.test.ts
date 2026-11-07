import { describe, expect, it } from "vitest";

import { buildLlmRunsTsv } from "../lib/llm-runs-export";
import type { LlmResearchRun } from "../lib/llm-types";

const sample: LlmResearchRun = {
  run_id: "run-1",
  match_id: "match-1",
  kickoff_at: "2026-11-07T12:30:00+00:00",
  competition: "EPL",
  home_team: "Leeds United FC",
  away_team: "Tottenham Hotspur FC",
  status: "bet",
  stage: "T-30m",
  model_version: "llm-assistant-v2",
  prompt_version: "research-v2",
  provider: "openai_compatible",
  recommended_side: "A",
  recommended_stake_pct: "0.006",
  confidence: "0.64",
  probabilities: { H: "0.31", D: "0.29", A: "0.4" },
  active_findings: 3,
  total_findings: 7,
  error: null,
};

describe("LLM research runs TSV export", () => {
  it("copies the filtered runs with stable headers and numeric cells", () => {
    const tsv = buildLlmRunsTsv([sample]);
    const [header, row] = tsv.split("\n");

    expect(header).toBe(
      [
        "match_id",
        "run_id",
        "kickoff_hkt",
        "competition",
        "home_team",
        "away_team",
        "status",
        "recommended_side",
        "recommended_stake_pct",
        "confidence_pct",
        "p_home_pct",
        "p_draw_pct",
        "p_away_pct",
        "active_findings",
        "total_findings",
        "model_version",
        "prompt_version",
        "stage",
        "provider",
        "error",
      ].join("\t"),
    );
    expect(row?.split("\t")).toHaveLength(20);
    expect(row).toContain("0.60\t64.00\t31.00\t29.00\t40.00\t3\t7");
    expect(row).toContain("07 Nov, 20:30");
  });

  it("keeps missing values empty and defuses spreadsheet formulas", () => {
    const tsv = buildLlmRunsTsv([
      {
        ...sample,
        recommended_side: null,
        recommended_stake_pct: null,
        confidence: null,
        probabilities: null,
        error: "=SUM(A1)\tbroken\nline",
        home_team: "=Leeds",
      },
    ]);
    const row = tsv.split("\n")[1] ?? "";
    const cells = row.split("\t");

    expect(cells[4]).toBe("'=Leeds");
    expect(cells[7]).toBe("");
    expect(cells[8]).toBe("");
    expect(cells[9]).toBe("");
    expect(cells[10]).toBe("");
    expect(cells[19]).toBe("'=SUM(A1) broken line");
  });

  it("returns only the header for an empty filtered list", () => {
    expect(buildLlmRunsTsv([]).split("\n")).toHaveLength(1);
  });
});
