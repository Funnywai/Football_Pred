// Environment panel whitelist. Exactly five fields are read from /ops/status; the panel
// never renders the status object wholesale, so no environment value, secret, DSN or token
// can reach the DOM.

import type { OpsStatus } from "./types";

export type EnvironmentTone = "neutral" | "ok" | "down" | "warn";

export interface EnvironmentRow {
  id: string;
  label: string;
  value: string;
  tone: EnvironmentTone;
}

export function environmentRows(status: OpsStatus): EnvironmentRow[] {
  return [
    { id: "app_version", label: "App version", value: status.app_version, tone: "neutral" },
    { id: "git_sha", label: "Git SHA", value: status.git_sha, tone: "neutral" },
    {
      id: "alembic_revision",
      label: "Alembic revision",
      value: status.alembic_revision ?? "unknown",
      tone: "neutral",
    },
    {
      id: "db_ok",
      label: "DB connectivity",
      value: status.db_ok ? "connected" : "unreachable",
      tone: status.db_ok ? "ok" : "down",
    },
    {
      id: "scheduler_enabled",
      label: "Scheduler",
      value: status.scheduler_enabled ? "enabled" : "disabled",
      tone: status.scheduler_enabled ? "ok" : "warn",
    },
  ];
}
