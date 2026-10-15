import type { Metadata } from "next";
import type { ReactNode } from "react";

import { DbSizeTable } from "@/components/technical/DbSizeTable";
import { EnvironmentPanel } from "@/components/technical/EnvironmentPanel";
import { FreshnessPanel } from "@/components/technical/FreshnessPanel";
import { IngestionRunsTimeline } from "@/components/technical/IngestionRunsTimeline";
import { LogStream } from "@/components/technical/LogStream";
import { ModelTimeline } from "@/components/technical/ModelTimeline";
import { SchedulerTable } from "@/components/technical/SchedulerTable";
import { Panel } from "@/components/ui/Panel";
import { normalizeLogLevel } from "@/lib/logs";
import { LOGS_LIMIT, RUNS_LIMIT, loadTechnicalData } from "@/lib/technical-data";

export const metadata: Metadata = {
  title: "Technical · WorldCup Mission Control",
};

function Source({ children }: { children: ReactNode }) {
  return (
    <span className="text-caption text-text-tertiary">
      source <span className="tnum text-text-secondary">{children}</span>
    </span>
  );
}

export default async function TechnicalPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const level = normalizeLogLevel(params.level);
  const data = await loadTechnicalData(level);
  const runsTotal = data.data?.table_counts.ingestion_runs ?? null;

  return (
    <main role="tabpanel" aria-labelledby="tab-technical" className="flex flex-col gap-6">
      <div>
        <h1 className="text-h1 font-semibold text-text-primary">Technical</h1>
        <p className="mt-1 text-body text-text-secondary">
          Logs, scheduler, ingestion, freshness, database size, model versions and environment.
        </p>
      </div>

      <Panel id="log-stream" title="Live log stream" action={<Source>/ops/logs</Source>}>
        <LogStream logs={data.logs} level={level} limit={LOGS_LIMIT} />
      </Panel>

      <Panel
        id="scheduler"
        title="Scheduler table"
        action={<Source>/ops/jobs + /ops/runs</Source>}
      >
        <SchedulerTable jobs={data.jobs} runs={data.runs} now={data.now} />
      </Panel>

      <Panel
        id="ingestion-timeline"
        title="Ingestion runs timeline"
        action={<Source>/ops/runs</Source>}
      >
        <IngestionRunsTimeline runs={data.runs} total={runsTotal} limit={RUNS_LIMIT} />
      </Panel>

      <Panel
        id="freshness"
        title="Data freshness panel"
        action={<Source>/ops/data + /ops/runs</Source>}
      >
        <FreshnessPanel data={data.data} runs={data.runs} now={data.now} />
      </Panel>

      <Panel id="db-size" title="DB size table" action={<Source>/ops/data</Source>}>
        <DbSizeTable data={data.data} />
      </Panel>

      <Panel
        id="model-timeline"
        title="Model version timeline"
        action={<Source>/models + /ops/data</Source>}
      >
        <ModelTimeline models={data.models} opsVersions={data.data?.model_versions ?? null} />
      </Panel>

      <Panel id="environment" title="Environment" action={<Source>/ops/status</Source>}>
        <EnvironmentPanel status={data.status} />
      </Panel>
    </main>
  );
}
