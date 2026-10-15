import { Boxes } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { StatusPill, type StatusVariant } from "@/components/ui/StatusPill";
import { formatDateTime } from "@/lib/format";
import {
  formatMetric,
  formatParamValue,
  metricCells,
  modelTimelineRows,
  type ModelTimelineEntry,
} from "@/lib/model-metrics";
import type { ModelVersion, OpsModelVersion } from "@/lib/types";

const MODEL_PILL: Record<string, { variant: StatusVariant; label: string }> = {
  champion: { variant: "success", label: "champion" },
  challenger: { variant: "queued", label: "challenger" },
  retired: { variant: "never-tracked", label: "retired" },
};

export interface ModelTimelineProps {
  models: ModelVersion[] | null;
  opsVersions: OpsModelVersion[] | null;
}

export function ModelTimeline({ models, opsVersions }: ModelTimelineProps) {
  if (models === null) {
    return (
      <EmptyState
        icon={Boxes}
        title="Model versions unavailable"
        detail="the API did not return /models"
      />
    );
  }
  if (models.length === 0) {
    return <EmptyState icon={Boxes} title="No model versions registered yet" />;
  }

  const entries = modelTimelineRows(models, opsVersions);
  return (
    <div className="flex flex-col gap-3">
      <ol className="divide-y divide-border-hairline">
        {entries.map((entry) => (
          <ModelRow key={entry.model.id} entry={entry} />
        ))}
      </ol>
      <p className="text-caption text-text-tertiary">
        — = metric not tracked for this target (handicap models carry brier, logloss and n
        only). Ordered by created_at, newest first.
      </p>
    </div>
  );
}

function ModelRow({ entry }: { entry: ModelTimelineEntry }) {
  const { model, params } = entry;
  const pill = MODEL_PILL[model.status] ?? { variant: "never-tracked" as const, label: model.status };
  return (
    <li className="flex flex-col gap-3 py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <StatusPill variant={pill.variant} label={pill.label} />
        <span className="font-mono text-data text-text-primary">{model.target}</span>
        <span className="text-caption text-text-tertiary">{model.algorithm}</span>
        <span className="tnum text-caption text-text-secondary">
          created {formatDateTime(model.created_at)}
        </span>
        <span className="tnum text-caption text-text-secondary">
          promoted {formatDateTime(model.promoted_at)}
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 lg:grid-cols-6">
        {metricCells(model.metrics).map((cell) => (
          <div key={cell.key}>
            <dt className="text-overline uppercase text-text-tertiary">{cell.key}</dt>
            <dd className="tnum text-data text-text-primary">
              {cell.value === null ? "—" : formatMetric(cell.key, cell.value)}
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-caption text-text-tertiary">
        artifact <span className="font-mono text-text-secondary">{model.artifact_path}</span>
      </p>
      <p className="text-caption text-text-tertiary">
        params{" "}
        {params === null ? (
          <span>unavailable (not in /ops/data)</span>
        ) : (
          <span className="font-mono text-text-secondary">
            {Object.entries(params)
              .map(([key, value]) => `${key}=${formatParamValue(value)}`)
              .join(" · ")}
          </span>
        )}
      </p>
    </li>
  );
}
