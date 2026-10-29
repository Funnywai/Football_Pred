"use client";

import { Check, Inbox, Minus, SearchX } from "lucide-react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { RevealFooter } from "@/components/ui/RevealFooter";
import { SearchInput } from "@/components/ui/SearchInput";
import { TermTip } from "@/components/ui/TermTip";
import { formatDateTime, formatHkd, formatPercent } from "@/lib/format";
import { matchesQuery } from "@/lib/row-search";
import type { AgentDecision } from "@/lib/types";
import { REVEAL_INITIAL, useRowReveal } from "@/lib/use-row-reveal";

function actionLabel(action: string): string {
  if (action === "bet") return "bet";
  if (action === "no_bet") return "no bet";
  return action;
}

function ActionCell({ action }: { action: string }) {
  const isBet = action === "bet";
  return (
    <span
      className={`inline-flex items-center gap-1 ${
        isBet ? "text-accent-mint" : "text-text-tertiary"
      }`}
    >
      {isBet ? <Check className="size-3" aria-hidden /> : <Minus className="size-3" aria-hidden />}
      {actionLabel(action)}
    </span>
  );
}

function teamsText(decision: AgentDecision): string {
  if (decision.home_team != null && decision.away_team != null) {
    return `${decision.home_team} v ${decision.away_team}`;
  }
  return `match #${decision.match_id}`;
}

const COLUMNS: Column<AgentDecision>[] = [
  { key: "run", header: "Run", render: (decision) => decision.run_id },
  {
    key: "league",
    header: "League",
    render: (decision) => decision.league_code ?? "—",
  },
  { key: "match", header: "Match", render: teamsText },
  { key: "outcome", header: "Outcome", render: (decision) => decision.outcome },
  { key: "action", header: "Action", render: (decision) => <ActionCell action={decision.action} /> },
  {
    key: "stake",
    header: <TermTip term="stake">Stake</TermTip>,
    numeric: true,
    render: (decision) => (decision.stake === null ? "—" : formatHkd(decision.stake)),
  },
  {
    key: "edge",
    header: <TermTip term="edge">Edge</TermTip>,
    numeric: true,
    render: (decision) => (decision.edge === null ? "—" : formatPercent(decision.edge)),
  },
  {
    key: "reason",
    header: "Reason",
    wrap: true,
    render: (decision) => (decision.reason === "" ? "—" : decision.reason),
  },
  {
    key: "evaluated",
    header: "Evaluated",
    render: (decision) => formatDateTime(decision.evaluated_at),
  },
];

function decisionMatches(decision: AgentDecision, query: string): boolean {
  return matchesQuery(
    [
      decision.run_id,
      decision.league_code ?? "",
      decision.home_team ?? "",
      decision.away_team ?? "",
      decision.outcome,
      decision.action,
      decision.reason,
    ],
    query,
  );
}

export interface AgentDecisionsTableProps {
  decisions: AgentDecision[] | null;
  limit: number;
}

export function AgentDecisionsTable({ decisions, limit }: AgentDecisionsTableProps) {
  const reveal = useRowReveal(decisions ?? [], decisionMatches);

  if (decisions === null) {
    return (
      <EmptyState
        icon={Inbox}
        title="Agent decisions unavailable"
        detail="the API did not return /agent/decisions"
      />
    );
  }
  if (decisions.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="No agent decisions yet"
        detail="the agent has not evaluated a match"
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <SearchInput
        label="Search agent decisions"
        scope={`searches the ${decisions.length} rows in this window`}
        value={reveal.query}
        onChange={reveal.setQuery}
        onClear={reveal.clear}
      />
      <DataTable
        columns={COLUMNS}
        rows={reveal.shown}
        rowKey={(decision) => decision.id}
        caption="Agent decisions (paper only)."
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
        base={
          decisions.length >= limit
            ? `the newest ${decisions.length} decisions`
            : `${decisions.length} decisions`
        }
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
