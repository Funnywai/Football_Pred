import { FlaskConical } from "lucide-react";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { EquityCurve } from "@/components/charts/EquityCurve";
import { ClvCard } from "@/components/clv/ClvCard";
import { KpiStrip } from "@/components/kpi/KpiStrip";
import { PerformanceViewTabs } from "@/components/performance/PerformanceViewTabs";
import { PipelineFlow } from "@/components/pipeline/PipelineFlow";
import { BetsTable } from "@/components/tables/BetsTable";
import { MatchesPredictionsTable } from "@/components/tables/MatchesPredictionsTable";
import { ResultsTable } from "@/components/tables/ResultsTable";
import { SignalVsExecutionTable } from "@/components/tables/SignalVsExecutionTable";
import { Panel } from "@/components/ui/Panel";
import { RefreshOnInterval } from "@/components/ui/RefreshOnInterval";
import {
  normalizePerformanceView,
  performanceViewBook,
  type PerformanceView,
} from "@/lib/performance-view";
import {
  loadClvViewData,
  loadPerformanceData,
  type ClvViewData,
  type PerformanceData,
} from "@/lib/performance-data";
import { pipelineStages } from "@/lib/pipeline";
import type { LedgerBook } from "@/lib/types";

export const metadata: Metadata = {
  title: "Performance · Football_Pred Mission Control",
};

function Source({ children }: { children: ReactNode }) {
  return (
    <span className="text-caption text-text-tertiary">
      source <span className="tnum text-text-secondary">{children}</span>
    </span>
  );
}

function PerformanceShell({
  view,
  children,
}: {
  view: PerformanceView;
  children: ReactNode;
}) {
  return (
    <div role="tabpanel" aria-labelledby="tab-performance" className="flex flex-col gap-6">
      <RefreshOnInterval />
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-h1 font-semibold text-text-primary">Performance</h1>
          <p className="mt-1 text-body text-text-secondary">
            Every match, prediction, bet and outcome, plus money over time.
          </p>
        </div>
        <PerformanceViewTabs view={view} />
      </div>
      {children}
    </div>
  );
}

export default async function PerformancePage({
  searchParams,
}: {
  searchParams: Promise<{ book?: string; view?: string }>;
}) {
  const { book: requestedBook, view: requestedView } = await searchParams;
  const view = normalizePerformanceView(requestedView, requestedBook);

  if (view === "clv") {
    const data = await loadClvViewData();
    return (
      <PerformanceShell view={view}>
        <ClvView data={data} />
      </PerformanceShell>
    );
  }

  const book = performanceViewBook(view);
  const data = await loadPerformanceData(book);
  return (
    <PerformanceShell view={view}>
      <LedgerView view={view} book={book} data={data} />
    </PerformanceShell>
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

function LedgerView({
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
