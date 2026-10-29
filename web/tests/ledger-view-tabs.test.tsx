import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LedgerAgentVariantTabs } from "@/components/ledger/LedgerAgentVariantTabs";
import { LedgerViewTabs } from "@/components/ledger/LedgerViewTabs";
import {
  ledgerViewBook,
  legacyPerformanceHref,
  normalizeLedgerView,
} from "@/lib/ledger-view";

describe("LedgerViewTabs", () => {
  it("links all four views to their URL-backed query", () => {
    render(<LedgerViewTabs view="production" />);

    expect(screen.getByRole("navigation", { name: "Ledger view" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Production" })).toHaveAttribute(
      "href",
      "/ledger?view=production",
    );
    expect(screen.getByRole("link", { name: "Shadow" })).toHaveAttribute(
      "href",
      "/ledger?view=shadow",
    );
    expect(screen.getByRole("link", { name: "Agent" })).toHaveAttribute(
      "href",
      "/ledger?view=agent",
    );
    expect(screen.getByRole("link", { name: "CLV & Calibration" })).toHaveAttribute(
      "href",
      "/ledger?view=clv",
    );
  });

  it("carries the active view with aria-current, not colour alone", () => {
    const { rerender } = render(<LedgerViewTabs view="production" />);
    expect(screen.getByRole("link", { name: "Production" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Agent" })).not.toHaveAttribute(
      "aria-current",
    );

    rerender(<LedgerViewTabs view="agent" />);
    expect(screen.getByRole("link", { name: "Agent" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Production" })).not.toHaveAttribute(
      "aria-current",
    );

    rerender(<LedgerViewTabs view="clv" />);
    expect(screen.getByRole("link", { name: "CLV & Calibration" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Shadow" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});

describe("LedgerAgentVariantTabs", () => {
  it("links both variants to the ledger agent view", () => {
    render(<LedgerAgentVariantTabs variant="a_only" />);

    expect(
      screen.getByRole("navigation", { name: "Agent paper book variant" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "A-only" })).toHaveAttribute(
      "href",
      "/ledger?view=agent",
    );
    expect(screen.getByRole("link", { name: "A+B+C" })).toHaveAttribute(
      "href",
      "/ledger?view=agent&variant=abc",
    );
    expect(screen.getByRole("link", { name: "A-only" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("marks the A+B+C variant as current when selected", () => {
    render(<LedgerAgentVariantTabs variant="abc" />);

    expect(screen.getByRole("link", { name: "A+B+C" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "A-only" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});

describe("normalizeLedgerView", () => {
  it("accepts the four views", () => {
    expect(normalizeLedgerView("production", undefined)).toBe("production");
    expect(normalizeLedgerView("shadow", undefined)).toBe("shadow");
    expect(normalizeLedgerView("agent", undefined)).toBe("agent");
    expect(normalizeLedgerView("clv", undefined)).toBe("clv");
  });

  it("keeps the legacy ?book=shadow URL working as shadow", () => {
    expect(normalizeLedgerView(undefined, "shadow")).toBe("shadow");
    expect(normalizeLedgerView("bogus", "shadow")).toBe("shadow");
  });

  it("defaults an unknown or absent view to production", () => {
    expect(normalizeLedgerView(undefined, undefined)).toBe("production");
    expect(normalizeLedgerView("bogus", undefined)).toBe("production");
    expect(normalizeLedgerView("bogus", "bogus")).toBe("production");
  });

  it("lets a valid view win over a conflicting legacy book", () => {
    expect(normalizeLedgerView("production", "shadow")).toBe("production");
    expect(normalizeLedgerView("agent", "shadow")).toBe("agent");
  });
});

describe("ledgerViewBook", () => {
  it("only the shadow view reads the shadow book", () => {
    expect(ledgerViewBook("production")).toBe("production");
    expect(ledgerViewBook("shadow")).toBe("shadow");
    expect(ledgerViewBook("agent")).toBe("production");
    expect(ledgerViewBook("clv")).toBe("production");
  });
});

describe("legacyPerformanceHref", () => {
  it("maps every old /performance URL to its canonical ledger view", () => {
    expect(legacyPerformanceHref({})).toBe("/ledger?view=production");
    expect(legacyPerformanceHref({ view: "production" })).toBe(
      "/ledger?view=production",
    );
    expect(legacyPerformanceHref({ view: "shadow" })).toBe("/ledger?view=shadow");
    expect(legacyPerformanceHref({ view: "clv" })).toBe("/ledger?view=clv");
    expect(legacyPerformanceHref({ book: "shadow" })).toBe("/ledger?view=shadow");
  });

  it("carries the agent variant through the redirect", () => {
    expect(legacyPerformanceHref({ view: "agent" })).toBe("/ledger?view=agent");
    expect(legacyPerformanceHref({ view: "agent", variant: "abc" })).toBe(
      "/ledger?view=agent&variant=abc",
    );
  });
});
