import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EquityCurve } from "@/components/charts/EquityCurve";
import { KpiStrip } from "@/components/kpi/KpiStrip";
import { PipelineFlow } from "@/components/pipeline/PipelineFlow";
import { BetsTable } from "@/components/tables/BetsTable";
import { SignalVsExecutionTable } from "@/components/tables/SignalVsExecutionTable";
import type { BetsWindow } from "@/lib/bets-window";
import type { Bet, BetSummary, EquityPoint, OpsData, OpsJob, Prediction } from "@/lib/types";

const NOW = new Date("2026-10-15T12:00:00Z");

const SUMMARY: BetSummary = {
  initial_bankroll: 1000,
  bankroll: 1005,
  n_bets: 2,
  n_settled: 2,
  n_open: 0,
  stakes_total: 20,
  open_stakes: 0,
  realized_profit: 5,
  roi: 0.25,
  yield_pct: 0.25,
};

function bet(overrides: Partial<Bet>): Bet {
  return {
    id: 1,
    match_id: 29164,
    target: "1x2",
    outcome: "H",
    model_version_id: 1,
    line: null,
    odds: 2.48,
    stake: 10,
    bankroll_at_place: 1000,
    edge: 0.05,
    kelly_multiplier: 0.5,
    status: "won",
    placed_at: "2026-10-14T00:00:00Z",
    settled_at: "2026-10-15T00:00:00Z",
    payout: 24.8,
    profit: 14.8,
    kickoff_time: "2026-10-14T12:00:00Z",
    league_code: "EPL",
    home_team: "Arsenal",
    away_team: "Chelsea",
    ...overrides,
  };
}

function prediction(overrides: Partial<Prediction>): Prediction {
  return {
    id: 1,
    match_id: 29164,
    target: "1x2",
    outcome: "H",
    model_version_id: 1,
    prob: 0.45,
    implied_prob: 0.4,
    edge: 0.05,
    fair_odds: 2.22,
    market_odds: 2.48,
    recommended_fraction: 0.02,
    kickoff_time: "2026-10-14T12:00:00Z",
    league_code: "EPL",
    home_team: "Arsenal",
    away_team: "Chelsea",
    ...overrides,
  };
}

function job(id: string, lastRun: OpsJob["last_run"]): OpsJob {
  return { id, trigger: "interval", next_run_time: "2026-10-15T12:10:00Z", pending: false, last_run: lastRun };
}

function windowOf(rows: Bet[], total: number | null, newestFirst = true): BetsWindow {
  return { rows, total, newestFirst };
}

function opsData(): OpsData {
  return {
    table_counts: {},
    odds: { total: 0, last_captured_at: null, by_source_type: [] },
    match_features: { count: 18, max_built_at: "2026-10-15T11:00:00Z" },
    results: { total: 0, confirmed: 0, payout_confirmed: 0, max_confirmed_at: null },
    model_versions: [],
    alembic_revision: "0003",
    last_arrived: {
      odds_captured_at: "2026-10-15T11:58:00Z",
      features_built_at: "2026-10-15T11:00:00Z",
      results_confirmed_at: null,
      model_created_at: null,
      model_promoted_at: null,
    },
  };
}

