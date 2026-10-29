import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentPage from "@/app/(dashboard)/agent/page";
import type { AgentDecision, Bet, BetSummary, EquityPoint } from "@/lib/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: () => {} }),
}));

const SUMMARY: BetSummary = {
  initial_bankroll: 1000,
  bankroll: 1005,
  n_bets: 1,
  n_settled: 1,
  n_open: 0,
  stakes_total: 10,
  open_stakes: 0,
  realized_profit: 5,
  roi: 0.5,
  yield_pct: 0.5,
};

const BET: Bet = {
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
};

const EQUITY: EquityPoint[] = [
  { t: null, bankroll: 1000 },
  { t: "2026-10-15T00:00:00Z", bankroll: 1005 },
];

const DECISION: AgentDecision = {
  id: 1,
  run_id: "run-2026-10-15",
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
  reason: "edge above threshold and data fresh",
  input_snapshot: {},
  evaluated_at: "2026-10-15T10:00:00Z",
  league_code: "EPL",
  home_team: "Arsenal",
  away_team: "Chelsea",
};

const loadAgentLedgerData = vi.fn();
const loadAgentDecisionsData = vi.fn();

vi.mock("@/lib/agent-data", () => ({
  AGENT_DECISIONS_LIMIT: 100,
  loadAgentLedgerData: (variant: "a_only" | "abc" = "a_only") =>
    loadAgentLedgerData(variant),
  loadAgentDecisionsData: (variant: "a_only" | "abc" = "a_only") =>
    loadAgentDecisionsData(variant),
}));

beforeEach(() => {
  loadAgentLedgerData.mockReset();
  loadAgentDecisionsData.mockReset();
  loadAgentLedgerData.mockResolvedValue({
    variant: "a_only",
    summary: SUMMARY,
    equity: EQUITY,
    bets: { rows: [BET], total: 1, newestFirst: true },
  });
  loadAgentDecisionsData.mockResolvedValue({
    variant: "a_only",
    decisions: [DECISION],
  });
});

describe("/agent — loaded", () => {
  it("renders the paper book and the decision audit from both loaders", async () => {
    render(await AgentPage({ searchParams: Promise.resolve({}) }));

    expect(loadAgentLedgerData).toHaveBeenCalledWith("a_only");
    expect(loadAgentDecisionsData).toHaveBeenCalledWith("a_only");
    expect(screen.getByRole("heading", { name: "Agent" })).toBeInTheDocument();
    expect(
      screen.getByText(
        /Agent decisions are paper only\. Production bankroll and the shadow ledger are unchanged\./,
      ),
    ).toBeInTheDocument();

    for (const title of [
      "Agent KPI strip",
      "Agent equity / money curve",
      "Agent paper bets",
      "Agent decisions",
    ]) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }

    expect(screen.getAllByText("HK$1,005.00").length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText("/agent/summary?variant=a_only + /agent/bets?variant=a_only"),
    ).toBeInTheDocument();
    expect(screen.getByText("/agent/equity-curve?variant=a_only")).toBeInTheDocument();
    expect(screen.getByText("/agent/bets?variant=a_only")).toBeInTheDocument();
    expect(screen.getByText("run-2026-10-15")).toBeInTheDocument();
    expect(screen.getByText("edge above threshold and data fresh")).toBeInTheDocument();
    expect(screen.getByText("/agent/decisions?agent=risk&limit=100")).toBeInTheDocument();

    // The paper book no longer lives behind a Ledger link.
    expect(screen.queryByText(/lives in the Ledger/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Open the .* paper book/ }),
    ).not.toBeInTheDocument();
  });
});

describe("/agent — A+B+C variant", () => {
  it("switches every panel and source label to the A+B+C variant", async () => {
    loadAgentLedgerData.mockResolvedValue({
      variant: "abc",
      summary: SUMMARY,
      equity: EQUITY,
      bets: { rows: [BET], total: 1, newestFirst: true },
    });
    loadAgentDecisionsData.mockResolvedValue({
      variant: "abc",
      decisions: [
        { ...DECISION, agent: "decision", reason: "approved: lineups complete" },
      ],
    });
    render(await AgentPage({ searchParams: Promise.resolve({ variant: "abc" }) }));

    expect(loadAgentLedgerData).toHaveBeenCalledWith("abc");
    expect(loadAgentDecisionsData).toHaveBeenCalledWith("abc");
    expect(screen.getByRole("link", { name: "A+B+C" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "A-only" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(
      screen.getByText(/A \+ B \+ C paper book and decision audit/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("/agent/summary?variant=abc + /agent/bets?variant=abc"),
    ).toBeInTheDocument();
    expect(screen.getByText("/agent/equity-curve?variant=abc")).toBeInTheDocument();
    expect(screen.getByText("/agent/bets?variant=abc")).toBeInTheDocument();
    expect(screen.getByText("/agent/decisions?agent=decision&limit=100")).toBeInTheDocument();
    expect(screen.getByText("approved: lineups complete")).toBeInTheDocument();
  });
});

describe("/agent — empty", () => {
  it("states that there are no agent bets or decisions yet", async () => {
    loadAgentLedgerData.mockResolvedValue({
      variant: "a_only",
      summary: SUMMARY,
      equity: [],
      bets: { rows: [], total: 0, newestFirst: true },
    });
    loadAgentDecisionsData.mockResolvedValue({ variant: "a_only", decisions: [] });
    render(await AgentPage({ searchParams: Promise.resolve({}) }));

    expect(screen.getByText("No agent bets yet")).toBeInTheDocument();
    expect(screen.getByText("No agent decisions yet")).toBeInTheDocument();
  });
});

describe("/agent — unavailable", () => {
  it("renders an explicit unavailable state for every paper-book source", async () => {
    loadAgentLedgerData.mockResolvedValue({
      variant: "a_only",
      summary: null,
      equity: null,
      bets: null,
    });
    loadAgentDecisionsData.mockResolvedValue({ variant: "a_only", decisions: null });
    render(await AgentPage({ searchParams: Promise.resolve({}) }));

    expect(screen.getByText("KPI data unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("the API did not return /agent/summary?variant=a_only"),
    ).toBeInTheDocument();
    expect(screen.getByText("Equity curve unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("the API did not return /agent/equity-curve?variant=a_only"),
    ).toBeInTheDocument();
    expect(screen.getByText("Agent bets unavailable")).toBeInTheDocument();
    expect(screen.getByText("Agent decisions unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("the API did not return /agent/decisions"),
    ).toBeInTheDocument();
  });
});
