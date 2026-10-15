import "server-only";

import type {
  Bet,
  BetSummary,
  EquityPoint,
  Match,
  ModelVersion,
  Prediction,
  Result,
} from "./types";

// Server-side-only API access. `server-only` makes importing this module from a Client
// Component a build error, so the API base URL and every response stay on the server and
// never reach the browser bundle. The FastAPI app has no CORS and is never called from
// the client.
const DEFAULT_API_BASE_URL = "http://app:8000";

const REQUEST_TIMEOUT_MS = 5000;

export function apiBaseUrl(): string {
  return process.env.API_BASE_URL ?? DEFAULT_API_BASE_URL;
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string };

/**
 * GET a JSON endpoint. Never throws: an unreachable API, a non-2xx status, or a timeout
 * all resolve to `{ ok: false }` so Server Components can degrade gracefully and the
 * production build never fails when the API is down.
 */
export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  const url = `${apiBaseUrl()}${path}`;
  try {
    const response = await fetch(url, {
      cache: "no-store",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      return { ok: false, error: `HTTP ${response.status}` };
    }
    const data = (await response.json()) as T;
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "request failed" };
  }
}

// ---- Data-route fetchers (app/api/routes.py) ----

export const getBetSummary = (): Promise<ApiResult<BetSummary>> => apiGet("/bets/summary");

export const getEquityCurve = (): Promise<ApiResult<EquityPoint[]>> =>
  apiGet("/bets/equity-curve");

export const getBets = (limit = 50): Promise<ApiResult<Bet[]>> => apiGet(`/bets?limit=${limit}`);

// `champion_only` defaults to true on the API. The signal-vs-execution join needs the
// prediction a bet was actually placed from, which may belong to a since-replaced model,
// so that view fetches with champion_only=false.
export const getPredictions = (
  limit = 50,
  championOnly = true,
): Promise<ApiResult<Prediction[]>> =>
  apiGet(`/predictions?limit=${limit}&champion_only=${championOnly}`);

export const getModels = (): Promise<ApiResult<ModelVersion[]>> => apiGet("/models");

export const getMatches = (limit = 100): Promise<ApiResult<Match[]>> =>
  apiGet(`/matches?limit=${limit}`);

export const getResults = (limit = 100): Promise<ApiResult<Result[]>> =>
  apiGet(`/results?limit=${limit}`);
