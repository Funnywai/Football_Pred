/**
 * Read-only API contract for the separate LLM Ensemble Lab lane.
 *
 * The endpoint is `GET /llm/status`. Counts, weights and prompt hashes cross the
 * wire as numbers/strings; every field stays optional so the page can still render
 * when the API is older or the lane has not been populated yet.
 */

import type { Numeric, OutcomeEv, OutcomeOdds, OutcomeProbabilities } from "./types";

export interface LlmRuntime {
  decision_layer?: string | null;
  data_plane?: string | null;
  paper_ledger?: string | null;
  provider?: string | null;
  model?: string | null;
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

export interface LlmFixture {
  match_id?: string | null;
  kickoff_at?: string | null;
  competition?: string | null;
  home_team?: string | null;
  away_team?: string | null;
  status?: string | null;
}

export interface LlmLedger {
  experiment_id?: string | null;
  label?: string | null;
  model_version?: string | null;
  strategy_version?: string | null;
  initial_bankroll?: string | null;
  bankroll?: string | null;
  available?: string | null;
  reserved?: string | null;
  currency?: string | null;
  total_stake?: string | null;
  total_payout?: string | null;
  roi?: string | null;
  settled_bets?: number | null;
  pending_bets?: number | null;
  max_drawdown?: string | null;
}

export interface LlmPrediction {
  match_id?: string | null;
  kickoff_at?: string | null;
  competition?: string | null;
  home_team?: string | null;
  away_team?: string | null;
  probabilities?: OutcomeProbabilities | null;
  odds?: OutcomeOdds | null;
  ev?: OutcomeEv | null;
  model_version?: string | null;
  generated_at?: string | null;
  decision_status?: string | null;
  paper_bet_id?: string | null;
  paper_bet_status?: string | null;
  paper_bet_selection?: string | null;
  paper_bet_odds?: Numeric;
  paper_bet_stake?: Numeric;
}

export interface LlmStatus {
  generated_at?: string | null;
  phase?: string | null;
  competitions?: string[] | null;
  runtime?: LlmRuntime | null;
  safety?: LlmSafety | null;
  counts?: LlmCounts | null;
  ledger?: LlmLedger | null;
  next_fixtures?: LlmFixture[] | null;
  agents?: LlmAgent[] | null;
  weights?: LlmWeight[] | null;
  prompts?: LlmPrompt[] | null;
  separation?: LlmSeparation[] | null;
}
export interface LlmResearchFinding {
  agent_id?: string | null;
  summary?: string | null;
  findings?: string[] | null;
  confidence?: Numeric;
  direction?: string | null;
  evidence_refs?: string[] | null;
  uncertainties?: string[] | null;
  abstain?: boolean | null;
  error?: string | null;
}

export interface LlmResearchRisk {
  accepted?: boolean | null;
  reason?: string | null;
  selection?: string | null;
  stake?: Numeric;
  odds?: Numeric;
  paper_bet_id?: string | null;
  bankroll?: Numeric;
}

export interface LlmResearchReport {
  summary?: string | null;
  key_findings?: string[] | null;
  market_view?: string | null;
  risks?: string[] | null;
  reasoning?: string | null;
}

export interface LlmResearchRun {
  run_id?: string | null;
  match_id?: string | null;
  stage?: string | null;
  as_of?: string | null;
  status?: string | null;
  model_version?: string | null;
  prompt_version?: string | null;
  provider?: string | null;
  report?: LlmResearchReport | null;
  probabilities?: OutcomeProbabilities | null;
  recommended_side?: string | null;
  recommended_stake_pct?: Numeric;
  confidence?: Numeric;
  abstain?: boolean | null;
  risk?: LlmResearchRisk | null;
  error?: string | null;
  findings?: LlmResearchFinding[] | null;
  created_at?: string | null;
}
