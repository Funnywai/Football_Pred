import { asNumber } from "./format";

export interface CalibrationBin {
  label: string;
  predicted: number | null;
  observed: number | null;
  count: number | null;
}

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function firstNumber(record: UnknownRecord, keys: string[]): number | null {
  for (const key of keys) {
    const parsed = asNumber(record[key] as number | string | null | undefined);
    if (parsed !== null) return parsed;
  }
  return null;
}

function firstString(record: UnknownRecord, keys: string[]): string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number") return String(value);
  }
  return null;
}

/** A bucket label such as "0.2-0.3" also yields its midpoint for the x position. */
function midpointFromLabel(label: string | null): number | null {
  if (!label) return null;
  const numbers = label.match(/\d+(?:\.\d+)?/g)?.map(Number) ?? [];
  if (numbers.length === 0) return null;
  if (numbers.length === 1) return numbers[0] ?? null;
  const first = numbers[0];
  const second = numbers[1];
  if (first === undefined || second === undefined) return null;
  return (first + second) / 2;
}

function binFromEntry(entry: UnknownRecord, index: number, key?: string): CalibrationBin | null {
  const predicted = firstNumber(entry, [
    "predicted",
    "predicted_probability",
    "forecast",
    "expected",
    "mean_predicted",
    "probability",
    "confidence",
    "p",
  ]);
  const observed = firstNumber(entry, [
    "observed",
    "observed_frequency",
    "actual",
    "frequency",
    "outcome_rate",
    "empirical",
    "accuracy",
    "y",
  ]);
  const count = firstNumber(entry, ["count", "n", "sample_count", "samples", "support", "total"]);
  const label = firstString(entry, ["bin", "bucket", "label", "range", "key"]) ?? key ?? `bin ${index + 1}`;
  if (predicted === null && observed === null) return null;
  return {
    label,
    predicted: predicted ?? midpointFromLabel(label),
    observed,
    count,
  };
}

/**
 * The backend's `calibration` payload is not fully specified. Accept an array of
 * bins, a `{bins: [...]}` wrapper, or a bucket-keyed object, and ignore anything
 * that cannot be read as a bin.
 */
export function extractCalibrationBins(value: unknown): CalibrationBin[] {
  if (Array.isArray(value)) {
    return value
      .map((entry, index) => (isRecord(entry) ? binFromEntry(entry, index) : null))
      .filter((entry): entry is CalibrationBin => entry !== null)
      .slice(0, 24);
  }
  if (!isRecord(value)) return [];

  const nested = value.bins ?? value.items ?? value.buckets ?? value.calibration;
  if (Array.isArray(nested)) return extractCalibrationBins(nested);

  const entries: CalibrationBin[] = [];
  let index = 0;
  for (const [key, entry] of Object.entries(value)) {
    if (!isRecord(entry)) continue;
    const bin = binFromEntry(entry, index, key);
    if (bin) entries.push(bin);
    index += 1;
  }
  return entries.slice(0, 24);
}

/** Map a 0–1 ratio (or an already-percentage value) to 0–100 for the bin axis. */
export function toAxisPercent(value: number | null): number | null {
  if (value === null) return null;
  const points = Math.abs(value) <= 1 ? value * 100 : value;
  return Math.min(100, Math.max(0, points));
}

export function hasCalibrationData(value: unknown): boolean {
  return extractCalibrationBins(value).some(
    (bin) => bin.predicted !== null || bin.observed !== null,
  );
}
