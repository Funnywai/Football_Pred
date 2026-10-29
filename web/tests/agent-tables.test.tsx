import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentBetsTable } from "@/components/tables/AgentBetsTable";
import { AgentDecisionsTable } from "@/components/tables/AgentDecisionsTable";
import type { AgentDecision, Bet } from "@/lib/types";

function decision(overrides: Partial<AgentDecision>): AgentDecision {
  return {
    id: 1,
    run_id: "run-1",
    match_id: 29164,
    model_version_id: 1,
    target: "1x2",
    outcome: "H",
    action: "bet",
    stake: 10,
    odds: 2.48,
    edge: 0.05,
    signal_edge: 0.06,
    confidence: 0.7,
    agent: "risk",
    reason: "edge above threshold",
    input_snapshot: {},
    evaluated_at: "2026-10-15T10:00:00Z",
    league_code: "EPL",
    home_team: "Arsenal",
    away_team: "Chelsea",
    ...overrides,
  };
}

function bet(overrides: Partial<Bet>): Bet {
  return {
    id: 7,
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

describe("AgentDecisionsTable", () => {
  it("renders run, match identity, action and reason", () => {
    render(<AgentDecisionsTable decisions={[decision({})]} limit={100} />);

    expect(screen.getByText("run-1")).toBeInTheDocument();
    expect(screen.getByText("Arsenal v Chelsea")).toBeInTheDocument();
    expect(screen.getByText("bet")).toBeInTheDocument();
    expect(screen.getByText("edge above threshold")).toBeInTheDocument();
  });

  it("labels no_bet and falls back to the match id when team fields are absent", () => {
    render(
      <AgentDecisionsTable
        decisions={[
          decision({
            id: 2,
            action: "no_bet",
            stake: null,
            home_team: null,
            away_team: null,
            match_id: 29160,
          }),
        ]}
        limit={100}
      />,
    );

    expect(screen.getByText("no bet")).toBeInTheDocument();
    expect(screen.getByText("match #29160")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("searches the fetched window", () => {
    render(
      <AgentDecisionsTable
        decisions={[
          decision({ id: 1, league_code: "EPL" }),
          decision({ id: 2, league_code: "LALIGA", run_id: "run-2" }),
        ]}
        limit={100}
      />,
    );
    expect(screen.getAllByRole("row")).toHaveLength(3);

    fireEvent.change(screen.getByLabelText("Search agent decisions"), {
      target: { value: "laliga" },
    });
    expect(screen.getAllByRole("row")).toHaveLength(2);
  });

  it("renders an empty state when no decision exists", () => {
    render(<AgentDecisionsTable decisions={[]} limit={100} />);
    expect(screen.getByText("No agent decisions yet")).toBeInTheDocument();
  });

  it("renders an unavailable state when the endpoint failed", () => {
    render(<AgentDecisionsTable decisions={null} limit={100} />);
    expect(screen.getByText("Agent decisions unavailable")).toBeInTheDocument();
  });
});

describe("AgentBetsTable", () => {
  it("renders the agent paper-book copy and the bet rows", () => {
    render(
      <AgentBetsTable bets={{ rows: [bet({})], total: 1, newestFirst: true }} />,
    );

    expect(screen.getByText("Agent paper book bets (paper only).")).toBeInTheDocument();
    expect(screen.queryByText("All ledger bets")).not.toBeInTheDocument();
    expect(screen.queryByText("All shadow ledger bets (paper only).")).not.toBeInTheDocument();
    expect(screen.getAllByText("Arsenal v Chelsea").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the agent empty and unavailable states", () => {
    const { rerender } = render(
      <AgentBetsTable bets={{ rows: [], total: 0, newestFirst: true }} />,
    );
    expect(screen.getByText("No agent bets yet")).toBeInTheDocument();

    rerender(<AgentBetsTable bets={null} />);
    expect(screen.getByText("Agent bets unavailable")).toBeInTheDocument();
  });
});
