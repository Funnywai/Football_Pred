import { ServerCog } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { StatusPill, type StatusVariant } from "@/components/ui/StatusPill";
import { environmentRows, type EnvironmentTone } from "@/lib/environment";
import type { OpsStatus } from "@/lib/types";

const TONE_PILL: Record<Exclude<EnvironmentTone, "neutral">, StatusVariant> = {
  ok: "success",
  down: "failed",
  warn: "queued",
};

export interface EnvironmentPanelProps {
  status: OpsStatus | null;
}

export function EnvironmentPanel({ status }: EnvironmentPanelProps) {
  if (status === null) {
    return (
      <EmptyState
        icon={ServerCog}
        title="Environment unavailable"
        detail="the API did not return /ops/status"
      />
    );
  }

  const rows = environmentRows(status);
  return (
    <div className="flex flex-col gap-3">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-5">
        {rows.map((row) => {
          const tone = row.tone;
          return (
            <div key={row.id} className="flex flex-col gap-1">
              <dt className="text-overline uppercase text-text-tertiary">{row.label}</dt>
              <dd className="text-data text-text-primary">
                {tone === "neutral" ? (
                  <span className="font-mono">{row.value}</span>
                ) : (
                  <StatusPill variant={TONE_PILL[tone]} label={row.value} />
                )}
              </dd>
            </div>
          );
        })}
      </dl>
      <p className="text-caption text-text-tertiary">
        whitelisted fields only — no environment values, secrets, DSNs or tokens are rendered.
      </p>
    </div>
  );
}
