import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LedgerPage from "@/app/(dashboard)/ledger/page";
import type { Bet, BetSummary, EquityPoint } from "@/lib/types";

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

const loadPerformanceData = vi.fn();
const loadClvViewData = vi.fn();
const loadAgentLedgerData = vi.fn();

vi.mock("@/lib/performance-data", () => ({
  loadPerformanceData: (book: string) => loadPerformanceData(book),
  loadClvViewData: () => loadClvViewData(),
}));

vi.mock("@/lib/agent-data", () => ({
  loadAgentLedgerData: (variant: "a_only" | "abc" = "a_only") =>
    loadAgentLedgerData(variant),
}));

function performanceData(book: string) {
  return {
    now: new Date("2026-10-15T12:00:00Z"),
    book,
    summary: null,
    bets: null,
    equity: null,
    predictions: null,
    results: null,
    jobs: null,
    runs: null,
    data: null,
    models: null,
    clv: null,
  };
}

beforeEach(() => {
  loadPerformanceData.mockReset();
  loadClvViewData.mockReset();
  loadAgentLedgerData.mockReset();
  loadPerformanceData.mockImplementation(async (book: string) => performanceData(book));
  loadClvViewData.mockResolvedValue({ models: null, clv: null });
  loadAgentLedgerData.mockResolvedValue({
    variant: "a_only",
    summary: SUMMARY,
    equity: EQUITY,
    bets: { rows: [BET], total: 1, newestFirst: true },
  });
});

const SHADOW_BANNER = "Shadow ledger — paper only. Production bankroll is unchanged.";

describe("/ledger — production", () => {
  it("renders the production panels and defaults to the production view", async () => {
    render(await LedgerPage({ searchParams: Promise.resolve({}) }));

    expect(screen.getByRole("heading", { name: "Ledger" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Production" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(loadPerformanceData).toHaveBeenCalledWith("production");
    for (const title of [
      "KPI strip",
      "Equity / money curve",
      "AI pipeline",
      "Signal vs execution price",
      "All bets",
      "Matches x predictions",
      "Results",
    ]) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }
    expect(screen.getByText("/bets/equity-curve?book=production")).toBeInTheDocument();
    expect(screen.queryByText(SHADOW_BANNER)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "CLV & Calibration" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Agent KPI strip" }),
    ).not.toBeInTheDocument();
  });
});

describe("/ledger — shadow", () => {
  it("treats the legacy ?book=shadow URL as the shadow view", async () => {
    render(await LedgerPage({ searchParams: Promise.resolve({ book: "shadow" }) }));

    expect(screen.getByText(SHADOW_BANNER)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Shadow" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(loadPerformanceData).toHaveBeenCalledWith("shadow");
    expect(screen.getByText("/bets/equity-curve?book=shadow")).toBeInTheDocument();
  });
});

describe("/ledger — agent", () => {
  it("renders the agent paper book without the decisions table", async () => {
    render(
      await LedgerPage({
        searchParams: Promise.resolve({ view: "agent", variant: "a_only" }),
      }),
    );

    expect(loadAgentLedgerData).toHaveBeenCalledWith("a_only");
    expect(loadPerformanceData).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Agent" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getByText(
        /Agent paper book — paper only\. Production bankroll and the shadow ledger are unchanged\./,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Agent KPI strip" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Agent equity / money curve" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Agent paper bets" })).toBeInTheDocument();
    expect(screen.getAllByText("HK$1,005.00").length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText("/agent/summary?variant=a_only + /agent/bets?variant=a_only"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open the A-only decision audit" }),
    ).toHaveAttribute("href", "/agent?variant=a_only");
    expect(
      screen.queryByRole("heading", { name: "Agent decisions" }),
    ).not.toBeInTheDocument();
  });

  it("switches the paper book variant through the URL", async () => {
    loadAgentLedgerData.mockResolvedValue({
      variant: "abc",
      summary: SUMMARY,
      equity: EQUITY,
      bets: { rows: [BET], total: 1, newestFirst: true },
    });
    render(
      await LedgerPage({
        searchParams: Promise.resolve({ view: "agent", variant: "abc" }),
      }),
    );

    expect(loadAgentLedgerData).toHaveBeenCalledWith("abc");
    expect(screen.getByRole("link", { name: "A+B+C" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getByRole("link", { name: "Open the A+B+C decision audit" }),
    ).toHaveAttribute("href", "/agent?variant=abc");
    expect(screen.getByText("/agent/equity-curve?variant=abc")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Agent decisions" }),
    ).not.toBeInTheDocument();
  });
});

describe("/ledger — CLV", () => {
  it("renders only the CLV card and gate on the CLV view", async () => {
    render(await LedgerPage({ searchParams: Promise.resolve({ view: "clv" }) }));

    expect(
      screen.getByRole("heading", { name: "CLV & Calibration" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("/clv/summary?book=production + /models"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "CLV & Calibration" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.queryByText(SHADOW_BANNER)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "KPI strip" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "All bets" })).not.toBeInTheDocument();
    expect(loadPerformanceData).not.toHaveBeenCalled();
  });
});
