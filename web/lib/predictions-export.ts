import {
  asNumber,
  formatKickoff,
  formatNumber,
  formatOdds,
  toPercentPoints,
} from "./format";
import type { Prediction } from "./types";

const HEADERS = [
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
  const points = toPercentPoints(value);
  return points === null ? "" : formatNumber(points, 2);
}

function resultFields(prediction: Prediction): {
  result: string;
  resultType: string;
} {
  const status = (prediction.status ?? "").toLowerCase();
  const finished = status === "finished";
  const live = status === "live";
  const home90 = asNumber(prediction.home_goals_90);
  const away90 = asNumber(prediction.away_goals_90);
  const home = home90 ?? asNumber(prediction.home_goals_final);
  const away = away90 ?? asNumber(prediction.away_goals_final);

  if ((!finished && !live) || home === null || away === null) {
    return { result: "", resultType: "" };
  }
  return {
    result: `${home}-${away}`,
    resultType: live ? "LIVE" : home90 === null ? "AET" : "FT",
  };
}

/**
 * Build a spreadsheet-friendly TSV for the complete prediction feed. Missing
 * values are copied as empty cells so the output can be pasted into Excel or
 * Sheets without carrying display-only dashes into numeric columns.
 */
export function buildPredictionsTsv(predictions: Prediction[]): string {
  const rows = predictions.map((prediction) => {
    const probabilities = prediction.probabilities ?? {};
    const odds = prediction.odds ?? {};
    const ev = prediction.ev ?? {};
    const result = resultFields(prediction);
    const kickoff = formatKickoff(prediction.kickoff_at);

    return [
      textCell(prediction.match_id),
      textCell(kickoff === "—" ? "" : kickoff),
      textCell(prediction.competition),
      textCell(prediction.home_team),
      textCell(prediction.away_team),
      textCell(prediction.status),
      textCell(result.result),
      textCell(result.resultType),
      prediction.home_goals_90,
      prediction.away_goals_90,
      prediction.home_goals_final,
      prediction.away_goals_final,
      percentCell(probabilities.H),
      percentCell(probabilities.D),
      percentCell(probabilities.A),
      formatOdds(odds.H) === "—" ? "" : formatOdds(odds.H),
      formatOdds(odds.D) === "—" ? "" : formatOdds(odds.D),
      formatOdds(odds.A) === "—" ? "" : formatOdds(odds.A),
      percentCell(ev.H),
      percentCell(ev.D),
      percentCell(ev.A),
      textCell(prediction.model_version),
      textCell(prediction.decision_status),
      textCell(prediction.decision_reason),
    ];
  });

  return [HEADERS.map(cell), ...rows].map((row) => row.join("\t")).join("\n");
}
