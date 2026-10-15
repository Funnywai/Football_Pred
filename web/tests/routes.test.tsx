import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import TechnicalPage from "@/app/(dashboard)/technical/page";
import { PERFORMANCE_SECTIONS, TECHNICAL_SECTIONS } from "@/lib/sections";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: () => {} }),
}));

vi.mock("@/lib/performance-data", () => ({
  loadPerformanceData: async () => ({
    now: new Date("2026-10-15T12:00:00Z"),
    summary: null,
    bets: null,
    equity: null,
    predictions: null,
    results: null,
    jobs: null,
    runs: null,
    data: null,
    models: null,
  }),
}));

vi.mock("@/lib/technical-data", () => ({
  LOGS_LIMIT: 100,
  RUNS_LIMIT: 200,
  loadTechnicalData: async () => ({
    now: new Date("2026-10-15T12:00:00Z"),
    status: null,
    jobs: null,
    runs: null,
    logs: null,
    data: null,
    models: null,
    logLevel: null,
  }),
}));

import PerformancePage from "@/app/(dashboard)/performance/page";

// The exact unavailable strings each section renders when every loader returns null,
// read from the components that emit them. A section that regresses to a shell, a blank
// panel, or a reworded state fails here.
const PERFORMANCE_UNAVAILABLE: Array<[string, string]> = [
  ["KPI data unavailable", "the API did not return /bets/summary"],
  ["Equity curve unavailable", "the API did not return /bets/equity-curve"],
  ["Pipeline unavailable", "the API did not return /ops/jobs or /ops/data"],
  ["Signal vs execution unavailable", "the API did not return /bets or /predictions"],
  ["Bets unavailable", "the API did not return /bets"],
  ["Matches x predictions unavailable", "the API did not return /predictions or /bets"],
  ["Results unavailable", "the API did not return /results"],
  ["CLV unavailable", "the API did not return /models"],
];

const TECHNICAL_UNAVAILABLE: Array<[string, string]> = [
  ["Log stream unavailable", "the API did not return /ops/logs"],
  ["Scheduler unavailable", "the API did not return /ops/jobs"],
  ["Runs unavailable", "the API did not return /ops/runs"],
  ["Freshness unavailable", "the API did not return /ops/data"],
  ["DB size unavailable", "the API did not return /ops/data"],
  ["Model versions unavailable", "the API did not return /models"],
  ["Environment unavailable", "the API did not return /ops/status"],
];

function expectUnavailableStates(pairs: Array<[string, string]>): void {
  const detailCounts = new Map<string, number>();
  for (const [title, detail] of pairs) {
    expect(screen.getByText(title)).toBeInTheDocument();
    detailCounts.set(detail, (detailCounts.get(detail) ?? 0) + 1);
  }
  for (const [detail, count] of detailCounts) {
    expect(screen.getAllByText(detail)).toHaveLength(count);
  }
}

describe("route smoke — /performance", () => {
  it("renders every section heading and the explicit unavailable state of every section", async () => {
    render(await PerformancePage());

    for (const section of PERFORMANCE_SECTIONS) {
      expect(screen.getByRole("heading", { name: section.title })).toBeInTheDocument();
    }
    expectUnavailableStates(PERFORMANCE_UNAVAILABLE);
    expect(screen.queryByText("pending — next increment")).not.toBeInTheDocument();
  });
});

describe("route smoke — /technical", () => {
  it("renders every technical section heading with an explicit unavailable state", async () => {
    render(await TechnicalPage({ searchParams: Promise.resolve({}) }));

    for (const section of TECHNICAL_SECTIONS) {
      expect(screen.getByRole("heading", { name: section.title })).toBeInTheDocument();
    }
    expectUnavailableStates(TECHNICAL_UNAVAILABLE);
    expect(screen.queryByText("pending — next increment")).not.toBeInTheDocument();
  });
});
