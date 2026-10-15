"use client";

import { ArrowDown, ArrowLeftRight, ArrowUp, Inbox, SearchX } from "lucide-react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { Note } from "@/components/ui/Note";
import { RevealFooter } from "@/components/ui/RevealFooter";
import { SearchInput } from "@/components/ui/SearchInput";
import { betsWindowPhrase, type BetsWindow } from "@/lib/bets-window";
import { formatDateTime, formatOdds, formatSignedPercent } from "@/lib/format";
import { matchesQuery } from "@/lib/row-search";
import { signalExecutionRows, type SignalExecutionRow } from "@/lib/signal-execution";
import type { Prediction } from "@/lib/types";
import { REVEAL_INITIAL, useRowReveal } from "@/lib/use-row-reveal";

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

function signalMatches(row: SignalExecutionRow, query: string): boolean {
  return matchesQuery([row.homeTeam, row.awayTeam, row.leagueCode, row.outcome], query);
}

export interface SignalVsExecutionTableProps {
  bets: BetsWindow | null;
  predictions: Prediction[] | null;
}

export function SignalVsExecutionTable({ bets, predictions }: SignalVsExecutionTableProps) {
  const rows =
    bets === null || predictions === null ? [] : signalExecutionRows(bets.rows, predictions);
  const reveal = useRowReveal(rows, signalMatches);

  if (bets === null || predictions === null) {
    return (
      <EmptyState
        icon={ArrowLeftRight}
        title="Signal vs execution unavailable"
        detail="the API did not return /bets or /predictions"
      />
    );
  }
  if (bets.rows.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="No bets to compare yet"
        detail="the comparison appears once a bet is placed"
      />
    );
  }

  const unmatched = rows.filter((row) => !row.matched).length;

  return (
    <div className="flex flex-col gap-3">
      <SearchInput
        label="Search signal vs execution"
        scope={`searches the ${rows.length} rows in this window`}
        value={reveal.query}
        onChange={reveal.setQuery}
        onClear={reveal.clear}
      />
      <Note>
        signal is the 48h prior market price (predictions.market_odds); execution is the
        price the bet was placed at (ledger_bets.odds). Rows where the price moved against
        us are marked. Window: {betsWindowPhrase(bets)} joined with
        /predictions?limit=200&champion_only=false.
        {unmatched > 0
          ? ` ${unmatched} bet(s) have no matching prediction in the fetched page.`
          : ""}
      </Note>
      <DataTable
        columns={COLUMNS}
        rows={reveal.shown}
        rowKey={(row) => row.betId}
        caption="Signal price vs execution price per bet"
        rowClassName={(row) => (row.againstUs ? "border-l-2 border-l-status-neg bg-status-neg/5" : "")}
        empty={
          reveal.isFiltered ? (
            <EmptyState
              icon={SearchX}
              title={`No row in this window matches "${reveal.query.trim()}"`}
              detail="Search covers only the fetched window."
            />
          ) : undefined
        }
      />
      <RevealFooter
        shown={reveal.shown.length}
        matching={reveal.filtered.length}
        query={reveal.query}
        isFiltered={reveal.isFiltered}
        canExpand={reveal.canExpand}
        canCollapse={reveal.visible > REVEAL_INITIAL}
        onExpand={reveal.expand}
        onExpandAll={reveal.expandAll}
        onCollapse={reveal.collapse}
      />
    </div>
  );
}
