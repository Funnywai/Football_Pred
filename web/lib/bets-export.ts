import { asNumber, formatKickoff, formatNumber, formatOdds } from "./format";
import type { Bet } from "./types";

export type ExportBet = Bet & { displayLane?: "V1" | "V2" };

const HEADERS = [
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

function ratioPercentCell(value: string | number | null | undefined): string {
  const parsed = asNumber(value);
  return parsed === null ? "" : formatNumber(parsed * 100, 2);
}

function resultFields(bet: Bet): { result: string; resultType: string } {
  const status = (bet.match_status ?? "").toLowerCase();
  const betStatus = (bet.status ?? "").toLowerCase();
  const settled =
    Boolean(bet.settled_at) ||
    ["won", "lost", "void", "push", "settled"].includes(betStatus);
  const live = status === "live" && !settled;
  const finished = status === "finished" || settled;
  const home90 = asNumber(bet.home_goals_90);
  const away90 = asNumber(bet.away_goals_90);
  const home = home90 ?? asNumber(bet.home_goals_final);
  const away = away90 ?? asNumber(bet.away_goals_final);

  if ((!finished && !live) || home === null || away === null) {
    return { result: "", resultType: "" };
  }
  return {
    result: `${home}-${away}`,
    resultType: live ? "LIVE" : home90 === null ? "AET" : "FT",
  };
}

/**
 * Build a spreadsheet-friendly TSV for the currently filtered bet ledger.
 * Missing values are empty cells so numeric columns stay numeric when pasted
 * into Excel or Sheets.
 */
export function buildBetsTsv(bets: ExportBet[]): string {
  const rows = bets.map((bet) => {
    const result = resultFields(bet);
    const kickoff = formatKickoff(bet.kickoff_at);
    const odds = formatOdds(bet.odds);

    return [
      textCell(bet.displayLane ?? bet.lane),
      textCell(bet.bet_id),
      textCell(bet.match_id),
      textCell(kickoff === "—" ? "" : kickoff),
      textCell(bet.competition),
      textCell(bet.home_team),
      textCell(bet.away_team),
      textCell(result.result),
      textCell(result.resultType),
      textCell(bet.market),
      textCell(bet.selection),
      textCell(bet.line_key),
      textCell(odds === "—" ? "" : odds),
      textCell(bet.stake),
      textCell(bet.status),
      textCell(bet.placed_at),
      textCell(bet.settled_at),
      textCell(bet.payout),
      textCell(bet.profit),
      ratioPercentCell(bet.clv),
      textCell(bet.brier),
      textCell(bet.model_version),
      textCell(bet.decision_slot_key),
    ];
  });

  return [HEADERS.map(cell), ...rows].map((row) => row.join("\t")).join("\n");
}
