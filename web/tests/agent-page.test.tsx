import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentPage from "@/app/(dashboard)/agent/page";
import type { AgentDecision } from "@/lib/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: () => {} }),
}));

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

const loadAgentDecisionsData = vi.fn();

vi.mock("@/lib/agent-data", () => ({
  AGENT_DECISIONS_LIMIT: 100,
  loadAgentDecisionsData: (variant: "a_only" | "abc" = "a_only") =>
    loadAgentDecisionsData(variant),
}));

beforeEach(() => {
  loadAgentDecisionsData.mockReset();
  loadAgentDecisionsData.mockResolvedValue({
    variant: "a_only",
    decisions: [DECISION],
  });
});

describe("/agent — loaded", () => {
  it("renders the decision audit only, plus a link to the ledger paper book", async () => {
    render(await AgentPage({ searchParams: Promise.resolve({}) }));

    expect(loadAgentDecisionsData).toHaveBeenCalledWith("a_only");
    expect(screen.getByRole("heading", { name: "Agent" })).toBeInTheDocument();
    expect(
      screen.getByText(
        /Agent decisions are paper only\. Production bankroll and the shadow ledger are unchanged\./,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("run-2026-10-15")).toBeInTheDocument();
    expect(screen.getByText("edge above threshold and data fresh")).toBeInTheDocument();
    expect(screen.getByText("/agent/decisions?agent=risk&limit=100")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open the A-only paper book" }),
    ).toHaveAttribute("href", "/ledger?view=agent&variant=a_only");

    // The paper book moved to the Ledger; none of it renders here any more.
    expect(
      screen.queryByRole("heading", { name: "Agent KPI strip" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Agent equity / money curve" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Agent paper bets" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("/agent/equity-curve?variant=a_only")).not.toBeInTheDocument();
  });
});

describe("/agent — A+B+C variant", () => {
  it("switches the variant and the decision agent filter", async () => {
    loadAgentDecisionsData.mockResolvedValue({
      variant: "abc",
      decisions: [
        { ...DECISION, agent: "decision", reason: "approved: lineups complete" },
      ],
    });
    render(await AgentPage({ searchParams: Promise.resolve({ variant: "abc" }) }));

    expect(loadAgentDecisionsData).toHaveBeenCalledWith("abc");
    expect(screen.getByRole("link", { name: "A+B+C" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "A-only" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(
      screen.getByText(/A \+ B \+ C decision audit — the gates behind the paper book\./),
    ).toBeInTheDocument();
    expect(screen.getByText("/agent/decisions?agent=decision&limit=100")).toBeInTheDocument();
    expect(screen.getByText("approved: lineups complete")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open the A+B+C paper book" }),
    ).toHaveAttribute("href", "/ledger?view=agent&variant=abc");
  });
});

describe("/agent — empty", () => {
  it("states that there are no decisions yet", async () => {
    loadAgentDecisionsData.mockResolvedValue({ variant: "a_only", decisions: [] });
    render(await AgentPage({ searchParams: Promise.resolve({}) }));

    expect(screen.getByText("No agent decisions yet")).toBeInTheDocument();
  });
});

describe("/agent — unavailable", () => {
  it("renders an explicit unavailable state for the decision source", async () => {
    loadAgentDecisionsData.mockResolvedValue({ variant: "a_only", decisions: null });
    render(await AgentPage({ searchParams: Promise.resolve({}) }));

    expect(screen.getByText("Agent decisions unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("the API did not return /agent/decisions"),
    ).toBeInTheDocument();
  });
});
