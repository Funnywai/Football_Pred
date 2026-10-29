"use client";

import { ArrowDown, ArrowUp, Inbox, SearchX } from "lucide-react";

import { BetStatusPill } from "@/components/ui/BetStatusPill";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { Note } from "@/components/ui/Note";
import { RevealFooter } from "@/components/ui/RevealFooter";
import { SearchInput } from "@/components/ui/SearchInput";
import { TermTip } from "@/components/ui/TermTip";
import { betsWindowPhrase, isTruncated, type BetsWindow } from "@/lib/bets-window";
import {
  formatDateTime,
  formatHkd,
  formatOdds,
  formatPercent,
  formatSignedHkd,
} from "@/lib/format";
import { matchesQuery } from "@/lib/row-search";
import type { Bet, LedgerBook } from "@/lib/types";
import { REVEAL_INITIAL, useRowReveal } from "@/lib/use-row-reveal";

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
  { key: "odds", header: <TermTip term="execution">Odds</TermTip>, numeric: true, render: (bet) => formatOdds(bet.odds) },
  {
    key: "edge",
    header: <TermTip term="edge">Edge</TermTip>,
    numeric: true,
    render: (bet) => (bet.edge === null ? "—" : formatPercent(bet.edge)),
  },
  { key: "stake", header: <TermTip term="stake">Stake</TermTip>, numeric: true, render: (bet) => formatHkd(bet.stake) },
  {
    key: "payout",
    header: <TermTip term="payout">Payout</TermTip>,
    numeric: true,
    render: (bet) => (bet.payout === null ? "—" : formatHkd(bet.payout)),
  },
  {
    key: "profit",
    header: <TermTip term="profit">Profit</TermTip>,
    numeric: true,
    render: (bet) => (bet.profit === null ? "—" : <ProfitCell value={bet.profit} />),
  },
  { key: "status", header: <TermTip term="status">Status</TermTip>, render: (bet) => <BetStatusPill status={bet.status} /> },
  { key: "placed", header: "Placed", render: (bet) => formatDateTime(bet.placed_at) },
];

function betMatches(bet: Bet, query: string): boolean {
  return matchesQuery(
    [bet.home_team, bet.away_team, bet.league_code, bet.target, bet.outcome, bet.status],
    query,
  );
}

export interface BetsTableProps {
  bets: BetsWindow | null;
  book?: LedgerBook;
  copy?: "ledger" | "agent";
}

export function BetsTable({ bets, book = "production", copy = "ledger" }: BetsTableProps) {
  const reveal = useRowReveal(bets?.rows ?? [], betMatches);

  if (bets === null) {
    if (copy === "agent") {
      return (
        <EmptyState
          icon={Inbox}
          title="Agent bets unavailable"
          detail="the API did not return /agent/bets"
        />
      );
    }
    return (
      <EmptyState icon={Inbox} title="Bets unavailable" detail="the API did not return /bets" />
    );
  }
  if (bets.rows.length === 0) {
    return <EmptyBets bets={bets} book={book} copy={copy} />;
  }

  return (
    <div className="flex flex-col gap-3">
      <SearchInput
        label="Search bets"
        scope={`searches the ${bets.rows.length} rows in this window`}
        value={reveal.query}
        onChange={reveal.setQuery}
        onClear={reveal.clear}
      />
      <Note>
        odds is the execution price (the latest pre-kickoff HKJC snapshot at placement);
        edge is measured at that price.
      </Note>
      <DataTable
        columns={COLUMNS}
        rows={reveal.shown}
        rowKey={(bet) => bet.id}
        caption={
          copy === "agent"
            ? "Agent paper book bets (paper only)."
            : book === "shadow"
              ? "All shadow ledger bets (paper only)."
              : "All ledger bets"
        }
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
        base={windowSentence(bets)}
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

// The footer never states a fetched count as a total: a truncated window names the slice
// it shows, and the oldest-page fallback names its missing summary.
function windowSentence(bets: BetsWindow): string {
  if (!bets.newestFirst) {
    return `showing the oldest ${bets.rows.length} bets · /bets/summary unavailable`;
  }
  if (isTruncated(bets)) return `showing ${betsWindowPhrase(bets)}`;
  return `${bets.rows.length} bets`;
}

function EmptyBets({
  bets,
  book,
  copy,
}: {
  bets: BetsWindow;
  book: LedgerBook;
  copy: "ledger" | "agent";
}) {
  if (bets.total === 0) {
    if (copy === "agent") {
      return (
        <EmptyState
          icon={Inbox}
          title="No agent bets yet"
          detail="the agent paper book has not placed a bet"
        />
      );
    }
    if (book === "shadow") {
      return <EmptyState icon={Inbox} title="Shadow ledger has not placed a bet." />;
    }
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
      <EmptyState icon={Inbox} title="No bets to show" detail="the fetched window is empty" />
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
