import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BetsTable } from "@/components/tables/BetsTable";
import { TermTip } from "@/components/ui/TermTip";
import type { BetsWindow } from "@/lib/bets-window";
import { GLOSSARY } from "@/lib/glossary";
import type { Bet } from "@/lib/types";

function bet(overrides: Partial<Bet> = {}): Bet {
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

function windowOf(rows: Bet[]): BetsWindow {
  return { rows, total: rows.length, newestFirst: true };
}

function advance(ms: number): void {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

describe("TermTip", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not show a tooltip before the 3000ms delay", () => {
    render(<TermTip term="edge">Edge</TermTip>);
    const trigger = screen.getByText("Edge");

    fireEvent.pointerEnter(trigger);
    advance(2999);

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("shows the Chinese what/good/bad explanation after 3000ms", () => {
    render(<TermTip term="edge">Edge</TermTip>);
    const trigger = screen.getByText("Edge");

    fireEvent.pointerEnter(trigger);
    advance(3000);

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent(GLOSSARY.edge.what);
    expect(tooltip).toHaveTextContent(GLOSSARY.edge.good);
    expect(tooltip).toHaveTextContent(GLOSSARY.edge.bad);
    expect(tooltip.parentElement).toBe(document.body);
    expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
  });

  it("cancels the pending timer when the pointer leaves before 3000ms", () => {
    render(<TermTip term="edge">Edge</TermTip>);
    const trigger = screen.getByText("Edge");

    fireEvent.pointerEnter(trigger);
    advance(2000);
    fireEvent.pointerLeave(trigger);
    advance(2000);

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("hides an open tooltip when the pointer leaves", () => {
    render(<TermTip term="edge">Edge</TermTip>);
    const trigger = screen.getByText("Edge");

    fireEvent.pointerEnter(trigger);
    advance(3000);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    fireEvent.pointerLeave(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("shows on focus and hides on blur", () => {
    render(<TermTip term="roi">ROI</TermTip>);
    const trigger = screen.getByText("ROI");

    fireEvent.focus(trigger);
    advance(3000);
    expect(screen.getByRole("tooltip")).toHaveTextContent(GLOSSARY.roi.what);

    fireEvent.blur(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("hides an open tooltip on Escape", () => {
    render(<TermTip term="edge">Edge</TermTip>);
    const trigger = screen.getByText("Edge");

    fireEvent.pointerEnter(trigger);
    advance(3000);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("hides an open tooltip on scroll", () => {
    render(<TermTip term="edge">Edge</TermTip>);
    const trigger = screen.getByText("Edge");

    fireEvent.pointerEnter(trigger);
    advance(3000);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    fireEvent.scroll(window);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("hides an open tooltip on window resize", () => {
    render(<TermTip term="edge">Edge</TermTip>);
    const trigger = screen.getByText("Edge");

    fireEvent.pointerEnter(trigger);
    advance(3000);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    fireEvent.resize(window);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("keeps the visible table header label and explains it after the delay", () => {
    render(<BetsTable bets={windowOf([bet()])} />);
    const header = screen.getByText("Edge");

    expect(header).toBeInTheDocument();
    fireEvent.pointerEnter(header);
    advance(3000);

    expect(screen.getByRole("tooltip")).toHaveTextContent(GLOSSARY.edge.what);
  });
});
