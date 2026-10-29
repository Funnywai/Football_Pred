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

const EQUITY: EquityPoint[] = [
  { t: null, bankroll: 1000 },
  { t: "2026-10-15T00:00:00Z", bankroll: 1005 },
];

const loaded = {
  variant: "a_only" as const,
  summary: SUMMARY,
  equity: EQUITY,
  bets: { rows: [BET], total: 1, newestFirst: true },
  decisions: [DECISION],
};

const empty = {
  variant: "a_only" as const,
  summary: { ...SUMMARY, bankroll: 1000, n_bets: 0, n_settled: 0, stakes_total: 0, realized_profit: 0, roi: 0, yield_pct: 0 },
  equity: [{ t: null, bankroll: 1000 }],
  bets: { rows: [], total: 0, newestFirst: true },
  decisions: [],
};

const unavailable = {
  variant: "a_only" as const,
  summary: null,
  equity: null,
  bets: null,
  decisions: null,
};

const loadAgentData = vi.fn();

vi.mock("@/lib/agent-data", () => ({
  AGENT_DECISIONS_LIMIT: 100,
  loadAgentData: (variant: "a_only" | "abc" = "a_only") => loadAgentData(variant),
}));

beforeEach(() => {
  loadAgentData.mockReset();
});

describe("/agent — loaded", () => {
  it("renders the paper-only banner, KPIs, decisions and paper bets", async () => {
    loadAgentData.mockResolvedValue(loaded);
    render(await AgentPage({ searchParams: Promise.resolve({}) }));

    expect(
      screen.getByText(/Agent paper book — paper only\. Production bankroll and the shadow ledger are unchanged\./),
    ).toBeInTheDocument();
    expect(screen.getAllByText("HK$1,005.00").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("run-2026-10-15")).toBeInTheDocument();
    expect(screen.getByText("edge above threshold and data fresh")).toBeInTheDocument();
    expect(screen.getByText("Agent paper book bets (paper only).")).toBeInTheDocument();
    expect(screen.getByText("/agent/equity-curve?variant=a_only")).toBeInTheDocument();
    expect(
      screen.getByText("/agent/summary?variant=a_only + /agent/bets?variant=a_only"),
    ).toBeInTheDocument();
  });
});


describe("/agent — A+B+C variant", () => {
  it("switches the variant, books and decision agent filter", async () => {
    loadAgentData.mockResolvedValue({
      ...loaded,
      variant: "abc" as const,
      decisions: [{ ...DECISION, agent: "decision", reason: "approved: lineups complete" }],
    });
    render(await AgentPage({ searchParams: Promise.resolve({ variant: "abc" }) }));

    expect(loadAgentData).toHaveBeenCalledWith("abc");
    expect(screen.getByRole("link", { name: "A+B+C" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "A-only" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.getByText("A + B + C paper decisions and paper bets.")).toBeInTheDocument();
    expect(screen.getByText("/agent/summary?variant=abc + /agent/bets?variant=abc")).toBeInTheDocument();
    expect(screen.getByText("/agent/decisions?agent=decision&limit=100")).toBeInTheDocument();
    expect(screen.getByText("approved: lineups complete")).toBeInTheDocument();
  });
});

describe("/agent — empty", () => {
  it("states that there are no decisions or paper bets yet", async () => {
    loadAgentData.mockResolvedValue(empty);
    render(await AgentPage({ searchParams: Promise.resolve({}) }));

    expect(screen.getByText("No agent decisions yet")).toBeInTheDocument();
    expect(screen.getByText("No agent bets yet")).toBeInTheDocument();
  });
});

describe("/agent — unavailable", () => {
  it("renders an explicit unavailable state for every agent source", async () => {
    loadAgentData.mockResolvedValue(unavailable);
    render(await AgentPage({ searchParams: Promise.resolve({}) }));

    expect(screen.getByText("KPI data unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("the API did not return /agent/summary?variant=a_only"),
    ).toBeInTheDocument();
    expect(screen.getByText("Equity curve unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("the API did not return /agent/equity-curve?variant=a_only"),
    ).toBeInTheDocument();
    expect(screen.getByText("Agent decisions unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("the API did not return /agent/decisions"),
    ).toBeInTheDocument();
    expect(screen.getByText("Agent bets unavailable")).toBeInTheDocument();
    expect(screen.getByText("the API did not return /agent/bets")).toBeInTheDocument();
  });
});
