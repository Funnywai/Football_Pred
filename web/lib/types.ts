/**
 * Read-only API contract for the new-method paper-trading backend.
 *
 * Every Decimal / UUID / datetime value crosses the wire as a string. Fields stay
 * optional and nullable on purpose: the dashboard must still render when the API is
 * older, partially populated, or serving an empty database.
 */

export type Numeric = string | number | null | undefined;

export type HealthState =
  | "ok"
  | "up"
  | "down"
  | "degraded"
  | "not_configured"
  | "unknown"
  | string;

export interface Health {
  api?: HealthState | null;
  database?: HealthState | null;
  redis?: HealthState | null;
}

export interface Counts {
  matches?: number | null;
  predictions?: number | null;
  predicted_matches?: number | null;
  bets?: number | null;
  settlements?: number | null;
  decisions?: number | null;
  raw_payloads?: number | null;
  source_runs?: number | null;
}

export interface Bankroll {
  initial?: Numeric;
  balance?: Numeric;
  reserved?: Numeric;
  available?: Numeric;
  currency?: string | null;
}

export interface LedgerSummary {
  total_stake?: Numeric;
  total_payout?: Numeric;
  roi?: Numeric;
  settled_bets?: number | null;
  pending_bets?: number | null;
  max_drawdown?: Numeric;
}

export interface Fixture {
  match_id?: string | null;
  kickoff_at?: string | null;
  competition?: string | null;
  home_team?: string | null;
  away_team?: string | null;
  status?: string | null;
}

export interface CalibrationSnapshot {
  model_version?: string | null;
  strategy_version?: string | null;
  competition?: string | null;
  market?: string | null;
  time_block?: string | null;
  sample_count?: number | null;
  brier?: Numeric;
  log_loss?: Numeric;
  roi?: Numeric;
  clv?: Numeric;
}

export interface SourceStatus {
  source_name?: string | null;
  status?: string | null;
  finished_at?: string | null;
  error_count?: number | null;
}

export interface Overview {
  generated_at?: string | null;
  experiment?: {
    id?: string | null;
    label?: string | null;
    model_version?: string | null;
    strategy_version?: string | null;
    initial_bankroll?: Numeric;
  } | null;
  health?: Health | null;
  bankroll?: Bankroll | null;
  ledger?: LedgerSummary | null;
  counts?: Counts | null;
  next_fixtures?: Fixture[] | null;
  latest_calibration?: CalibrationSnapshot[] | null;
  latest_sources?: SourceStatus[] | null;
}

export interface OutcomeProbabilities {
  H?: Numeric;
  D?: Numeric;
  A?: Numeric;
}

export type OutcomeOdds = OutcomeProbabilities;
export type OutcomeEv = OutcomeProbabilities;

export type DecisionStatus = "bet" | "no_bet" | "skipped" | "pending" | string;

export interface Prediction {
  match_id?: string | null;
  kickoff_at?: string | null;
  competition?: string | null;
  home_team?: string | null;
  away_team?: string | null;
  status?: string | null;
  home_goals_90?: Numeric;
  away_goals_90?: Numeric;
  home_goals_final?: Numeric;
  away_goals_final?: Numeric;
  probabilities?: OutcomeProbabilities | null;
  odds?: OutcomeOdds | null;
  ev?: OutcomeEv | null;
  model_version?: string | null;
  decision_at?: string | null;
  decision_status?: DecisionStatus | null;
  decision_reason?: string | null;
}

export interface Bet {
  bet_id?: string | null;
  lane?: string | null;
  match_id?: string | null;
  kickoff_at?: string | null;
  competition?: string | null;
  home_team?: string | null;
  away_team?: string | null;
  market?: string | null;
  selection?: string | null;
  line_key?: string | null;
  odds?: Numeric;
  stake?: Numeric;
  status?: string | null;
  placed_at?: string | null;
  settled_at?: string | null;
  payout?: Numeric;
  profit?: Numeric;
  clv?: Numeric;
  brier?: Numeric;
  model_version?: string | null;
  decision_slot_key?: string | null;
}

export interface EquityPoint {
  t?: string | null;
  bankroll?: Numeric;
}

export interface Equity {
  initial?: Numeric;
  points?: EquityPoint[] | null;
}

export interface ChallengerExperiment {
  id?: string | null;
  label?: string | null;
  lane?: string | null;
  model_version?: string | null;
  strategy_version?: string | null;
  initial_bankroll?: Numeric;
}

export interface ChallengerSummary {
  experiment?: ChallengerExperiment | null;
  bankroll?: Bankroll | null;
  ledger?: LedgerSummary | null;
  counts?: Counts | null;
}

export interface ModelRecord {
  version?: string | null;
  family?: string | null;
  status?: string | null;
  created_at?: string | null;
  params?: Record<string, unknown> | null;
  validation_metrics?: Record<string, unknown> | null;
}

export interface StrategyRecord {
  version?: string | null;
  model_version?: string | null;
  status?: string | null;
  created_at?: string | null;
  policy_params?: Record<string, unknown> | null;
}

export interface CalibrationMetric extends CalibrationSnapshot {
  /** Shape is backend-defined; see lib/calibration.ts for tolerant parsing. */
  calibration?: unknown;
}

export interface WeightSnapshot {
  strategy_version?: string | null;
  weights?: Record<string, unknown> | null;
  reason?: string | null;
  evaluation_period?: string | null;
  created_at?: string | null;
}

export interface Calibration {
  models?: ModelRecord[] | null;
  strategies?: StrategyRecord[] | null;
  metrics?: CalibrationMetric[] | null;
  weight_snapshots?: WeightSnapshot[] | null;
}

export interface SourceRun extends SourceStatus {
  [key: string]: unknown;
}

export interface LatestOdds {
  snapshot_at?: string | null;
  market?: string | null;
  match_id?: string | null;
}

export interface Technical {
  alembic_revision?: string | null;
  database?: HealthState | null;
  redis?: HealthState | null;
  counts?: Counts | null;
  sources?: SourceRun[] | null;
  decisions?: Array<Record<string, unknown>> | null;
  latest_odds?: LatestOdds | null;
  paper_forward?: unknown;
}
