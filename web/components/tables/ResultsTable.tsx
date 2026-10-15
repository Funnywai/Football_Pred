"use client";

import { Inbox, SearchX } from "lucide-react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { Note } from "@/components/ui/Note";
import { RevealFooter } from "@/components/ui/RevealFooter";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusPill } from "@/components/ui/StatusPill";
import { formatDateTime } from "@/lib/format";
import { RESULTS_PAGE_SIZE, resultsWindowPhrase } from "@/lib/results-window";
import { matchesQuery } from "@/lib/row-search";
import type { Result } from "@/lib/types";
import { REVEAL_INITIAL, useRowReveal } from "@/lib/use-row-reveal";

// A boolean state is carried by a glyph AND a text label, never colour alone (DESIGN.md 2.2).
function BoolPill({ value, yes, no }: { value: boolean; yes: string; no: string }) {
  return value ? (
    <StatusPill variant="success" label={yes} />
  ) : (
    <StatusPill variant="never-tracked" label={no} />
  );
}

const COLUMNS: Column<Result>[] = [
  { key: "kickoff", header: "Kickoff", render: (result) => formatDateTime(result.kickoff_time) },
  { key: "league", header: "League", render: (result) => result.league_code },
  {
    key: "match",
    header: "Match",
    render: (result) => `${result.home_team.name_en} v ${result.away_team.name_en}`,
  },
  {
    key: "score",
    header: "Score",
    numeric: true,
    render: (result) => `${result.home_score}-${result.away_score}`,
  },
  {
    key: "confirmed",
    header: "Confirmed",
    render: (result) => (
      <BoolPill value={result.confirmed} yes="confirmed" no="unconfirmed" />
    ),
  },
  {
    key: "payout",
    header: "Payout",
    render: (result) => (
      <BoolPill
        value={result.payout_confirmed}
        yes="payout confirmed"
        no="payout unconfirmed"
      />
    ),
  },
  { key: "source", header: "Source", render: (result) => result.source },
  {
    key: "confirmed-at",
    header: "Confirmed at",
    render: (result) => formatDateTime(result.confirmed_at),
  },
];

export interface ResultsTableProps {
  results: Result[] | null;
}

function resultMatches(row: Result, query: string): boolean {
  return matchesQuery(
    [
      row.home_team.name_en,
      row.away_team.name_en,
      row.league_code,
      row.source,
      `${row.home_score}-${row.away_score}`,
    ],
    query,
  );
}

export function ResultsTable({ results }: ResultsTableProps) {
  const reveal = useRowReveal(results ?? [], resultMatches);

  if (results === null) {
    return (
      <EmptyState
        icon={Inbox}
        title="Results unavailable"
        detail="the API did not return /results"
      />
    );
  }
  if (results.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="No results yet"
        detail="no match has a recorded result"
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <SearchInput
        label="Search results"
        scope={`searches the ${results.length} rows in this window`}
        value={reveal.query}
        onChange={reveal.setQuery}
        onClear={reveal.clear}
      />
      <Note>Window: {resultsWindowPhrase(results.length, RESULTS_PAGE_SIZE)}.</Note>
      <DataTable
        columns={COLUMNS}
        rows={reveal.shown}
        rowKey={(result) => result.match_id}
        caption="Every fetched match result with its confirmation state"
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
