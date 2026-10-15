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

const IMPLEMENTED = new Set([
  "kpi-strip",
  "equity-curve",
  "pipeline",
  "signal-vs-execution",
  "bets",
  "matches-predictions",
  "results",
  "clv",
]);

describe("route smoke — /performance", () => {
  it("renders every section heading, with shells only for the unimplemented ones", async () => {
    render(await PerformancePage());

    for (const section of PERFORMANCE_SECTIONS) {
      expect(screen.getByRole("heading", { name: section.title })).toBeInTheDocument();
    }
    const remaining = PERFORMANCE_SECTIONS.filter((section) => !IMPLEMENTED.has(section.id));
    expect(screen.queryAllByText("pending — next increment")).toHaveLength(remaining.length);
  });
});

describe("route smoke — /technical", () => {
  it("renders every technical section heading with an explicit unavailable state", async () => {
    render(await TechnicalPage({ searchParams: Promise.resolve({}) }));

    for (const section of TECHNICAL_SECTIONS) {
      expect(screen.getByRole("heading", { name: section.title })).toBeInTheDocument();
    }
    expect(screen.queryByText("pending — next increment")).not.toBeInTheDocument();
  });
});
