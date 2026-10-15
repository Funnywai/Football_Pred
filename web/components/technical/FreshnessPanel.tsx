import { Activity } from "lucide-react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusPill, type StatusVariant } from "@/components/ui/StatusPill";
import { formatDateTime, formatRelative } from "@/lib/format";
import {
  formatDuration,
  freshnessRows,
  type FreshnessRow,
  type FreshnessRowState,
} from "@/lib/freshness";
import type { OpsData, OpsRun } from "@/lib/types";

const STATE_PILL: Record<FreshnessRowState, { variant: StatusVariant; label: string }> = {
  healthy: { variant: "success", label: "fresh" },
  degraded: { variant: "ageing", label: "ageing" },
  stale: { variant: "stale", label: "stale" },
  "never-tracked": { variant: "never-tracked", label: "never tracked" },
  unavailable: { variant: "unavailable", label: "unavailable" },
};

export interface FreshnessPanelProps {
  data: OpsData | null;
  runs: OpsRun[] | null;
  now: Date;
}

export function FreshnessPanel({ data, runs, now }: FreshnessPanelProps) {
  if (data === null) {
    return (
      <EmptyState
        icon={Activity}
        title="Freshness unavailable"
        detail="the API did not return /ops/data"
      />
    );
  }

  const rows = freshnessRows(data, runs, now);
  const columns: Column<FreshnessRow>[] = [
    {
      key: "arrival",
      header: "Arrival",
      render: (row) => (
        <span className="flex flex-col gap-1">
          <span className="text-text-primary">{row.label}</span>
          <span className="font-mono text-caption text-text-tertiary">{row.source}</span>
        </span>
      ),
    },
    {
      key: "state",
      header: "State",
      render: (row) => (
        <StatusPill variant={STATE_PILL[row.state].variant} label={STATE_PILL[row.state].label} />
      ),
    },
    {
      key: "age",
      header: "Age",
      render: (row) => <span className="tnum">{formatRelative(row.iso, now)}</span>,
    },
    {
      key: "threshold",
      header: "Threshold",
      render: (row) => (
        <span className="tnum text-caption text-text-secondary">
          degraded &gt; {formatDuration(row.thresholds.degradedMs)} · stale &gt;{" "}
          {formatDuration(row.thresholds.staleMs)}
        </span>
      ),
    },
    {
      key: "raw",
      header: "Last arrival (UTC)",
      render: (row) => <span className="tnum">{formatDateTime(row.iso)}</span>,
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(row) => row.id}
      caption="Data freshness arrivals"
    />
  );
}
