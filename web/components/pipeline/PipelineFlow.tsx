import { Workflow } from "lucide-react";

import { ChartTableFallback } from "@/components/charts/ChartTableFallback";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatRelative } from "@/lib/format";
import { pipelineStages } from "@/lib/pipeline";
import type { OpsData, OpsJob, OpsRun } from "@/lib/types";

import { PipelineNode } from "./PipelineNode";

export interface PipelineFlowProps {
  jobs: OpsJob[] | null;
  runs: OpsRun[] | null;
  data: OpsData | null;
  now: Date;
}

export function PipelineFlow({ jobs, runs, data, now }: PipelineFlowProps) {
  if (jobs === null && data === null) {
    return (
      <EmptyState
        icon={Workflow}
        title="Pipeline unavailable"
        detail="the API did not return /ops/jobs or /ops/data"
      />
    );
  }

  const stages = pipelineStages({ jobs, runs, data, now });
  const activeIndex = stages.findIndex((stage) => stage.status === "active");

  return (
    <div className="flex flex-col gap-4">
      <ol className="flex flex-col gap-2 lg:flex-row lg:items-stretch lg:gap-0">
        {stages.map((stage, index) => (
          <li
            key={`${stage.id}-${stage.status}`}
            className="flex flex-1 items-stretch"
          >
            {index > 0 ? (
              <span
                aria-hidden
                className="hidden w-6 shrink-0 self-center border-t border-border-hairline lg:block"
              />
            ) : null}
            <PipelineNode
              stage={stage}
              active={index === activeIndex}
              settled={index === activeIndex - 1 && stage.status === "success"}
              now={now}
            />
          </li>
        ))}
      </ol>
      <ChartTableFallback
        caption="Pipeline stages"
        columns={["Stage", "Status", "Last action"]}
        rows={stages.map((stage) => [
          stage.label,
          stage.status,
          formatRelative(stage.lastActionAt, now),
        ])}
      />
    </div>
  );
}
