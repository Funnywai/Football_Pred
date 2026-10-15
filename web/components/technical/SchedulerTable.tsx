import { CalendarClock } from "lucide-react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusPill, type StatusVariant } from "@/components/ui/StatusPill";
import { formatCount, formatDateTime } from "@/lib/format";
import type { StageStatus } from "@/lib/pipeline";
import { schedulerRows, type SchedulerRow } from "@/lib/scheduler";
import type { OpsJob, OpsRun } from "@/lib/types";

const STAGE_PILL: Record<StageStatus, StatusVariant> = {
  active: "running",
  success: "success",
  failed: "failed",
  ageing: "ageing",
  stale: "stale",
  overdue: "overdue",
  "never-tracked": "never-tracked",
  unavailable: "unavailable",
};

export interface SchedulerTableProps {
  jobs: OpsJob[] | null;
  runs: OpsRun[] | null;
  now: Date;
}

export function SchedulerTable({ jobs, runs, now }: SchedulerTableProps) {
  if (jobs === null) {
    return (
      <EmptyState
        icon={CalendarClock}
        title="Scheduler unavailable"
        detail="the API did not return /ops/jobs"
      />
    );
  }
  if (jobs.length === 0) {
    return (
      <EmptyState
        icon={CalendarClock}
        title="No scheduled jobs"
        detail="the scheduler is disabled or not started"
      />
    );
  }

  const rows = schedulerRows(jobs, runs ?? [], now);
  const columns: Column<SchedulerRow>[] = [
    {
      key: "job",
      header: "Job",
      render: (row) => <span className="font-mono">{row.job.id}</span>,
    },
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <span className="flex flex-col items-start gap-1">
          <StatusPill variant={STAGE_PILL[row.status]} />
          <span className="block max-w-48 whitespace-normal text-caption text-text-tertiary">
            {row.detail}
          </span>
        </span>
      ),
    },
    {
      key: "trigger",
      header: "Trigger",
      render: (row) => (
        <span className="font-mono text-caption text-text-secondary">{row.job.trigger}</span>
      ),
    },
    {
      key: "next",
      header: "Next run",
      render: (row) => <span className="tnum">{formatDateTime(row.job.next_run_time)}</span>,
    },
    {
      key: "finished",
      header: "Last finished",
      render: (row) => (
        <span className="tnum">{formatDateTime(row.job.last_run?.finished_at ?? null)}</span>
      ),
    },
    {
      key: "records",
      header: "Records",
      numeric: true,
      render: (row) => {
        const records = row.job.last_run?.records_upserted ?? null;
        return records === null ? "—" : formatCount(records);
      },
    },
    {
      key: "error",
      header: "Error",
      render: (row) => {
        const error = row.job.last_run?.error ?? null;
        return error === null ? (
          "—"
        ) : (
          <span className="block max-w-48 whitespace-normal break-words text-status-neg">
            {error}
          </span>
        );
      },
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(row) => row.job.id}
        caption="Scheduled jobs"
      />
      <p className="text-caption text-text-tertiary">
        prune_odds does not record ingestion runs, so its last run always reads never tracked.
        {runs === null ? " stuck-run detection unavailable (/ops/runs unreachable)." : ""}
      </p>
    </div>
  );
}
