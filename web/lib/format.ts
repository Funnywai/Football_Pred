// Pure display formatters. No server-only import: these are safe in any component and
// are unit-tested directly. All numbers render with tabular numerals at the call site.

const HKD = new Intl.NumberFormat("en-HK", {
  style: "currency",
  currency: "HKD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const COUNT = new Intl.NumberFormat("en-US");

// The system runs in UTC (compose sets TZ=UTC); format in UTC so server output is stable.
const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  timeZone: "UTC",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatHkd(value: number): string {
  return HKD.format(value);
}

export function formatSignedHkd(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${HKD.format(Math.abs(value))}`;
}

export function formatPercent(fraction: number, digits = 1): string {
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function formatSignedPercent(fraction: number, digits = 1): string {
  const sign = fraction > 0 ? "+" : fraction < 0 ? "-" : "";
  return `${sign}${(Math.abs(fraction) * 100).toFixed(digits)}%`;
}

export function formatOdds(value: number): string {
  return value.toFixed(2);
}

export function formatCount(value: number): string {
  return COUNT.format(value);
}

export function formatDateTime(iso: string | null): string {
  if (iso === null) return "—";
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return "—";
  return DATE_TIME.format(parsed);
}

export function formatRelative(iso: string | null, now: Date = new Date()): string {
  if (iso === null) return "never";
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return "never";
  const diff = now.getTime() - parsed;
  if (diff < 0) return "just now";
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
