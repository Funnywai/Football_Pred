import { asNumber, formatKickoff, formatNumber } from "./format";
import type { LlmResearchRun } from "./llm-types";

const HEADERS = [
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
] as const;

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value).replaceAll("\t", " ").replace(/\r?\n/g, " ");
}

/** Free-text cells must not become spreadsheet formulas when pasted. */
function textCell(value: unknown): string {
  const text = cell(value);
  return /^[=+\-@]/.test(text) ? `'${text}` : text;
}

function percentCell(value: string | number | null | undefined): string {
  const parsed = asNumber(value);
  return parsed === null ? "" : formatNumber(parsed * 100, 2);
}

function countCell(value: number | null | undefined): string {
  return typeof value === "number" ? String(value) : "";
}

/**
 * Build a spreadsheet-friendly TSV for the currently filtered research runs.
 * Missing values are empty cells so numeric columns stay numeric when pasted
 * into Excel or Sheets.
 */
export function buildLlmRunsTsv(runs: LlmResearchRun[]): string {
  const rows = runs.map((run) => {
    const probabilities = run.probabilities ?? {};
    const kickoff = formatKickoff(run.kickoff_at);

    return [
      textCell(run.match_id),
      textCell(run.run_id),
      textCell(kickoff === "—" ? "" : kickoff),
      textCell(run.competition),
      textCell(run.home_team),
      textCell(run.away_team),
      textCell(run.status),
      textCell(run.recommended_side),
      percentCell(run.recommended_stake_pct),
      percentCell(run.confidence),
      percentCell(probabilities.H),
      percentCell(probabilities.D),
      percentCell(probabilities.A),
      countCell(run.active_findings),
      countCell(run.total_findings),
      textCell(run.model_version),
      textCell(run.prompt_version),
      textCell(run.stage),
      textCell(run.provider),
      textCell(run.error),
    ];
  });

  return [HEADERS.map(cell), ...rows].map((row) => row.join("\t")).join("\n");
}
