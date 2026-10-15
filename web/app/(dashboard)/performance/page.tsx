import type { Metadata } from "next";
import type { ReactNode } from "react";

import { EquityCurve } from "@/components/charts/EquityCurve";
import { KpiStrip } from "@/components/kpi/KpiStrip";
import { PipelineFlow } from "@/components/pipeline/PipelineFlow";
import { SectionShell } from "@/components/sections/SectionShell";
import { BetsTable } from "@/components/tables/BetsTable";
import { SignalVsExecutionTable } from "@/components/tables/SignalVsExecutionTable";
import { Panel } from "@/components/ui/Panel";
import { RefreshOnInterval } from "@/components/ui/RefreshOnInterval";
import { loadPerformanceData } from "@/lib/performance-data";
import { pipelineStages } from "@/lib/pipeline";
import { PERFORMANCE_SECTIONS } from "@/lib/sections";

export const metadata: Metadata = {
  title: "Performance · WorldCup Mission Control",
};

const IMPLEMENTED = new Set([
  "kpi-strip",
  "equity-curve",
  "pipeline",
  "signal-vs-execution",
  "bets",
]);

function Source({ children }: { children: ReactNode }) {
  return (
    <span className="text-caption text-text-tertiary">
      source <span className="tnum text-text-secondary">{children}</span>
    </span>
  );
}

export default async function PerformancePage() {
  const data = await loadPerformanceData();
  const stages = pipelineStages({
    jobs: data.jobs ?? [],
    runs: data.runs ?? [],
    data: data.data,
    now: data.now,
  });
  const pipelineActive = stages.some((stage) => stage.status === "active");

  return (
    <main role="tabpanel" aria-labelledby="tab-performance" className="flex flex-col gap-6">
      <RefreshOnInterval />
      <div>
        <h1 className="text-h1 font-semibold text-text-primary">Performance</h1>
        <p className="mt-1 text-body text-text-secondary">
          Every match, prediction, bet and outcome, plus money over time.
        </p>
      </div>

      <Panel id="kpi-strip" title="KPI strip" action={<Source>/bets/summary + /bets</Source>}>
        <KpiStrip summary={data.summary} bets={data.bets} />
      </Panel>

      <Panel
        id="equity-curve"
        title="Equity / money curve"
        action={<Source>/bets/equity-curve</Source>}
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
        action={<Source>/bets + /predictions</Source>}
      >
        <SignalVsExecutionTable bets={data.bets} predictions={data.predictions} />
      </Panel>

      <Panel id="bets" title="All bets" action={<Source>/bets</Source>}>
        <BetsTable bets={data.bets} />
      </Panel>

      {PERFORMANCE_SECTIONS.filter((section) => !IMPLEMENTED.has(section.id)).map((section) => (
        <SectionShell key={section.id} {...section} />
      ))}
    </main>
  );
}
