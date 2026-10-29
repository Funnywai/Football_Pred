import "server-only";

import type {
  AgentDecision,
  AgentDecisionAgent,
  AgentVariant,
  Bet,
  BetSummary,
  ClvSummary,
  EquityPoint,
  LedgerBook,
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

// Every ledger read takes the book (`production` or `shadow`); the API defaults to
// production, but the dashboard always states it explicitly so a missing parameter can
// never silently change the book.
export const getBetSummary = (
  book: LedgerBook = "production",
): Promise<ApiResult<BetSummary>> =>
  apiGet(`/bets/summary?book=${encodeURIComponent(book)}`);

export const getEquityCurve = (
  book: LedgerBook = "production",
): Promise<ApiResult<EquityPoint[]>> =>
  apiGet(`/bets/equity-curve?book=${encodeURIComponent(book)}`);

// `/bets` orders by (placed_at, id) ascending; the caller passes the offset of the page
// it wants (the performance tab fetches the newest page, i.e. the tail of the list).
export const getBets = (
  limit = 50,
  offset = 0,
  book: LedgerBook = "production",
): Promise<ApiResult<Bet[]>> =>
  apiGet(
    `/bets?limit=${limit}&offset=${offset}&book=${encodeURIComponent(book)}`,
  );

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

// `source` defaults to hkjc on the API; the dashboard asks for it explicitly so the card
// never silently changes source if the server default moves.
export const getClvSummary = (
  source = "hkjc",
  book: LedgerBook = "production",
): Promise<ApiResult<ClvSummary>> =>
  apiGet(
    `/clv/summary?source=${encodeURIComponent(source)}&book=${encodeURIComponent(book)}`,
  );

// ---- /agent/* surface (app/api/routes.py) ----

// Decisions are ordered newest-first by (evaluated_at, id) on the API, so `limit` is the
// newest slice; there is no offset parameter in Phase 1.
export const getAgentDecisions = (
  limit = 100,
  agent?: AgentDecisionAgent,
): Promise<ApiResult<AgentDecision[]>> =>
  apiGet(
    `/agent/decisions?limit=${limit}${agent === undefined ? "" : `&agent=${encodeURIComponent(agent)}`}`,
  );

// Agent books live in their own namespace (`variant=a_only|abc`), never under `book=`.
export const getAgentBets = (
  limit = 50,
  offset = 0,
  variant: AgentVariant = "a_only",
): Promise<ApiResult<Bet[]>> =>
  apiGet(
    `/agent/bets?variant=${encodeURIComponent(variant)}&limit=${limit}&offset=${offset}`,
  );

export const getAgentSummary = (
  variant: AgentVariant = "a_only",
): Promise<ApiResult<BetSummary>> =>
  apiGet(`/agent/summary?variant=${encodeURIComponent(variant)}`);

export const getAgentEquityCurve = (
  variant: AgentVariant = "a_only",
): Promise<ApiResult<EquityPoint[]>> =>
  apiGet(`/agent/equity-curve?variant=${encodeURIComponent(variant)}`);