describe("KpiStrip", () => {
  it("renders the summary values and the derived win rate", () => {
    render(
      <KpiStrip
        summary={SUMMARY}
        bets={windowOf(
          [bet({ id: 1, status: "won", profit: 14.8 }), bet({ id: 2, status: "lost", profit: -9.8 })],
          2,
        )}
      />,
    );
    expect(screen.getAllByText("HK$1,005.00").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("+HK$5.00").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("25.0%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("50.0%").length).toBeGreaterThanOrEqual(1);
  });

  it("discloses the window when the win rate is derived from a truncated page", () => {
    const rows = Array.from({ length: 30 }, (_, index) =>
      bet({ id: index + 1, status: "won", profit: 1 }),
    );
    render(<KpiStrip summary={SUMMARY} bets={windowOf(rows, 250)} />);
    expect(screen.getByText(/over the 30 most recent settled bets/)).toBeInTheDocument();
  });

  it("adds no truncation wording when the fetched page covers the ledger", () => {
    render(
      <KpiStrip
        summary={SUMMARY}
        bets={windowOf(
          [bet({ id: 1, status: "won", profit: 14.8 }), bet({ id: 2, status: "lost", profit: -9.8 })],
          2,
        )}
      />,
    );
    expect(screen.queryByText(/most recent settled bets/)).not.toBeInTheDocument();
  });

  it("says the bets source is unavailable when the bets fetch failed", () => {
    render(<KpiStrip summary={SUMMARY} bets={null} />);
    expect(screen.getByText("bets unavailable")).toBeInTheDocument();
  });

  it("renders an explicit unavailable state when the summary is missing", () => {
    render(<KpiStrip summary={null} bets={null} />);
    expect(screen.getByText("KPI data unavailable")).toBeInTheDocument();
  });
});

describe("EquityCurve", () => {
  const points: EquityPoint[] = [
    { t: null, bankroll: 1000 },
    { t: "2026-10-15T00:00:00Z", bankroll: 1005 },
    { t: "2026-10-15T12:00:00Z", bankroll: 1005 },
  ];

  it("renders the trend summary and a table fallback", () => {
    render(<EquityCurve points={points} />);
    expect(screen.getByText(/HK\$1,000\.00 to HK\$1,005\.00/)).toBeInTheDocument();
    expect(screen.getByText("table view")).toBeInTheDocument();
  });

  it("renders an explicit unavailable state when the curve is missing", () => {
    render(<EquityCurve points={null} />);
    expect(screen.getByText("Equity curve unavailable")).toBeInTheDocument();
  });

  it("renders an empty state when there are no settlements", () => {
    render(<EquityCurve points={[{ t: null, bankroll: 1000 }]} />);
    expect(screen.getByText("No equity points yet")).toBeInTheDocument();
  });
});

describe("PipelineFlow", () => {
  it("renders all six stages with their statuses", () => {
    render(
      <PipelineFlow
        jobs={[
          job("sync_odds", { status: "success", finished_at: "2026-10-15T11:58:00Z", records_upserted: 5, error: null }),
          job("ml_predict", { status: "running", finished_at: null, records_upserted: null, error: null }),
        ]}
        runs={[]}
        data={opsData()}
        now={NOW}
      />,
    );
    for (const label of ["INGEST", "FEATURES", "PREDICT", "BET", "SETTLE", "RETRAIN"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1);
    }
    expect(screen.getAllByText("running").length).toBeGreaterThanOrEqual(1);
  });

  it("renders an explicit unavailable state when the ops surface is missing", () => {
    render(<PipelineFlow jobs={null} runs={null} data={null} now={NOW} />);
    expect(screen.getByText("Pipeline unavailable")).toBeInTheDocument();
  });
});

describe("BetsTable", () => {
  it("renders the execution-price note and the bet rows", () => {
    render(
      <BetsTable
        bets={windowOf([bet({ id: 1 }), bet({ id: 2, match_id: 29160, odds: 4.0 })], 2)}
      />,
    );
    expect(screen.getByText(/odds is the execution price/)).toBeInTheDocument();
    expect(screen.getAllByText("Arsenal v Chelsea").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("2 bets · 2 of 2 shown")).toBeInTheDocument();
  });

  it("discloses the fetched slice when the page is truncated", () => {
    const rows = Array.from({ length: 30 }, (_, index) => bet({ id: index + 1 }));
    render(<BetsTable bets={windowOf(rows, 250)} />);
    expect(
      screen.getByText("showing the 30 most recent of 250 bets · 10 of 30 shown"),
    ).toBeInTheDocument();
  });

  it("renders the rows in the given newest-first display order", () => {
    render(
      <BetsTable
        bets={windowOf(
          [
            bet({ id: 2, home_team: "Newest", placed_at: "2026-10-14T00:00:00Z" }),
            bet({ id: 1, home_team: "Older", placed_at: "2026-10-13T00:00:00Z" }),
          ],
          2,
        )}
      />,
    );
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Newest");
    expect(rows[2]).toHaveTextContent("Older");
  });

  it("renders the oldest-page wording when the summary was unavailable", () => {
    render(<BetsTable bets={windowOf([bet({ id: 1 }), bet({ id: 2 })], null, false)} />);
    expect(
      screen.getByText(
        "showing the oldest 2 bets · /bets/summary unavailable · 2 of 2 shown",
      ),
    ).toBeInTheDocument();
  });

  it("reveals 10 more per click and searches", () => {
    const rows = Array.from({ length: 30 }, (_, index) =>
      bet({ id: index + 1, away_team: index < 5 ? "Chelsea" : "Liverpool" }),
    );
    render(<BetsTable bets={windowOf(rows, 30)} />);
    expect(screen.getAllByRole("row")).toHaveLength(11);
    fireEvent.click(screen.getByRole("button", { name: /Expand/ }));
    expect(screen.getAllByRole("row")).toHaveLength(21);
    fireEvent.change(screen.getByLabelText("Search bets"), { target: { value: "chelsea" } });
    expect(screen.getAllByRole("row").length).toBeLessThan(11);
    expect(screen.getByText('30 bets · 5 of 5 shown · matching "chelsea"')).toBeInTheDocument();
  });

  it("renders an explicit unavailable state when bets are missing", () => {
    render(<BetsTable bets={null} />);
    expect(screen.getByText("Bets unavailable")).toBeInTheDocument();
  });

  it("renders an empty state when the ledger is empty", () => {
    render(<BetsTable bets={windowOf([], 0)} />);
    expect(screen.getByText("No bets placed yet")).toBeInTheDocument();
  });

  it("renders an honest empty state when the fetched window is empty but the ledger is not", () => {
    render(<BetsTable bets={windowOf([], 250)} />);
    expect(screen.getByText("No bets in the fetched window")).toBeInTheDocument();
  });
});

describe("SignalVsExecutionTable", () => {
  it("renders the signal and execution prices for a matched bet", () => {
    render(
      <SignalVsExecutionTable
        bets={windowOf([bet({ id: 2, match_id: 29160, odds: 4.0 })], 2)}
        predictions={[prediction({ match_id: 29160, market_odds: 3.9 })]}
      />,
    );
    expect(screen.getByText("3.90")).toBeInTheDocument();
    expect(screen.getByText("4.00")).toBeInTheDocument();
    expect(screen.getByText("+0.10")).toBeInTheDocument();
  });

  it("states the joined window, the predictions source, and the unmatched count", () => {
    const rows = Array.from({ length: 30 }, (_, index) => bet({ id: index + 1 }));
    render(<SignalVsExecutionTable bets={windowOf(rows, 250)} predictions={[]} />);
    expect(screen.getByText(/the 30 most recent of 250 bets/)).toBeInTheDocument();
    expect(
      screen.getByText(/\/predictions\?limit=200&champion_only=false/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/30 bet\(s\) have no matching prediction in the fetched window/),
    ).toBeInTheDocument();
  });

  it("renders an explicit unavailable state when a source is missing", () => {
    render(<SignalVsExecutionTable bets={null} predictions={null} />);
    expect(screen.getByText("Signal vs execution unavailable")).toBeInTheDocument();
  });

  it("renders an empty state when there are no bets", () => {
    render(<SignalVsExecutionTable bets={windowOf([], 0)} predictions={[]} />);
    expect(screen.getByText("No bets to compare yet")).toBeInTheDocument();
  });
});
