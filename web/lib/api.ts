import "server-only";

import type {
  Bet,
  Calibration,
  Equity,
  Overview,
  Prediction,
  Technical,
} from "./types";

export const API_BASE_URL = (process.env.API_BASE_URL ?? "http://api:8000").replace(
  /\/+$/,
  "",
);

const REQUEST_TIMEOUT_MS = 8_000;

export interface EndpointResult<T> {
  data: T | null;
  error: string | null;
}

export interface DashboardData {
  overview: EndpointResult<Overview>;
  predictions: EndpointResult<Prediction[]>;
  bets: EndpointResult<Bet[]>;
  equity: EndpointResult<Equity>;
  calibration: EndpointResult<Calibration>;
  technical: EndpointResult<Technical>;
}

type PayloadKind = "array" | "object";

function describeFailure(error: unknown): string {
  if (error instanceof Error) {
    if (error.name === "TimeoutError" || error.name === "AbortError") {
      return `API timed out after ${REQUEST_TIMEOUT_MS / 1000}s`;
    }
    if (error.message.includes("ECONNREFUSED")) {
      return `API unreachable at ${API_BASE_URL}`;
    }
    if (error.message === "fetch failed") {
      return `API unreachable at ${API_BASE_URL}`;
    }
    return error.message;
  }
  return "Unknown API failure";
}

async function getJson<T>(
  path: string,
  kind: PayloadKind,
): Promise<EndpointResult<T>> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });

    if (!response.ok) {
      return {
        data: null,
        error: `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`,
      };
    }

    const payload: unknown = await response.json();
    if (kind === "array" && !Array.isArray(payload)) {
      return { data: null, error: "Unexpected payload: expected a JSON array" };
    }
    if (kind === "object" && (payload === null || typeof payload !== "object" || Array.isArray(payload))) {
      return { data: null, error: "Unexpected payload: expected a JSON object" };
    }

    return { data: payload as T, error: null };
  } catch (error) {
    return { data: null, error: describeFailure(error) };
  }
}

/**
 * Fetch every dashboard endpoint in parallel. Failures are isolated per panel so a
 * single degraded endpoint never takes down the page.
 */
export async function getDashboardData(): Promise<DashboardData> {
  const [overview, predictions, bets, equity, calibration, technical] =
    await Promise.all([
      getJson<Overview>("/dashboard/overview", "object"),
      getJson<Prediction[]>("/dashboard/predictions?limit=50", "array"),
      getJson<Bet[]>("/dashboard/bets?limit=100", "array"),
      getJson<Equity>("/dashboard/equity", "object"),
      getJson<Calibration>("/dashboard/calibration", "object"),
      getJson<Technical>("/dashboard/technical", "object"),
    ]);

  return { overview, predictions, bets, equity, calibration, technical };
}
