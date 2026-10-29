import { Bot, FlaskConical } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { EquityCurve } from "@/components/charts/EquityCurve";
import { ClvCard } from "@/components/clv/ClvCard";
import { KpiStrip } from "@/components/kpi/KpiStrip";
import { LedgerAgentVariantTabs } from "@/components/ledger/LedgerAgentVariantTabs";
import { LedgerViewTabs } from "@/components/ledger/LedgerViewTabs";
import { PipelineFlow } from "@/components/pipeline/PipelineFlow";
import { AgentBetsTable } from "@/components/tables/AgentBetsTable";
import { BetsTable } from "@/components/tables/BetsTable";
import { MatchesPredictionsTable } from "@/components/tables/MatchesPredictionsTable";
import { ResultsTable } from "@/components/tables/ResultsTable";
import { SignalVsExecutionTable } from "@/components/tables/SignalVsExecutionTable";
import { Panel } from "@/components/ui/Panel";
import { RefreshOnInterval } from "@/components/ui/RefreshOnInterval";
import { loadAgentLedgerData, type AgentLedgerData } from "@/lib/agent-data";
import { normalizeAgentVariant } from "@/lib/agent-variant";
import {
  ledgerViewBook,
  normalizeLedgerView,
  type LedgerView,
} from "@/lib/ledger-view";
import {
  loadClvViewData,
  loadPerformanceData,
  type ClvViewData,
  type PerformanceData,
} from "@/lib/performance-data";
import { pipelineStages } from "@/lib/pipeline";
import type { AgentVariant, LedgerBook } from "@/lib/types";

export const metadata: Metadata = {
  title: "Ledger · Football_Pred Mission Control",
};

function Source({ children }: { children: ReactNode }) {
  return (
    <span className="text-caption text-text-tertiary">
      source <span className="tnum text-text-secondary">{children}</span>
    </span>
  );
}

function LedgerShell({ view, children }: { view: LedgerView; children: ReactNode }) {
  return (
    <div role="tabpanel" aria-labelledby="tab-ledger" className="flex flex-col gap-6">
      <RefreshOnInterval />
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-h1 font-semibold text-text-primary">Ledger</h1>
          <p className="mt-1 text-body text-text-secondary">
            Production, shadow and agent paper books — every match, prediction, bet and
            outcome, plus CLV. No real money moves in any book.
          </p>
        </div>
        <LedgerViewTabs view={view} />
      </div>
      {children}
    </div>
  );
}

export default async function LedgerPage({
  searchParams,
}: {
  searchParams: Promise<{ book?: string; view?: string; variant?: string }>;
}) {
  const {
    book: requestedBook,
    view: requestedView,
    variant: requestedVariant,
  } = await searchParams;
  const view = normalizeLedgerView(requestedView, requestedBook);

  if (view === "clv") {
    const data = await loadClvViewData();
    return (
      <LedgerShell view={view}>
        <ClvView data={data} />
      </LedgerShell>
    );
  }

  if (view === "agent") {
    const variant = normalizeAgentVariant(requestedVariant);
    const data = await loadAgentLedgerData(variant);
    return (
      <LedgerShell view={view}>
        <AgentBookView variant={variant} data={data} />
      </LedgerShell>
    );
  }

  const book = ledgerViewBook(view);
  const data = await loadPerformanceData(book);
  return (
    <LedgerShell view={view}>
      <LedgerBookView view={view} book={book} data={data} />
    </LedgerShell>
  );
}

function ClvView({ data }: { data: ClvViewData }) {
  return (
    <Panel
      id="clv"
      title="CLV & Calibration"
      action={<Source>/clv/summary?book=production + /models</Source>}
    >
      <ClvCard models={data.models} summary={data.clv} book="production" />
    </Panel>
  );
}

