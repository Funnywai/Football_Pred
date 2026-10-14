import { Cpu } from "lucide-react";

import type { HeaderThinking } from "@/lib/header-model";

export interface PipelineIndicatorProps {
  thinking: HeaderThinking;
}

export function PipelineIndicator({ thinking }: PipelineIndicatorProps) {
  return (
    <div
      role="status"
      aria-label={
        thinking.active
          ? `System is thinking: ${thinking.stage} stage active`
          : "System is idle"
      }
      className="flex items-center gap-2"
    >
      <Cpu
        className={`size-3.5 ${thinking.active ? "text-accent-signal" : "text-text-tertiary"}`}
        aria-hidden
      />
      <span className="text-caption text-text-secondary">
        {thinking.active ? "system is thinking" : "system idle"}
      </span>
      {thinking.active && thinking.stage !== null ? (
        <span
          className="relative h-1 w-16 overflow-hidden rounded-pill bg-surface-raised"
          aria-hidden
        >
          <span className="absolute inset-y-0 left-0 w-1/3 rounded-pill bg-accent-signal motion-safe:animate-[thinking-sweep_1.4s_ease-in-out_infinite]" />
        </span>
      ) : null}
    </div>
  );
}
