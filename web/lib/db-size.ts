// DB size derivation for the /ops/data snapshot. Every value is a row count, never a rate.

import type { OpsOddsGroup } from "./types";

export interface TableCountRow {
  table: string;
  count: number;
}

/** Preserve the API's table order (app/api/ops_data.py _TABLE_MODELS). */
export function tableCountRows(counts: Record<string, number>): TableCountRow[] {
  return Object.entries(counts).map(([table, count]) => ({ table, count }));
}

export interface OddsGroupRow {
  source: string;
  oddsType: string;
  inplay: boolean;
  count: number;
  newest: string | null;
}

export function oddsGroupRows(groups: OpsOddsGroup[]): OddsGroupRow[] {
  return groups.map((group) => ({
    source: group.source,
    oddsType: group.odds_type,
    inplay: group.inplay,
    count: group.count,
    newest: group.max_captured_at,
  }));
}
