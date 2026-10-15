import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MatchesPredictionsTable } from "@/components/tables/MatchesPredictionsTable";
import type { BetsWindow } from "@/lib/bets-window";
import type { Bet, Prediction } from "@/lib/types";

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

function windowOf(rows: Bet[], total: number | null, newestFirst = true): BetsWindow {
  return { rows, total, newestFirst };
}

describe("MatchesPredictionsTable", () => {
  it("renders prob, implied, edge and the placed bet's odds and stake", () => {
    render(
      <MatchesPredictionsTable
        predictions={[prediction({ id: 1, match_id: 1 })]}
        bets={windowOf([bet({ id: 7, match_id: 1, odds: 2.48, stake: 10 })], 1)}
      />,
    );
    expect(screen.getByText("45.0%")).toBeInTheDocument();
    expect(screen.getByText("40.0%")).toBeInTheDocument();
    expect(screen.getByText("+5.0%")).toBeInTheDocument();
    expect(screen.getByText("placed")).toBeInTheDocument();
    expect(screen.getByText("2.48")).toBeInTheDocument();
    expect(screen.getByText("HK$10.00")).toBeInTheDocument();
  });

  it("marks a prediction with no bet as no bet", () => {
    render(
      <MatchesPredictionsTable
        predictions={[prediction({ id: 1, match_id: 1 })]}
        bets={windowOf([], 0)}
      />,
    );
    expect(screen.getByText("no bet")).toBeInTheDocument();
  });

  it("states the fetched window, the display order and the join counts", () => {
    const predictions = Array.from({ length: 200 }, (_, index) =>
      prediction({ id: index + 1, match_id: index + 1 }),
    );
    render(<MatchesPredictionsTable predictions={predictions} bets={windowOf([], 0)} />);
    expect(
      screen.getByText(/the first 200 champion and challenger predictions by kickoff time \(earliest first\)/),
    ).toBeInTheDocument();
    expect(screen.getByText(/newer fixtures may fall outside this window/)).toBeInTheDocument();
    expect(
      screen.getByText(/Rows are shown newest kickoff first within that window/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/200 of these have no place in the ledger; 0 matched a placed bet\./),
    ).toBeInTheDocument();
  });

  it("states the whole set when the API returned fewer predictions than the page size", () => {
    render(
      <MatchesPredictionsTable
        predictions={[prediction({ id: 1, match_id: 1 })]}
        bets={windowOf([], 0)}
      />,
    );
    expect(
      screen.getByText(/all 1 champion and challenger predictions by kickoff time \(earliest first\)/),
    ).toBeInTheDocument();
  });

  it("qualifies the join counts when the fetched bets window is truncated", () => {
    render(
      <MatchesPredictionsTable
        predictions={[prediction({ id: 1, match_id: 1 })]}
        bets={windowOf([bet({ id: 7, match_id: 999 })], 250)}
      />,
    );
    expect(
      screen.getByText(
        /0 matched a placed bet in the fetched bets window; 1 has no match there — a bet outside the fetched window would not be seen\./,
      ),
    ).toBeInTheDocument();
  });

  it("states the definitive ledger claim when the fetched window covers the ledger", () => {
    render(
      <MatchesPredictionsTable
        predictions={[prediction({ id: 1, match_id: 1 })]}
        bets={windowOf([], 0)}
      />,
    );
    expect(
      screen.getByText(/1 of these has no place in the ledger; 0 matched a placed bet\./),
    ).toBeInTheDocument();
    expect(screen.queryByText(/no match there/)).not.toBeInTheDocument();
  });

  it("qualifies the claim when the summary was unavailable and only the oldest page was fetched", () => {
    render(
      <MatchesPredictionsTable
        predictions={[prediction({ id: 1, match_id: 1 })]}
        bets={windowOf([bet({ id: 7, match_id: 999 })], null, false)}
      />,
    );
    expect(
      screen.getByText(
        /0 matched a placed bet in the fetched bets window; 1 has no match there — a bet outside the fetched window would not be seen\./,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/no place in the ledger/)).not.toBeInTheDocument();
  });

  it("renders an explicit unavailable state when a source is missing", () => {
    render(<MatchesPredictionsTable predictions={null} bets={null} />);
    expect(screen.getByText("Matches x predictions unavailable")).toBeInTheDocument();
  });

  it("renders an empty state when the model has written no prediction", () => {
    render(<MatchesPredictionsTable predictions={[]} bets={windowOf([], 0)} />);
    expect(screen.getByText("No predictions yet")).toBeInTheDocument();
  });
});
