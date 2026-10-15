// Equity-curve derivation. The API returns the initial point (t = null), one point per
// settlement, and a final "now" point (app/services/ledger.py:equity_curve). Pure and
// unit-testable; the chart component consumes this model.

import { formatHkd, formatSignedHkd, formatSignedPercent } from "./format";
import type { EquityPoint } from "./types";

export interface EquityModel {
  points: EquityPoint[];
  hasSettlements: boolean;
  first: number | null;
  last: number | null;
  change: number | null;
  changePct: number | null;
  summary: string;
}

export function equityModel(points: EquityPoint[]): EquityModel {
  if (points.length === 0) {
    return {
      points,
      hasSettlements: false,
      first: null,
      last: null,
      change: null,
      changePct: null,
      summary: "no equity points yet",
    };
  }

  const first = points[0]?.bankroll ?? null;
  const last = points[points.length - 1]?.bankroll ?? null;
  const change = first === null || last === null ? null : last - first;
  const changePct = change === null || first === null || first === 0 ? null : change / first;

  return {
    points,
    hasSettlements: points.length > 2,
    first,
    last,
    change,
    changePct,
    summary: buildSummary(first, last, change, changePct),
  };
}

function buildSummary(
  first: number | null,
  last: number | null,
  change: number | null,
  changePct: number | null,
): string {
  if (first === null || last === null || change === null) return "no equity points yet";
  const pct = changePct === null ? "" : ` (${formatSignedPercent(changePct)})`;
  return `${formatHkd(first)} to ${formatHkd(last)} · ${formatSignedHkd(change)}${pct}`;
}
