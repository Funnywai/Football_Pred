import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClvCard } from "@/components/clv/ClvCard";
import { ResultsTable } from "@/components/tables/ResultsTable";
import { SignalVsExecutionTable } from "@/components/tables/SignalVsExecutionTable";
import type { Bet, ModelVersion, Result } from "@/lib/types";

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

  it("shows 10 rows, reveals 10 more, and searches the window", () => {
    const results = Array.from({ length: 30 }, (_, index) =>
      result({ match_id: index + 1, source: index < 5 ? "hkjc" : "football_data" }),
    );
    render(<ResultsTable results={results} />);
    expect(screen.getAllByRole("row")).toHaveLength(11);
    fireEvent.click(screen.getByRole("button", { name: /Expand/ }));
    expect(screen.getAllByRole("row")).toHaveLength(21);
    fireEvent.change(screen.getByLabelText("Search results"), { target: { value: "hkjc" } });
    expect(screen.getAllByRole("row").length).toBeLessThan(11);
    expect(screen.getByText('5 of 5 shown · matching "hkjc"')).toBeInTheDocument();
  });

  it("keeps the window sentence byte-identical while filtered", () => {
    const results = Array.from({ length: 200 }, (_, index) => result({ match_id: index + 1 }));
    render(<ResultsTable results={results} />);
    const note =
      "Window: the newest 200 results by kickoff time (newest first); newer results cannot fall outside this window, older ones can.";
    expect(screen.getByText(note)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search results"), { target: { value: "zzz" } });
    expect(screen.getByText(note)).toBeInTheDocument();
    expect(screen.getByText(/No row in this window matches "zzz"/)).toBeInTheDocument();
  });
});

describe("ClvCard", () => {
  it("renders the five metrics, the champion identity and the three mandatory notes", () => {
    render(<ClvCard models={[model({})]} summary={null} />);
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
    render(<ClvCard models={null} summary={null} />);
    expect(screen.getByText("CLV unavailable")).toBeInTheDocument();
  });

  it("says so when the registry has no champion 1x2 version", () => {
    render(<ClvCard models={[model({ id: 3, target: "handicap", status: "champion" })]} summary={null} />);
    expect(screen.getByText("No champion 1x2 version")).toBeInTheDocument();
  });

  it("keeps the champion identity and says so when the version reports no metrics", () => {
    render(<ClvCard models={[model({ metrics: {} })]} summary={null} />);
    expect(screen.getByText("No metrics reported")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
  });
});

describe("SignalVsExecutionTable", () => {
  it("reveals and searches the signal table without touching its window sentence", () => {
    const bets = Array.from({ length: 12 }, (_, index) =>
      bet({ id: index + 1, league_code: index < 5 ? "LALIGA" : "EPL" }),
    );
    render(
      <SignalVsExecutionTable
        bets={{ rows: bets, total: 12, newestFirst: true }}
        predictions={[]}
      />,
    );
    expect(screen.getAllByRole("row")).toHaveLength(11);
    fireEvent.click(screen.getByRole("button", { name: /Show all/ }));
    expect(screen.getAllByRole("row").length).toBeGreaterThan(11);
    fireEvent.change(screen.getByLabelText("Search signal vs execution"), {
      target: { value: "laliga" },
    });
    expect(screen.getAllByRole("row").length).toBeLessThan(11);
    expect(screen.getByText('5 of 5 shown · matching "laliga"')).toBeInTheDocument();
    expect(screen.getByText(/joined with .*predictions\?limit=200/)).toBeInTheDocument();
  });
});
