import type { FreshnessStatus } from "@/lib/freshness";

const DOT_CLASS: Record<FreshnessStatus, string> = {
  healthy: "bg-accent-mint",
  degraded: "bg-status-warn",
  stale: "bg-status-neg",
};

export interface HeartbeatDotProps {
  status: FreshnessStatus;
  label: string;
  detail: string;
}

export function HeartbeatDot({ status, label, detail }: HeartbeatDotProps) {
  return (
    <div
      role="status"
      aria-label={`Scheduler heartbeat: ${label}. ${detail}`}
      className="flex items-center gap-2"
    >
      <span
        className={`size-2.5 rounded-pill ${DOT_CLASS[status]} ${
          status === "healthy"
            ? "motion-safe:animate-[heartbeat-pulse_2.4s_ease-in-out_infinite]"
            : ""
        }`}
        aria-hidden
      />
      <span className="text-caption text-text-secondary">
        heartbeat <span className="text-text-primary">{label}</span>
      </span>
    </div>
  );
}
