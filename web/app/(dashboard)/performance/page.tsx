import { FlaskConical } from "lucide-react";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { EquityCurve } from "@/components/charts/EquityCurve";
import { ClvCard } from "@/components/clv/ClvCard";
import { KpiStrip } from "@/components/kpi/KpiStrip";
import { LedgerBookToggle } from "@/components/ledger/LedgerBookToggle";
import { PipelineFlow } from "@/components/pipeline/PipelineFlow";
import { BetsTable } from "@/components/tables/BetsTable";
import { MatchesPredictionsTable } from "@/components/tables/MatchesPredictionsTable";
import { ResultsTable } from "@/components/tables/ResultsTable";
import { SignalVsExecutionTable } from "@/components/tables/SignalVsExecutionTable";
import { Panel } from "@/components/ui/Panel";
import { RefreshOnInterval } from "@/components/ui/RefreshOnInterval";
import { normalizeLedgerBook } from "@/lib/ledger";
import { loadPerformanceData } from "@/lib/performance-data";
import { pipelineStages } from "@/lib/pipeline";

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

export default async function PerformancePage({
  searchParams,
}: {
  searchParams: Promise<{ book?: string }>;
}) {
  const { book: requestedBook } = await searchParams;
  const book = normalizeLedgerBook(requestedBook);
  const data = await loadPerformanceData(book);
  const bookQuery = book === "shadow" ? "?book=shadow" : "";
  const stages = pipelineStages({
    jobs: data.jobs,
    runs: data.runs,
    data: data.data,
    now: data.now,
  });
  const pipelineActive = stages.some((stage) => stage.status === "active");

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
        <LedgerBookToggle book={book} />
      </div>

      {book === "shadow" ? (
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

      <Panel
        id="bets"
        title="All bets"
        action={<Source>{`/bets${bookQuery}`}</Source>}
      >
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

      <Panel
        id="clv"
        title="CLV card"
        action={<Source>{`/clv/summary${bookQuery} + /models`}</Source>}
      >
        <ClvCard models={data.models} summary={data.clv} book={book} />
      </Panel>
    </div>
  );
}
