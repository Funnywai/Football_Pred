import { StatusPill, type StatusVariant } from "@/components/ui/StatusPill";
import { formatRelative } from "@/lib/format";
import type { PipelineStage, StageStatus } from "@/lib/pipeline";

const STATUS_VARIANT: Record<StageStatus, StatusVariant> = {
  active: "running",
  success: "success",
  failed: "failed",
  ageing: "ageing",
  stale: "stale",
  "never-tracked": "never-tracked",
};

export interface PipelineNodeProps {
  stage: PipelineStage;
  active: boolean;
  settled: boolean;
  now: Date;
}

export function PipelineNode({ stage, active, settled, now }: PipelineNodeProps) {
  const border = active
    ? "border-2 border-accent-signal"
    : settled
      ? "border border-accent-mint/60"
      : "border border-border-default";
  const lastAction = formatRelative(stage.lastActionAt, now);
  return (
    <div
      className={`flex min-w-0 flex-1 flex-col gap-2 rounded-lg bg-surface-base px-4 py-4 ${border} ${
        active ? "node-ignite" : ""
      }`}
      aria-label={`${stage.label}: ${stage.status}, last action ${lastAction}`}
    >
      <span
        className={`text-overline uppercase ${active ? "text-accent-signal" : "text-text-secondary"}`}
      >
        {stage.label}
      </span>
      <StatusPill variant={STATUS_VARIANT[stage.status]} live={active} />
      <span className="text-caption text-text-tertiary">{lastAction}</span>
      <span className="text-caption text-text-tertiary">{stage.detail}</span>
    </div>
  );
}
