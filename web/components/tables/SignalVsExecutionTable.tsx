import { ArrowDown, ArrowLeftRight, ArrowUp, Inbox } from "lucide-react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatDateTime, formatOdds, formatSignedPercent } from "@/lib/format";
import { signalExecutionRows, type SignalExecutionRow } from "@/lib/signal-execution";
import type { Bet, Prediction } from "@/lib/types";

function DiffCell({ value, percent = false }: { value: number; percent?: boolean }) {
  const positive = value >= 0;
  const text = percent ? formatSignedPercent(value) : `${value >= 0 ? "+" : "-"}${Math.abs(value).toFixed(2)}`;
  return (
    <span
      className={`inline-flex items-center gap-1 ${positive ? "text-accent-mint" : "text-status-neg"}`}
    >
      {positive ? (
        <ArrowUp className="size-3" aria-hidden />
      ) : (
        <ArrowDown className="size-3" aria-hidden />
      )}
      {text}
    </span>
  );
}

const COLUMNS: Column<SignalExecutionRow>[] = [
  { key: "match", header: "Match", render: (row) => `${row.homeTeam} v ${row.awayTeam}` },
  { key: "target", header: "Target", render: (row) => row.target },
  { key: "outcome", header: "Outcome", render: (row) => row.outcome },
  {
    key: "signal",
    header: "Signal",
    numeric: true,
    render: (row) => (row.signalOdds === null ? "—" : formatOdds(row.signalOdds)),
  },
  { key: "execution", header: "Execution", numeric: true, render: (row) => formatOdds(row.executionOdds) },
  {
    key: "abs",
    header: "Δ abs",
    numeric: true,
    render: (row) => (row.absDiff === null ? "—" : <DiffCell value={row.absDiff} />),
  },
  {
    key: "pct",
    header: "Δ %",
    numeric: true,
    render: (row) => (row.pctDiff === null ? "—" : <DiffCell value={row.pctDiff} percent />),
  },
  { key: "kickoff", header: "Kickoff", render: (row) => formatDateTime(row.kickoffTime) },
];

export interface SignalVsExecutionTableProps {
  bets: Bet[] | null;
  predictions: Prediction[] | null;
}

export function SignalVsExecutionTable({ bets, predictions }: SignalVsExecutionTableProps) {
  if (bets === null || predictions === null) {
    return (
      <EmptyState
        icon={ArrowLeftRight}
        title="Signal vs execution unavailable"
        detail="the API did not return /bets or /predictions"
      />
    );
  }
  if (bets.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="No bets to compare yet"
        detail="the comparison appears once a bet is placed"
      />
    );
  }

  const rows = signalExecutionRows(bets, predictions);
  const unmatched = rows.filter((row) => !row.matched).length;

  return (
    <div className="flex flex-col">
      <p className="px-6 py-3 text-caption text-text-tertiary">
        signal is the 48h prior market price (predictions.market_odds); execution is the
        price the bet was placed at (ledger_bets.odds). Rows where the price moved against
        us are marked.
        {unmatched > 0 ? ` ${unmatched} bet(s) have no matching prediction.` : ""}
      </p>
      <DataTable
        columns={COLUMNS}
        rows={rows}
        rowKey={(row) => row.betId}
        caption="Signal price vs execution price per bet"
        rowClassName={(row) => (row.againstUs ? "border-l-2 border-l-status-neg bg-status-neg/5" : "")}
      />
    </div>
  );
}
