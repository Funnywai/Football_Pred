"use client";

import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Inbox, Info } from "lucide-react";
import { useState } from "react";

import { BetStatusPill } from "@/components/ui/BetStatusPill";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { betsWindowPhrase, isTruncated, type BetsWindow } from "@/lib/bets-window";
import {
  formatDateTime,
  formatHkd,
  formatOdds,
  formatPercent,
  formatSignedHkd,
} from "@/lib/format";
import type { Bet } from "@/lib/types";

const PAGE_SIZE = 25;

const BUTTON =
  "inline-flex items-center gap-1 rounded-md border border-border-default px-2 py-1 text-caption text-text-secondary transition-colors duration-150 ease-out hover:border-accent-signal/60 hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40";

function ProfitCell({ value }: { value: number }) {
  const positive = value >= 0;
  return (
    <span
      className={`inline-flex items-center gap-1 ${positive ? "text-accent-mint" : "text-status-neg"}`}
    >
      {positive ? (
        <ArrowUp className="size-3" aria-hidden />
      ) : (
        <ArrowDown className="size-3" aria-hidden />
      )}
      {formatSignedHkd(value)}
    </span>
  );
}

const COLUMNS: Column<Bet>[] = [
  { key: "kickoff", header: "Kickoff", render: (bet) => formatDateTime(bet.kickoff_time) },
  { key: "league", header: "League", render: (bet) => bet.league_code },
  { key: "teams", header: "Teams", render: (bet) => `${bet.home_team} v ${bet.away_team}` },
  { key: "target", header: "Target", render: (bet) => bet.target },
  { key: "outcome", header: "Outcome", render: (bet) => bet.outcome },
  { key: "odds", header: "Odds", numeric: true, render: (bet) => formatOdds(bet.odds) },
  {
    key: "edge",
    header: "Edge",
    numeric: true,
    render: (bet) => (bet.edge === null ? "—" : formatPercent(bet.edge)),
  },
  { key: "stake", header: "Stake", numeric: true, render: (bet) => formatHkd(bet.stake) },
  {
    key: "payout",
    header: "Payout",
    numeric: true,
    render: (bet) => (bet.payout === null ? "—" : formatHkd(bet.payout)),
  },
  {
    key: "profit",
    header: "Profit",
    numeric: true,
    render: (bet) => (bet.profit === null ? "—" : <ProfitCell value={bet.profit} />),
  },
  { key: "status", header: "Status", render: (bet) => <BetStatusPill status={bet.status} /> },
  { key: "placed", header: "Placed", render: (bet) => formatDateTime(bet.placed_at) },
];

export interface BetsTableProps {
  bets: BetsWindow | null;
}

export function BetsTable({ bets }: BetsTableProps) {
  const [page, setPage] = useState(0);

  if (bets === null) {
    return (
      <EmptyState icon={Inbox} title="Bets unavailable" detail="the API did not return /bets" />
    );
  }
  if (bets.rows.length === 0) {
    return <EmptyBets bets={bets} />;
  }

  const pageCount = Math.max(1, Math.ceil(bets.rows.length / PAGE_SIZE));
  const current = Math.min(page, pageCount - 1);
  const rows = bets.rows.slice(current * PAGE_SIZE, current * PAGE_SIZE + PAGE_SIZE);

  return (
    <div className="flex flex-col">
      <p className="flex items-start gap-2 px-6 py-3 text-caption text-text-tertiary">
        <Info className="mt-0.5 size-3 shrink-0" aria-hidden />
        <span>
          odds is the execution price (the latest pre-kickoff HKJC snapshot at placement);
          edge is measured at that price.
        </span>
      </p>
      <DataTable
        columns={COLUMNS}
        rows={rows}
        rowKey={(bet) => bet.id}
        caption="All ledger bets"
      />
      <div className="flex items-center justify-between gap-4 px-6 py-3 text-caption text-text-tertiary">
        <span className="tnum">{footerText(bets, current + 1, pageCount)}</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className={BUTTON}
            onClick={() => setPage(current - 1)}
            disabled={current === 0}
          >
            <ChevronLeft className="size-3" aria-hidden />
            Prev
          </button>
          <button
            type="button"
            className={BUTTON}
            onClick={() => setPage(current + 1)}
            disabled={current >= pageCount - 1}
          >
            Next
            <ChevronRight className="size-3" aria-hidden />
          </button>
        </div>
      </div>
    </div>
  );
}

// The footer never states a fetched count as a total: a truncated window names the slice
// it shows, and the oldest-page fallback names its missing summary.
function footerText(bets: BetsWindow, page: number, pageCount: number): string {
  const pagination = `page ${page} of ${pageCount}`;
  if (!bets.newestFirst) {
    return `showing the oldest ${bets.rows.length} bets · ${pagination} · /bets/summary unavailable`;
  }
  if (isTruncated(bets)) {
    return `showing ${betsWindowPhrase(bets)} · ${pagination}`;
  }
  return `${bets.rows.length} bets · ${pagination}`;
}

function EmptyBets({ bets }: { bets: BetsWindow }) {
  if (bets.total === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="No bets placed yet"
        detail="the ledger has not placed a bet"
      />
    );
  }
  if (bets.total === null) {
    return (
      <EmptyState icon={Inbox} title="No bets to show" detail="the fetched page is empty" />
    );
  }
  return (
    <EmptyState
      icon={Inbox}
      title="No bets in the fetched window"
      detail="the ledger changed between the summary and the list fetch — refresh to retry"
    />
  );
}
