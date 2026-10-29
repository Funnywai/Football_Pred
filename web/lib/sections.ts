// Section shells for the walking skeleton. Titles, one-line purposes and source routes
// come straight from docs/superpowers/specs/2026-10-15-dashboard-design.md sections 5.2
// and 5.3. No data is fabricated here; each shell renders a pending state.

export interface SectionSpec {
  id: string;
  title: string;
  purpose: string;
  source: string;
}

export const PERFORMANCE_SECTIONS: SectionSpec[] = [
  {
    id: "kpi-strip",
    title: "KPI strip",
    purpose: "Bankroll, realised profit, ROI, yield, open stakes, bet count and win rate.",
    source: "/bets/summary + /bets",
  },
  {
    id: "equity-curve",
    title: "Equity / money curve",
    purpose: "Total money over time, including the initial point where t is null.",
    source: "/bets/equity-curve",
  },
  {
    id: "pipeline",
    title: "AI pipeline",
    purpose: "Six stages INGEST to RETRAIN, each with its last action time and live status.",
    source: "/ops/jobs + /ops/runs",
  },
  {
    id: "signal-vs-execution",
    title: "Signal vs execution price",
    purpose: "Per bet: prior market odds to execution odds and the percentage difference.",
    source: "/bets + /predictions",
  },
  {
    id: "bets",
    title: "All bets",
    purpose: "Every bet with odds, edge, stake, payout, profit, status and kickoff.",
    source: "/bets",
  },
  {
    id: "matches-predictions",
    title: "Matches x predictions",
    purpose: "Model probability vs implied probability vs edge, and whether a bet was placed.",
    source: "/predictions + /bets",
  },
  {
    id: "results",
    title: "Results",
    purpose: "Score, confirmation and payout-confirmation state for each settled match.",
    source: "/results",
  },
];

export const CLV_SECTIONS: SectionSpec[] = [
  {
    id: "clv",
    title: "CLV & Calibration",
    purpose: "Champion 1x2 CLV and calibration metrics, with the CLV-is-a-proxy note and stop/go gate.",
    source: "/clv/summary + /models",
  },
];

export const AGENT_SECTIONS: SectionSpec[] = [
  {
    id: "agent-kpi-strip",
    title: "Agent KPI strip",
    purpose: "The agent paper book's bankroll, profit, ROI, yield, open stakes, bets and win rate.",
    source: "/agent/summary + /agent/bets",
  },
  {
    id: "agent-equity-curve",
    title: "Agent equity / money curve",
    purpose: "Agent paper money over time, including the initial point where t is null.",
    source: "/agent/equity-curve",
  },
  {
    id: "agent-decisions",
    title: "Agent decisions",
    purpose: "Every risk-agent decision with match, outcome, action, stake, edge and reason.",
    source: "/agent/decisions",
  },
  {
    id: "agent-bets",
    title: "Agent paper bets",
    purpose: "The agent paper book's bets, separate from the production and shadow ledgers.",
    source: "/agent/bets",
  },
];

export const TECHNICAL_SECTIONS: SectionSpec[] = [
  {
    id: "log-stream",
    title: "Live log stream",
    purpose: "Recent log lines with a level filter, auto-refresh and pause.",
    source: "/ops/logs",
  },
  {
    id: "scheduler",
    title: "Scheduler table",
    purpose: "Each job's trigger, next run time, last status, records and error.",
    source: "/ops/jobs",
  },
  {
    id: "ingestion-timeline",
    title: "Ingestion runs timeline",
    purpose: "Run history over time, with failures highlighted.",
    source: "/ops/runs",
  },
  {
    id: "freshness",
    title: "Data freshness panel",
    purpose: "Last snapshot, feature, result and prediction arrival, ageing red past threshold.",
    source: "/ops/data + /ops/runs",
  },
  {
    id: "db-size",
    title: "DB size table",
    purpose: "Row counts per table, odds counts by source and type, post-compaction anchors.",
    source: "/ops/data",
  },
  {
    id: "model-timeline",
    title: "Model version timeline",
    purpose: "Champion and challenger versions with promotion time, metrics and artifact path.",
    source: "/models + /ops/data",
  },
  {
    id: "environment",
    title: "Environment",
    purpose: "App version, git SHA, alembic revision and DB connectivity. Never any secret.",
    source: "/ops/status",
  },
];
