import "server-only";

import { getJson, type EndpointResult } from "./api";
import type { LlmPrediction, LlmResearchRun, LlmStatus } from "./llm-types";
import type { Bet, Equity } from "./types";

/**
 * Server-side read of the separate LLM lane. Uses the same `API_BASE_URL`
 * convention (and failure isolation) as the deterministic dashboard; the browser
 * never talks to the API and no credentials are exposed.
 */
export async function getLlmStatus(): Promise<EndpointResult<LlmStatus>> {
  return getJson<LlmStatus>("/llm/status", "object");
}

export async function getLlmPredictions(): Promise<EndpointResult<LlmPrediction[]>> {
  return getJson<LlmPrediction[]>("/llm/predictions?limit=200", "array");
}

export async function getLlmBets(): Promise<EndpointResult<Bet[]>> {
  return getJson<Bet[]>("/llm/bets?limit=500", "array");
}

export async function getLlmEquity(): Promise<EndpointResult<Equity>> {
  return getJson<Equity>("/llm/equity", "object");
}

export async function getLlmResearchRuns(): Promise<EndpointResult<LlmResearchRun[]>> {
  return getJson<LlmResearchRun[]>("/llm/research-runs?limit=20", "array");
}

export async function getLlmPageData() {
  const [status, predictions, bets, equity, researchRuns] = await Promise.all([
    getLlmStatus(),
    getLlmPredictions(),
    getLlmBets(),
    getLlmEquity(),
    getLlmResearchRuns(),
  ]);
  return { status, predictions, bets, equity, researchRuns };
}
