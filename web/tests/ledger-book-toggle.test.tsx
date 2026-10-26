import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LedgerBookToggle } from "@/components/ledger/LedgerBookToggle";
import { normalizeLedgerBook } from "@/lib/ledger";

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
}));

import PerformancePage from "@/app/(dashboard)/performance/page";

describe("LedgerBookToggle", () => {
  it("links each segment to its URL-backed book", () => {
    render(<LedgerBookToggle book="production" />);

    const nav = screen.getByRole("navigation", { name: "Ledger book" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Production" })).toHaveAttribute(
      "href",
      "/performance",
    );
    expect(screen.getByRole("link", { name: "Shadow · paper" })).toHaveAttribute(
      "href",
      "/performance?book=shadow",
    );
  });

  it("carries the active book with aria-current, not colour alone", () => {
    const { rerender } = render(<LedgerBookToggle book="production" />);

    expect(screen.getByRole("link", { name: "Production" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Shadow · paper" })).not.toHaveAttribute(
      "aria-current",
    );

    rerender(<LedgerBookToggle book="shadow" />);

    expect(screen.getByRole("link", { name: "Production" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.getByRole("link", { name: "Shadow · paper" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});

describe("normalizeLedgerBook", () => {
  it("accepts shadow and defaults everything else to production", () => {
    expect(normalizeLedgerBook("shadow")).toBe("shadow");
    expect(normalizeLedgerBook("production")).toBe("production");
    expect(normalizeLedgerBook("bogus")).toBe("production");
    expect(normalizeLedgerBook(undefined)).toBe("production");
  });
});

describe("Performance page book switch", () => {
  it("defaults to production with no shadow banner", async () => {
    render(await PerformancePage({ searchParams: Promise.resolve({}) }));

    expect(
      screen.queryByText("Shadow ledger — paper only. Production bankroll is unchanged."),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Production" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByText("/bets/equity-curve")).toBeInTheDocument();
  });

  it("renders the shadow banner, active segment and shadow source labels", async () => {
    render(
      await PerformancePage({ searchParams: Promise.resolve({ book: "shadow" }) }),
    );

    expect(
      screen.getByText("Shadow ledger — paper only. Production bankroll is unchanged."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Shadow · paper" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByText("/bets/equity-curve?book=shadow")).toBeInTheDocument();
    expect(screen.getByText("/clv/summary?book=shadow + /models")).toBeInTheDocument();
  });

  it("normalizes an unknown book to production", async () => {
    render(
      await PerformancePage({ searchParams: Promise.resolve({ book: "bogus" }) }),
    );

    expect(
      screen.queryByText("Shadow ledger — paper only. Production bankroll is unchanged."),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Production" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
