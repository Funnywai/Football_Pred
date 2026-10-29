import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import LedgerPage from "@/app/(dashboard)/ledger/page";
import PerformancePage from "@/app/(dashboard)/performance/page";
import TechnicalPage from "@/app/(dashboard)/technical/page";
import Home from "@/app/page";
import { TECHNICAL_SECTIONS } from "@/lib/sections";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: () => {} }),
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
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

// The exact unavailable strings each technical section renders when every loader returns
// null, read from the components that emit them. A section that regresses to a shell, a
// blank panel, or a reworded state fails here.
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

describe("root redirect", () => {
  it("sends / to the agent page", () => {
    expect(() => Home()).toThrow("REDIRECT:/agent");
  });
});

describe("legacy /ledger redirect", () => {
  it("defaults to the A-only agent page", async () => {
    await expect(
      LedgerPage({ searchParams: Promise.resolve({}) }),
    ).rejects.toThrow("REDIRECT:/agent");
  });

  it("carries an agent variant bookmark through", async () => {
    await expect(
      LedgerPage({ searchParams: Promise.resolve({ view: "agent", variant: "abc" }) }),
    ).rejects.toThrow("REDIRECT:/agent?variant=abc");
  });

  it("keeps the A-only variant on the default agent page", async () => {
    await expect(
      LedgerPage({ searchParams: Promise.resolve({ view: "agent", variant: "a_only" }) }),
    ).rejects.toThrow("REDIRECT:/agent");
  });

  it("sends the retired production/shadow/CLV views to the agent page", async () => {
    for (const view of ["production", "shadow", "clv"]) {
      await expect(
        LedgerPage({ searchParams: Promise.resolve({ view }) }),
      ).rejects.toThrow("REDIRECT:/agent");
    }
  });
});

describe("legacy /performance redirect", () => {
  it("defaults to the A-only agent page", async () => {
    await expect(
      PerformancePage({ searchParams: Promise.resolve({}) }),
    ).rejects.toThrow("REDIRECT:/agent");
  });

  it("carries a variant bookmark through", async () => {
    await expect(
      PerformancePage({ searchParams: Promise.resolve({ variant: "abc" }) }),
    ).rejects.toThrow("REDIRECT:/agent?variant=abc");
  });

  it("keeps the A-only variant on the default agent page", async () => {
    await expect(
      PerformancePage({ searchParams: Promise.resolve({ variant: "a_only" }) }),
    ).rejects.toThrow("REDIRECT:/agent");
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