function AgentBookView({
  variant,
  data,
}: {
  variant: AgentVariant;
  data: AgentLedgerData;
}) {
  const variantQuery = `variant=${variant}`;

  return (
    <>
      <p className="flex items-start gap-2 rounded-lg border border-status-warn bg-surface-base px-4 py-3 text-body text-text-secondary">
        <Bot className="mt-0.5 size-4 shrink-0 text-status-warn" aria-hidden />
        <span>
          Agent paper book — paper only. Production bankroll and the shadow ledger are
          unchanged.
        </span>
      </p>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-caption text-text-tertiary">Agent paper book variant</p>
        <LedgerAgentVariantTabs variant={variant} />
      </div>

      <Panel
        id="agent-kpi-strip"
        title="Agent KPI strip"
        action={
          <Source>{`/agent/summary?${variantQuery} + /agent/bets?${variantQuery}`}</Source>
        }
      >
        <KpiStrip
          summary={data.summary}
          bets={data.bets}
          source={`/agent/summary?${variantQuery}`}
        />
      </Panel>

      <Panel
        id="agent-equity-curve"
        title="Agent equity / money curve"
        action={<Source>{`/agent/equity-curve?${variantQuery}`}</Source>}
      >
        <EquityCurve
          points={data.equity}
          source={`/agent/equity-curve?${variantQuery}`}
        />
      </Panel>

      <Panel
        id="agent-bets"
        title="Agent paper bets"
        action={<Source>{`/agent/bets?${variantQuery}`}</Source>}
      >
        <AgentBetsTable bets={data.bets} />
      </Panel>

      <p className="text-body text-text-secondary">
        Agent decisions are audited on the Agent tab.{" "}
        <Link
          href={`/agent?variant=${variant}`}
          className="text-accent-signal underline decoration-accent-signal underline-offset-4"
        >
          Open the {variant === "abc" ? "A+B+C" : "A-only"} decision audit
        </Link>
        .
      </p>
    </>
  );
}

function LedgerBookView({
  view,
  book,
  data,
}: {
  view: "production" | "shadow";
  book: LedgerBook;
  data: PerformanceData;
}) {
  const bookQuery = `?book=${book}`;
  const stages = pipelineStages({
    jobs: data.jobs,
    runs: data.runs,
    data: data.data,
    now: data.now,
  });
  const pipelineActive = stages.some((stage) => stage.status === "active");

  return (
    <>
      {view === "shadow" ? (
        <p className="flex items-start gap-2 rounded-lg border border-status-warn bg-surface-base px-4 py-3 text-body text-text-secondary">
          <FlaskConical className="mt-0.5 size-4 shrink-0 text-status-warn" aria-hidden />
          <span>Shadow ledger — paper only. Production bankroll is unchanged.</span>
        </p>
      ) : null}

      <Panel
        id="kpi-strip"
        title="KPI strip"
        action={<Source>{`/bets/summary${bookQuery} + /bets${bookQuery}`}</Source>}
      >
        <KpiStrip summary={data.summary} bets={data.bets} />
      </Panel>

      <Panel
        id="equity-curve"
        title="Equity / money curve"
        action={<Source>{`/bets/equity-curve${bookQuery}`}</Source>}
      >
        <EquityCurve points={data.equity} />
      </Panel>

      <Panel
        id="pipeline"
        title="AI pipeline"
        variant={pipelineActive ? "accent" : "default"}
        action={<Source>/ops/jobs + /ops/runs + /ops/data</Source>}
      >
        <PipelineFlow jobs={data.jobs} runs={data.runs} data={data.data} now={data.now} />
      </Panel>

      <Panel
        id="signal-vs-execution"
        title="Signal vs execution price"
        action={<Source>{`/bets${bookQuery} + /predictions`}</Source>}
      >
        <SignalVsExecutionTable bets={data.bets} predictions={data.predictions} />
      </Panel>

      <Panel id="bets" title="All bets" action={<Source>{`/bets${bookQuery}`}</Source>}>
        <BetsTable bets={data.bets} book={book} />
      </Panel>

      <Panel
        id="matches-predictions"
        title="Matches x predictions"
        action={<Source>{`/predictions + /bets${bookQuery}`}</Source>}
      >
        <MatchesPredictionsTable predictions={data.predictions} bets={data.bets} />
      </Panel>

      <Panel id="results" title="Results" action={<Source>/results</Source>}>
        <ResultsTable results={data.results} />
      </Panel>
    </>
  );
}
