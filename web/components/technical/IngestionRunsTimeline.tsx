import { ListTree } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { StatusPill, type StatusVariant } from "@/components/ui/StatusPill";
import { formatCount, formatDateTime } from "@/lib/format";
import { runStage, runStatusKind, runsWindowLabel, type RunStatusKind } from "@/lib/runs";
import type { OpsRun } from "@/lib/types";

// This is a list, NOT a chart: the run history renders as a dense ordered list. Do not add
// a chart fallback — there is no chart here.
const RUN_PILL: Record<RunStatusKind, StatusVariant> = {
  running: "running",
  success: "success",
  failed: "failed",
  flagged: "queued",
  unknown: "never-tracked",
};

export interface IngestionRunsTimelineProps {
  runs: OpsRun[] | null;
  total: number | null;
  limit: number;
}

export function IngestionRunsTimeline({ runs, total, limit }: IngestionRunsTimelineProps) {
  if (runs === null) {
    return (
      <EmptyState
        icon={ListTree}
        title="Runs unavailable"
        detail="the API did not return /ops/runs"
      />
    );
  }
  if (runs.length === 0) {
    return <EmptyState icon={ListTree} title="No ingestion runs recorded yet" />;
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-caption text-text-tertiary">
        {runsWindowLabel(runs, total, limit)} · run count is a row count, not a rate.
      </p>
      <ol className="divide-y divide-border-hairline">
        {runs.map((run) => (
          <RunRow key={run.id} run={run} />
        ))}
      </ol>
    </div>
  );
}

function RunRow({ run }: { run: OpsRun }) {
  const kind = runStatusKind(run.status);
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
      <StatusPill variant={RUN_PILL[kind]} label={kind === "unknown" ? run.status : undefined} />
      <span className="font-mono text-data text-text-primary">{run.job}</span>
      <span className="text-caption text-text-tertiary">{runStage(run.job)}</span>
      <span className="tnum text-caption text-text-secondary">
        {formatDateTime(run.started_at)} → {formatDateTime(run.finished_at)}
      </span>
      <span className="tnum text-caption text-text-secondary">
        {run.records_upserted === null ? "—" : `${formatCount(run.records_upserted)} records`}
      </span>
      {run.error === null ? null : (
        <span className="w-full break-words text-caption text-status-neg">{run.error}</span>
      )}
    </li>
  );
}
