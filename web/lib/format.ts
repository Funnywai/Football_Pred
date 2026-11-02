import type { Numeric } from "./types";

const HKT = "Asia/Hong_Kong";

const moneyFormatters = new Map<string, Intl.NumberFormat>();

function moneyFormatter(currency: string): Intl.NumberFormat {
  const key = currency.toUpperCase();
  const cached = moneyFormatters.get(key);
  if (cached) return cached;

  let formatter: Intl.NumberFormat;
  try {
    formatter = new Intl.NumberFormat("en-HK", {
      style: "currency",
      currency: key,
      currencyDisplay: "narrowSymbol",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  } catch {
    formatter = new Intl.NumberFormat("en-HK", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  moneyFormatters.set(key, formatter);
  return formatter;
}

/** Parse a Decimal-as-string / number into a finite number, otherwise null. */
export function asNumber(value: Numeric): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function formatMoney(
  value: Numeric,
  currency = "HKD",
  fallback = "—",
): string {
  const parsed = asNumber(value);
  if (parsed === null) return fallback;
  return moneyFormatter(currency || "HKD").format(parsed);
}

export function formatSignedMoney(
  value: Numeric,
  currency = "HKD",
  fallback = "—",
): string {
  const parsed = asNumber(value);
  if (parsed === null) return fallback;
  const formatted = moneyFormatter(currency || "HKD").format(Math.abs(parsed));
  if (parsed > 0) return `+${formatted}`;
  if (parsed < 0) return `−${formatted}`;
  return formatted;
}

export function formatNumber(
  value: Numeric,
  digits = 0,
  fallback = "—",
): string {
  const parsed = asNumber(value);
  if (parsed === null) return fallback;
  return new Intl.NumberFormat("en-HK", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(parsed);
}

/**
 * The API stores rates and ratios as Decimals (for example "-0.0423"). Values that
 * already look like percentage points (abs > 1) are passed through, so either wire
 * convention reads sensibly without guessing per field.
 */
export function toPercentPoints(value: Numeric): number | null {
  const parsed = asNumber(value);
  if (parsed === null) return null;
  return Math.abs(parsed) <= 1 ? parsed * 100 : parsed;
}

export function formatPercent(value: Numeric, digits = 1, fallback = "—"): string {
  const points = toPercentPoints(value);
  if (points === null) return fallback;
  return `${new Intl.NumberFormat("en-HK", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(points)}%`;
}

export function formatSignedPercent(
  value: Numeric,
  digits = 1,
  fallback = "—",
): string {
  const points = toPercentPoints(value);
  if (points === null) return fallback;
  const body = new Intl.NumberFormat("en-HK", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Math.abs(points));
  if (points > 0) return `+${body}%`;
  if (points < 0) return `−${body}%`;
  return `${body}%`;
}

export function formatOdds(value: Numeric, fallback = "—"): string {
  return formatNumber(value, 2, fallback);
}

export function formatFixed(value: Numeric, digits = 3, fallback = "—"): string {
  return formatNumber(value, digits, fallback);
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: HKT,
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatKickoff(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: HKT,
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: HKT,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatRelativeTime(
  value: string | null | undefined,
  now = new Date(),
): string {
  const date = parseDate(value);
  if (!date) return "—";
  const deltaSeconds = Math.round((date.getTime() - now.getTime()) / 1000);
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const thresholds: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, seconds] of thresholds) {
    if (Math.abs(deltaSeconds) >= seconds) {
      return formatter.format(Math.round(deltaSeconds / seconds), unit);
    }
  }
  return formatter.format(deltaSeconds, "second");
}

export interface ProbabilityPercents {
  H: number | null;
  D: number | null;
  A: number | null;
}

/** Convert H/D/A probabilities to percentage points regardless of wire scale. */
export function probabilitiesToPercents(
  probabilities: { H?: Numeric; D?: Numeric; A?: Numeric } | null | undefined,
): ProbabilityPercents {
  const h = asNumber(probabilities?.H);
  const d = asNumber(probabilities?.D);
  const a = asNumber(probabilities?.A);
  const values = [h, d, a].filter((item): item is number => item !== null);
  if (values.length === 0) return { H: null, D: null, A: null };
  const sum = values.reduce((total, item) => total + item, 0);
  const alreadyPercent = sum > 1.5;
  const scale = (item: number | null) =>
    item === null ? null : alreadyPercent ? item : item * 100;
  return { H: scale(h), D: scale(d), A: scale(a) };
}

export function formatProbability(value: Numeric): string {
  const percents = probabilitiesToPercents({ H: value });
  return percents.H === null ? "—" : `${percents.H.toFixed(1)}%`;
}

export type Tone = "positive" | "negative" | "accent" | "neutral" | "muted";

export function statusTone(status: string | null | undefined): Tone {
  const normalized = (status ?? "").toLowerCase();
  if (["up", "ok", "healthy", "success", "succeeded", "won", "win", "settled"].includes(normalized)) {
    return "positive";
  }
  if (["down", "error", "failed", "failure", "lost", "loss", "critical"].includes(normalized)) {
    return "negative";
  }
  if (["degraded", "warning", "stale"].includes(normalized)) {
    return "accent";
  }
  if (["not_configured", "not configured", "disabled", "skipped", "void", "push"].includes(normalized)) {
    return "muted";
  }
  if (["pending", "bet", "open", "running", "placed", "queued"].includes(normalized)) {
    return "accent";
  }
  return "neutral";
}

export function profitTone(value: Numeric): Tone {
  const parsed = asNumber(value);
  if (parsed === null) return "muted";
  if (parsed > 0) return "positive";
  if (parsed < 0) return "negative";
  return "neutral";
}

export function humanize(value: string | null | undefined, fallback = "—"): string {
  if (!value) return fallback;
  return value.replaceAll("_", " ");
}

export function shortId(value: string | null | undefined, length = 10): string {
  if (!value) return "—";
  return value.length <= length ? value : `${value.slice(0, length)}…`;
}
