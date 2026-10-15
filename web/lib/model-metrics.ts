// Model metric rendering. The API's metrics dict is untyped (app/api/schemas.py) and can
// carry nulls (app/ml/value.py returns None CLV values when no closing data exists), so a
// missing or null metric renders as "—" (not tracked), never as zero.

import { formatCount, formatPercent, formatSignedPercent } from "./format";
import type { ModelVersion, OpsModelVersion } from "./types";

export const METRIC_KEYS = [
  "brier",
  "logloss",
  "n",
  "clv_fraction",
  "clv_mean_edge",
  "clv_n",
] as const;

export interface MetricCell {
  key: string;
  value: number | null;
}

export function metricCells(metrics: Record<string, unknown>): MetricCell[] {
  const known = METRIC_KEYS.map((key) => ({ key, value: numeric(metrics[key]) }));
  const extra = Object.keys(metrics)
    .filter((key) => !METRIC_KEYS.some((knownKey) => knownKey === key))
    .map((key) => ({ key, value: numeric(metrics[key]) }));
  return [...known, ...extra];
}

function numeric(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

export function formatMetric(key: string, value: number): string {
  if (key === "n" || key === "clv_n") return formatCount(value);
  if (key === "clv_fraction") return formatPercent(value);
  if (key === "clv_mean_edge") return formatSignedPercent(value);
  return value.toFixed(4);
}

export function formatParamValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean" || value === null) {
    return String(value);
  }
  const json = JSON.stringify(value);
  return json === undefined ? "—" : json;
}

export interface ModelTimelineEntry {
  model: ModelVersion;
  params: Record<string, unknown> | null;
}

/** Newest first by created_at; params are joined from /ops/data.model_versions by id. */
export function modelTimelineRows(
  models: ModelVersion[],
  opsVersions: OpsModelVersion[] | null,
): ModelTimelineEntry[] {
  const paramsById = new Map<number, Record<string, unknown>>();
  for (const version of opsVersions ?? []) paramsById.set(version.id, version.params);
  return [...models]
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.id - a.id)
    .map((model) => ({ model, params: paramsById.get(model.id) ?? null }));
}
