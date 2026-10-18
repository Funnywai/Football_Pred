// TypeScript mirrors of the FastAPI response shapes.
//
// Authoritative sources: app/api/schemas.py (data routes) and app/api/ops.py +
// app/api/ops_data.py (the /ops/* surface). Field names are the exact JSON keys the
// API returns. Do not invent fields or routes.

export interface Team {
  id: number;
  name_en: string;
  name_ch: string | null;
}

export interface Match {
  id: number;
  league_code: string;
  league_name: string;
  kickoff_time: string;
  status: string;
  home_team: Team;
  away_team: Team;
  venue: string | null;
  round: string | null;
  hkjc_match_id: string | null;
}

export interface OddsSnapshot {
  odds_type: string;
  inplay: boolean;
  source: string;
  captured_at: string;
  snapshot_bucket: string;
  payload: Record<string, unknown>;
}

export interface Result {
  match_id: number;
  home_score: number;
  away_score: number;
  ttl_corner: number | null;
  source: string;
  confirmed: boolean;
  payout_confirmed: boolean;
  confirmed_at: string | null;
  kickoff_time: string;
  league_code: string;
  home_team: Team;
  away_team: Team;
}

export interface Prediction {
  id: number;
  match_id: number;
  target: string;
  outcome: string;
  model_version_id: number;
  prob: number;
  implied_prob: number | null;
  edge: number | null;
  fair_odds: number;
  market_odds: number | null;
  recommended_fraction: number | null;
  kickoff_time: string;
  league_code: string;
  home_team: string;
  away_team: string;
}

// `metrics` is an untyped dict in schemas.py; every value it carries is numeric.
export type ModelMetrics = Record<string, number>;

export interface ModelVersion {
  id: number;
  target: string;
  algorithm: string;
  status: string;
  metrics: ModelMetrics;
  artifact_path: string;
  created_at: string;
  promoted_at: string | null;
}

export interface Bet {
  id: number;
  match_id: number;
  target: string;
  outcome: string;
  model_version_id: number;
  line: number | null;
  odds: number;
  stake: number;
  bankroll_at_place: number;
  edge: number | null;
  kelly_multiplier: number;
  status: string;
  placed_at: string;
  settled_at: string | null;
  payout: number | null;
  profit: number | null;
  kickoff_time: string;
  league_code: string;
  home_team: string;
  away_team: string;
}

export interface BetSummary {
  initial_bankroll: number;
  bankroll: number;
  n_bets: number;
  n_settled: number;
  n_open: number;
  stakes_total: number;
  open_stakes: number;
  realized_profit: number;
  roi: number;
  yield_pct: number;
}

export interface EquityPoint {
  t: string | null;
  bankroll: number;
}

// ---- /clv/summary (app/api/schemas.py ClvSummaryOut) ----

export interface ClvMetrics {
  n: number;
  mean_edge: number | null;
  beat_fraction: number | null;
  beat_ci95: [number, number] | null;
  mean_edge_ci95: [number, number] | null;
}

export interface ClvModel extends ClvMetrics {
  model_version_id: number;
  target: string;
  status: string;
  algorithm: string;
}

export interface ClvCalibration {
  model_brier: number | null;
  model_logloss: number | null;
  market_brier: number | null;
  market_logloss: number | null;
  n_matches: number;
}

export interface ClvCriterion {
  key: string;
  passed: boolean;
  actual: number | null;
  required: number | null;
}

export type ClvGateVerdict = "pass" | "fail" | "collecting";

export interface ClvGate {
  ready: boolean;
  verdict: ClvGateVerdict;
  days_elapsed: number;
  days_remaining: number;
  criteria: ClvCriterion[];
}

export interface ClvSummary {
  source: string;
  n: number;
  mean_edge: number | null;
  beat_fraction: number | null;
  beat_ci95: [number, number] | null;
  mean_edge_ci95: [number, number] | null;
  by_outcome: Record<string, ClvMetrics>;
  by_model: ClvModel[];
  value: ClvMetrics;
  source_counts: Record<string, number>;
  fallback: number;
  calibration: ClvCalibration;
  roi_real: number | null;
  roi_real_ci95: [number, number] | null;
  n_settled_bets: number;
  settled_stakes: number;
  gate: ClvGate;
}

// ---- /ops/* surface (app/api/ops.py, app/api/ops_data.py) ----

export interface OpsStatus {
  app_version: string;
  git_sha: string;
  alembic_revision: string | null;
  uptime_seconds: number;
  db_ok: boolean;
  scheduler_enabled: boolean;
}

export interface OpsJobLastRun {
  status: string;
  finished_at: string | null;
  records_upserted: number | null;
  error: string | null;
}

export interface OpsJob {
  id: string;
  trigger: string;
  next_run_time: string | null;
  pending: boolean;
  last_run: OpsJobLastRun | null;
}

export interface OpsJobs {
  jobs: OpsJob[];
}

export interface OpsRun {
  id: number;
  job: string;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  records_upserted: number | null;
  error: string | null;
}

export interface OpsRuns {
  runs: OpsRun[];
}

export interface OpsLogLine {
  time: string;
  level: string;
  logger: string;
  message: string;
}

export interface OpsLogs {
  logs: OpsLogLine[];
}

export interface OpsOddsGroup {
  source: string;
  odds_type: string;
  inplay: boolean;
  count: number;
  max_captured_at: string | null;
}

export interface OpsModelVersion {
  id: number;
  target: string;
  algorithm: string;
  status: string;
  params: Record<string, unknown>;
  metrics: ModelMetrics;
  artifact_path: string;
  created_at: string | null;
  promoted_at: string | null;
}

export interface OpsData {
  table_counts: Record<string, number>;
  odds: {
    total: number;
    last_captured_at: string | null;
    by_source_type: OpsOddsGroup[];
  };
  match_features: { count: number; max_built_at: string | null };
  results: {
    total: number;
    confirmed: number;
    payout_confirmed: number;
    max_confirmed_at: string | null;
  };
  model_versions: OpsModelVersion[];
  alembic_revision: string | null;
  last_arrived: {
    odds_captured_at: string | null;
    features_built_at: string | null;
    results_confirmed_at: string | null;
    model_created_at: string | null;
    model_promoted_at: string | null;
  };
}
