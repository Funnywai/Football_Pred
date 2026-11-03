import "server-only";

import { getJson, type EndpointResult } from "./api";
import type { LlmStatus } from "./llm-types";

/**
 * Server-side read of the separate LLM lane. Uses the same `API_BASE_URL`
 * convention (and failure isolation) as the deterministic dashboard; the browser
 * never talks to the API and no credentials are exposed.
 */
export async function getLlmStatus(): Promise<EndpointResult<LlmStatus>> {
  return getJson<LlmStatus>("/llm/status", "object");
}
