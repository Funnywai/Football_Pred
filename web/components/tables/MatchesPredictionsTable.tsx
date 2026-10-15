import { Inbox, TableProperties } from "lucide-react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { Note } from "@/components/ui/Note";
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
import type { Prediction } from "@/lib/types";

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

export interface MatchesPredictionsTableProps {
  predictions: Prediction[] | null;
  bets: BetsWindow | null;
}

export function MatchesPredictionsTable({ predictions, bets }: MatchesPredictionsTableProps) {
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

  const rows = predictionBetRows(predictions, bets.rows);
  const matched = rows.filter((row) => row.bet !== null).length;
  const unmatched = rows.length - matched;

  return (
    <div className="flex flex-col gap-3">
      <Note>
        Window: {predictionsWindowPhrase(predictions.length, PREDICTIONS_PAGE_SIZE)}. Rows
        are shown newest kickoff first within that window.{" "}
        {joinSummaryPhrase(matched, unmatched, isTruncated(bets) || !bets.newestFirst)}
      </Note>
      <DataTable
        columns={COLUMNS}
        rows={rows}
        rowKey={(row) => row.prediction.id}
        caption="Every fetched prediction with the bet it produced, if any"
      />
    </div>
  );
}
