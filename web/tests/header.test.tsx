import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SystemHeader } from "@/components/header/SystemHeader";
import { buildHeaderData, type HeaderInputs } from "@/lib/header-model";

const NOW = new Date("2026-10-15T12:00:00Z");

const EMPTY_INPUTS: HeaderInputs = {
  summary: null,
  status: null,
  jobs: null,
  runs: null,
  data: null,
  models: null,
  now: NOW,
};

describe("SystemHeader — API unavailable degradation", () => {
  it("still renders, showing explicit unavailable/stale states", () => {
    render(<SystemHeader data={buildHeaderData(EMPTY_INPUTS)} />);

    // money, heartbeat and freshness each render an explicit unavailable state
    expect(screen.getAllByText("unavailable").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText("build unavailable")).toBeInTheDocument();
    expect(screen.getByText("system idle")).toBeInTheDocument();
  });
});

describe("SystemHeader — populated from real fields", () => {
  const inputs: HeaderInputs = {
    summary: {
      initial_bankroll: 1000,
      bankroll: 1234.5,
      n_bets: 10,
      n_settled: 8,
      n_open: 2,
      stakes_total: 200,
      open_stakes: 40,
      realized_profit: 234.5,
      roi: 0.1,
      yield_pct: 0.05,
    },
    status: {
      app_version: "0.1.0",
      git_sha: "abc1234",
      alembic_revision: "0003",
      uptime_seconds: 100,
      db_ok: true,
      scheduler_enabled: true,
    },
    jobs: [
      {
        id: "sync_odds",
        trigger: "interval[0:10:00]",
        next_run_time: "2026-10-15T12:05:00Z",
        pending: false,
        last_run: {
          status: "success",
          finished_at: "2026-10-15T11:58:00Z",
          records_upserted: 5,
          error: null,
        },
      },
    ],
    runs: [
      {
        id: 1,
        job: "sync_odds",
        started_at: "2026-10-15T11:57:00Z",
        finished_at: "2026-10-15T11:58:00Z",
        status: "success",
        records_upserted: 5,
        error: null,
      },
    ],
    data: {
      table_counts: {},
      odds: { total: 0, last_captured_at: "2026-10-15T11:58:00Z", by_source_type: [] },
      match_features: { count: 0, max_built_at: "2026-10-15T11:00:00Z" },
      results: { total: 0, confirmed: 0, payout_confirmed: 0, max_confirmed_at: "2026-10-15T10:00:00Z" },
      model_versions: [],
      alembic_revision: "0003",
      last_arrived: {
        odds_captured_at: "2026-10-15T11:58:00Z",
        features_built_at: "2026-10-15T11:00:00Z",
        results_confirmed_at: "2026-10-15T10:00:00Z",
        model_created_at: null,
        model_promoted_at: null,
      },
    },
    models: [
      {
        id: 1,
        target: "1x2",
        algorithm: "lightgbm",
        status: "champion",
        metrics: {},
        artifact_path: "artifacts/ml/x.joblib",
        created_at: "2026-10-01T00:00:00Z",
        promoted_at: "2026-10-02T00:00:00Z",
      },
    ],
    now: NOW,
  };

  it("renders bankroll, realised profit, build identity and a healthy heartbeat", () => {
    render(<SystemHeader data={buildHeaderData(inputs)} />);

    expect(screen.getByText("HK$1,234.50")).toBeInTheDocument();
    expect(screen.getByText("+HK$234.50")).toBeInTheDocument();
    expect(screen.getByText("abc1234")).toBeInTheDocument();
    expect(screen.getByText(/1x2/)).toBeInTheDocument();
    expect(screen.getAllByText("healthy").length).toBeGreaterThanOrEqual(1);
  });
});
