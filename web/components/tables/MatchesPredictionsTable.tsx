"use client";

import { Inbox, SearchX, TableProperties } from "lucide-react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { Note } from "@/components/ui/Note";
import { RevealFooter } from "@/components/ui/RevealFooter";
import { SearchInput } from "@/components/ui/SearchInput";
import { isTruncated, type BetsWindow } from "@/lib/bets-window";
import {
  formatDateTime,
  formatHkd,
  formatOdds,
  formatPercent,
  formatSignedPercent,
} from "@/lib/format";
import {
  joinSummaryPhrase,
  predictionBetRows,
  type PredictionBetRow,
} from "@/lib/predictions-join";
import { PREDICTIONS_PAGE_SIZE, predictionsWindowPhrase } from "@/lib/predictions-window";
import { matchesQuery } from "@/lib/row-search";
import type { Prediction } from "@/lib/types";
import { REVEAL_INITIAL, useRowReveal } from "@/lib/use-row-reveal";

// The sign carries the meaning; colour is supplementary (DESIGN.md 2.2).
function EdgeCell({ value }: { value: number }) {
  return (
    <span className={value >= 0 ? "text-accent-mint" : "text-status-neg"}>
      {formatSignedPercent(value)}
    </span>
  );
}

const COLUMNS: Column<PredictionBetRow>[] = [
  {
    key: "kickoff",
    header: "Kickoff",
    render: (row) => formatDateTime(row.prediction.kickoff_time),
  },
  { key: "league", header: "League", render: (row) => row.prediction.league_code },
  {
    key: "match",
    header: "Match",
    render: (row) => `${row.prediction.home_team} v ${row.prediction.away_team}`,
  },
  { key: "target", header: "Target", render: (row) => row.prediction.target },
  { key: "outcome", header: "Outcome", render: (row) => row.prediction.outcome },
  {
    key: "prob",
    header: "Prob",
    numeric: true,
    render: (row) => formatPercent(row.prediction.prob),
  },
  {
    key: "implied",
    header: "Implied",
    numeric: true,
    render: (row) =>
      row.prediction.implied_prob === null ? "—" : formatPercent(row.prediction.implied_prob),
  },
  {
    key: "edge",
    header: "Edge",
    numeric: true,
    render: (row) =>
      row.prediction.edge === null ? "—" : <EdgeCell value={row.prediction.edge} />,
  },
  {
    key: "bet",
    header: "Bet",
    render: (row) =>
      row.bet === null ? (
        <span className="text-text-tertiary">no bet</span>
      ) : (
        <span className="text-accent-mint">placed</span>
      ),
  },
  {
    key: "bet-odds",
    header: "Bet odds",
    numeric: true,
    render: (row) => (row.bet === null ? "—" : formatOdds(row.bet.odds)),
  },
  {
    key: "bet-stake",
    header: "Bet stake",
    numeric: true,
    render: (row) => (row.bet === null ? "—" : formatHkd(row.bet.stake)),
  },
];

function predictionMatches(row: PredictionBetRow, query: string): boolean {
  return matchesQuery(
    [
      row.prediction.home_team,
      row.prediction.away_team,
      row.prediction.league_code,
      row.prediction.target,
      row.prediction.outcome,
      row.bet === null ? "no bet" : "placed",
    ],
    query,
  );
}

export interface MatchesPredictionsTableProps {
  predictions: Prediction[] | null;
  bets: BetsWindow | null;
}

export function MatchesPredictionsTable({ predictions, bets }: MatchesPredictionsTableProps) {
  const rows =
    predictions === null || bets === null ? [] : predictionBetRows(predictions, bets.rows);
  const reveal = useRowReveal(rows, predictionMatches);

  if (predictions === null || bets === null) {
    return (
      <EmptyState
        icon={TableProperties}
        title="Matches x predictions unavailable"
        detail="the API did not return /predictions or /bets"
      />
    );
  }
  if (predictions.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="No predictions yet"
        detail="the model has not written a prediction"
      />
    );
  }

  // The summary must describe the set the sentence names: the full window when no filter is active,
  // the filtered set when one is. Passing the window counts under a query-named base would claim that
  // every fetched row matches the query - a false sentence, and the failure spec section 4.2/4.3 exists
  // to prevent.
  const counted = reveal.isFiltered ? reveal.filtered : rows;
  const matched = counted.filter((row) => row.bet !== null).length;
  const unmatched = counted.length - matched;
  const summaryBase = { fetched: rows.length, query: reveal.isFiltered ? reveal.query : undefined };

  return (
    <div className="flex flex-col gap-3">
      <SearchInput
        label="Search predictions"
        scope={`searches the ${predictions.length} rows in this window`}
        value={reveal.query}
        onChange={reveal.setQuery}
        onClear={reveal.clear}
      />
      <Note>
        Window: {predictionsWindowPhrase(predictions.length, PREDICTIONS_PAGE_SIZE)}. Rows
        are shown newest kickoff first within that window.{" "}
        {joinSummaryPhrase(matched, unmatched, isTruncated(bets) || !bets.newestFirst, summaryBase)}
      </Note>
      <DataTable
        columns={COLUMNS}
        rows={reveal.shown}
        rowKey={(row) => row.prediction.id}
        caption="Matches and predictions"
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
