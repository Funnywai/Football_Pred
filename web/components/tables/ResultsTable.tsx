import { Info, Inbox } from "lucide-react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusPill } from "@/components/ui/StatusPill";
import { formatDateTime } from "@/lib/format";
import { RESULTS_PAGE_SIZE, resultsWindowPhrase } from "@/lib/results-window";
import type { Result } from "@/lib/types";

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

export function ResultsTable({ results }: ResultsTableProps) {
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
    <div className="flex flex-col">
      <p className="flex items-start gap-2 px-6 py-3 text-caption text-text-tertiary">
        <Info className="mt-0.5 size-3 shrink-0" aria-hidden />
        <span>Window: {resultsWindowPhrase(results.length, RESULTS_PAGE_SIZE)}.</span>
      </p>
      <DataTable
        columns={COLUMNS}
        rows={results}
        rowKey={(result) => result.match_id}
        caption="Every fetched match result with its confirmation state"
      />
    </div>
  );
}
