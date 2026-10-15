import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClvCard } from "@/components/clv/ClvCard";
import { MatchesPredictionsTable } from "@/components/tables/MatchesPredictionsTable";
import { ResultsTable } from "@/components/tables/ResultsTable";
import type { BetsWindow } from "@/lib/bets-window";
import type { Bet, ModelVersion, Prediction, Result } from "@/lib/types";

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

function result(overrides: Partial<Result>): Result {
  return {
    match_id: 29164,
    home_score: 2,
    away_score: 1,
    ttl_corner: 9,
    source: "hkjc",
    confirmed: true,
    payout_confirmed: true,
    confirmed_at: "2026-10-15T00:00:00Z",
    kickoff_time: "2026-10-14T12:00:00Z",
    league_code: "EPL",
    home_team: { id: 1, name_en: "Arsenal", name_ch: "阿仙奴" },
    away_team: { id: 2, name_en: "Chelsea", name_ch: "車路士" },
    ...overrides,
  };
}

function model(overrides: Partial<ModelVersion>): ModelVersion {
  return {
    id: 2,
    target: "1x2",
    algorithm: "lightgbm",
    status: "champion",
    metrics: {
      brier: 0.1923,
      logloss: 0.5512,
      n: 100,
      clv_fraction: 0.583,
      clv_mean_edge: 0.012,
      clv_n: 36,
    },
    artifact_path: "artifacts/ml/model.txt",
    created_at: "2026-10-14T00:00:00Z",
    promoted_at: "2026-10-14T12:00:00Z",
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

  it("renders an explicit unavailable state when a source is missing", () => {
    render(<MatchesPredictionsTable predictions={null} bets={null} />);
    expect(screen.getByText("Matches x predictions unavailable")).toBeInTheDocument();
  });

  it("renders an empty state when the model has written no prediction", () => {
    render(<MatchesPredictionsTable predictions={[]} bets={windowOf([], 0)} />);
    expect(screen.getByText("No predictions yet")).toBeInTheDocument();
  });
});

describe("ResultsTable", () => {
  it("renders the score, the confirmation pills, the source and the confirmation time", () => {
    render(<ResultsTable results={[result({ match_id: 1 })]} />);
    expect(screen.getByText("2-1")).toBeInTheDocument();
    expect(screen.getByText("confirmed")).toBeInTheDocument();
    expect(screen.getByText("payout confirmed")).toBeInTheDocument();
    expect(screen.getByText("hkjc")).toBeInTheDocument();
    expect(screen.getByText("15/10/2026, 00:00")).toBeInTheDocument();
  });

  it("labels an unconfirmed result and an unconfirmed payout in words, not colour alone", () => {
    render(
      <ResultsTable
        results={[result({ confirmed: false, payout_confirmed: false, confirmed_at: null })]}
      />,
    );
    expect(screen.getByText("unconfirmed")).toBeInTheDocument();
    expect(screen.getByText("payout unconfirmed")).toBeInTheDocument();
  });

  it("states the newest-first window and that newer rows cannot be outside it", () => {
    const results = Array.from({ length: 200 }, (_, index) =>
      result({ match_id: index + 1 }),
    );
    render(<ResultsTable results={results} />);
    expect(
      screen.getByText(/the newest 200 results by kickoff time \(newest first\)/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/newer results cannot fall outside this window, older ones can/),
    ).toBeInTheDocument();
  });

  it("states the whole set when the API returned fewer results than the page size", () => {
    render(<ResultsTable results={[result({ match_id: 1 })]} />);
    expect(
      screen.getByText(/all 1 results by kickoff time \(newest first\)/),
    ).toBeInTheDocument();
  });

  it("renders an explicit unavailable state when the source is missing", () => {
    render(<ResultsTable results={null} />);
    expect(screen.getByText("Results unavailable")).toBeInTheDocument();
  });

  it("renders an empty state when no result is recorded", () => {
    render(<ResultsTable results={[]} />);
    expect(screen.getByText("No results yet")).toBeInTheDocument();
  });
});

describe("ClvCard", () => {
  it("renders the five metrics, the champion identity and the three mandatory notes", () => {
    render(<ClvCard models={[model({})]} />);
    expect(screen.getByText("+1.2%")).toBeInTheDocument();
    expect(screen.getByText("58.3%")).toBeInTheDocument();
    expect(screen.getByText("36")).toBeInTheDocument();
    expect(screen.getByText("0.1923")).toBeInTheDocument();
    expect(screen.getByText("0.5512")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    expect(screen.getByText("lightgbm")).toBeInTheDocument();
    expect(
      screen.getByText(/CLV is the only evidence available before wins and losses accumulate\. With clv_n = 36 so far, it is a weak signal, not proof\./),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No CLV time series and no per-bet CLV exist in v1 — no endpoint exposes either\./),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/The ledger's execution price never enters CLV: it is computed in the ML layer from the model's fair price against the closing price/),
    ).toBeInTheDocument();
  });

  it("renders an explicit unavailable state when /models is missing", () => {
    render(<ClvCard models={null} />);
    expect(screen.getByText("CLV unavailable")).toBeInTheDocument();
  });

  it("says so when the registry has no champion 1x2 version", () => {
    render(<ClvCard models={[model({ id: 3, target: "handicap", status: "champion" })]} />);
    expect(screen.getByText("No champion 1x2 version")).toBeInTheDocument();
  });

  it("keeps the champion identity and says so when the version reports no metrics", () => {
    render(<ClvCard models={[model({ metrics: {} })]} />);
    expect(screen.getByText("No metrics reported")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
  });
});
