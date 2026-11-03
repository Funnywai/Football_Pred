/**
 * Read-only API contract for the separate LLM Ensemble Lab lane.
 *
 * The endpoint is `GET /llm/status`. Counts, weights and prompt hashes cross the
 * wire as numbers/strings; every field stays optional so the page can still render
 * when the API is older or the lane has not been populated yet.
 */

import type { Numeric } from "./types";

export interface LlmRuntime {
  decision_layer?: string | null;
  data_plane?: string | null;
  paper_ledger?: string | null;
}

export interface LlmSafety {
  paper_only?: boolean | null;
  real_money?: boolean | null;
  llm_may_write_database?: boolean | null;
  llm_may_settle?: boolean | null;
}

export interface LlmCounts {
  agents?: number | null;
  prompts?: number | null;
  evidence_packets?: number | null;
  agent_runs?: number | null;
  predictions?: number | null;
  paper_bets?: number | null;
}

export interface LlmAgent {
  agent_id?: string | null;
  name?: string | null;
  scope?: string | null;
  kind?: string | null;
  phase?: string | null;
}

export interface LlmWeight {
  agent_id?: string | null;
  weight?: Numeric;
  sample_count?: number | null;
  status?: string | null;
}

export interface LlmPrompt {
  name?: string | null;
  sha256?: string | null;
  bytes?: number | null;
}

export interface LlmSeparation {
  lane?: string | null;
  label?: string | null;
  detail?: string | null;
}

export interface LlmStatus {
  generated_at?: string | null;
  phase?: string | null;
  runtime?: LlmRuntime | null;
  safety?: LlmSafety | null;
  counts?: LlmCounts | null;
  agents?: LlmAgent[] | null;
  weights?: LlmWeight[] | null;
  prompts?: LlmPrompt[] | null;
  separation?: LlmSeparation[] | null;
}
