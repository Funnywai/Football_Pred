// Log level handling for the live log stream. The API accepts exactly these five levels
// (app/api/ops.py _LEVELS) and filters at or above the requested level.

export const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;

export type LogLevel = (typeof LOG_LEVELS)[number];

export type LogLevelKind = "debug" | "info" | "warning" | "error" | "critical" | "unknown";

/** Normalise a searchParams value to a level the API accepts; anything else means no filter. */
export function normalizeLogLevel(value: unknown): LogLevel | null {
  if (typeof value !== "string") return null;
  const upper = value.toUpperCase();
  return LOG_LEVELS.find((level) => level === upper) ?? null;
}

export function logLevelKind(level: string): LogLevelKind {
  switch (level.toUpperCase()) {
    case "DEBUG":
      return "debug";
    case "INFO":
      return "info";
    case "WARNING":
      return "warning";
    case "ERROR":
      return "error";
    case "CRITICAL":
      return "critical";
    default:
      return "unknown";
  }
}
