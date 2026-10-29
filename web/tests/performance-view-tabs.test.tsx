import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PerformancePage from "@/app/(dashboard)/performance/page";
import { PerformanceViewTabs } from "@/components/performance/PerformanceViewTabs";
import { normalizePerformanceView } from "@/lib/performance-view";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: () => {} }),
}));

vi.mock("@/lib/performance-data", () => ({
  loadPerformanceData: async (book: string) => ({
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
  }),
  loadClvViewData: async () => ({ models: null, clv: null }),
}));

const SHADOW_BANNER = "Shadow ledger — paper only. Production bankroll is unchanged.";

describe("PerformanceViewTabs", () => {
  it("links all three views to their URL-backed query", () => {
    render(<PerformanceViewTabs view="production" />);

    expect(screen.getByRole("navigation", { name: "Performance view" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Production" })).toHaveAttribute(
      "href",
      "/performance?view=production",
    );
    expect(screen.getByRole("link", { name: "Shadow" })).toHaveAttribute(
      "href",
      "/performance?view=shadow",
    );
    expect(screen.getByRole("link", { name: "CLV & Calibration" })).toHaveAttribute(
      "href",
      "/performance?view=clv",
    );
  });

  it("carries the active view with aria-current, not colour alone", () => {
    const { rerender } = render(<PerformanceViewTabs view="production" />);
    expect(screen.getByRole("link", { name: "Production" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "CLV & Calibration" })).not.toHaveAttribute(
      "aria-current",
    );

    rerender(<PerformanceViewTabs view="clv" />);
    expect(screen.getByRole("link", { name: "CLV & Calibration" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Shadow" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});

describe("normalizePerformanceView", () => {
  it("accepts the three views", () => {
    expect(normalizePerformanceView("production", undefined)).toBe("production");
    expect(normalizePerformanceView("shadow", undefined)).toBe("shadow");
    expect(normalizePerformanceView("clv", undefined)).toBe("clv");
  });

  it("keeps the legacy ?book=shadow URL working as shadow", () => {
    expect(normalizePerformanceView(undefined, "shadow")).toBe("shadow");
  });

  it("defaults an unknown or absent view to production", () => {
    expect(normalizePerformanceView(undefined, undefined)).toBe("production");
    expect(normalizePerformanceView("bogus", undefined)).toBe("production");
    expect(normalizePerformanceView("bogus", "bogus")).toBe("production");
  });

  it("lets a valid view win over a conflicting legacy book", () => {
    expect(normalizePerformanceView("production", "shadow")).toBe("production");
  });
});

describe("Performance page view switch", () => {
  it("defaults to production with no shadow banner and no CLV panel", async () => {
    render(await PerformancePage({ searchParams: Promise.resolve({}) }));

    expect(screen.queryByText(SHADOW_BANNER)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Production" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByText("/bets/equity-curve?book=production")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "CLV & Calibration" }),
    ).not.toBeInTheDocument();
  });

  it("treats the legacy ?book=shadow URL as the shadow view", async () => {
    render(
      await PerformancePage({ searchParams: Promise.resolve({ book: "shadow" }) }),
    );

    expect(screen.getByText(SHADOW_BANNER)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Shadow" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByText("/bets/equity-curve?book=shadow")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "CLV & Calibration" }),
    ).not.toBeInTheDocument();
  });

  it("renders only the CLV card and gate on the CLV view", async () => {
    render(
      await PerformancePage({ searchParams: Promise.resolve({ view: "clv" }) }),
    );

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
    expect(screen.queryByRole("heading", { name: "KPI strip" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "All bets" })).not.toBeInTheDocument();
  });
});
