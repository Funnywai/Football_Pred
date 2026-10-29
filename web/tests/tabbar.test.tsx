import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ pathname: "/ledger" }));

vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
}));

import { TabBar } from "@/components/nav/TabBar";

describe("TabBar", () => {
  beforeEach(() => {
    state.pathname = "/ledger";
  });

  it("renders Ledger, Agent and Technical as real routes", () => {
    render(<TabBar />);

    expect(screen.getByRole("tablist", { name: "Dashboard sections" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(screen.getByRole("tab", { name: "Ledger" })).toHaveAttribute("href", "/ledger");
    expect(screen.getByRole("tab", { name: "Agent" })).toHaveAttribute("href", "/agent");
    expect(screen.getByRole("tab", { name: "Technical" })).toHaveAttribute(
      "href",
      "/technical",
    );
  });

  it("marks the current route with aria-selected", () => {
    const { rerender } = render(<TabBar />);
    expect(screen.getByRole("tab", { name: "Ledger" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    state.pathname = "/agent";
    rerender(<TabBar />);
    expect(screen.getByRole("tab", { name: "Agent" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Ledger" })).toHaveAttribute(
      "aria-selected",
      "false",
    );

    state.pathname = "/technical";
    rerender(<TabBar />);
    expect(screen.getByRole("tab", { name: "Technical" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("keeps the ledger tab selected on a ledger sub-view", () => {
    state.pathname = "/ledger";
    render(<TabBar />);

    expect(screen.getByRole("tab", { name: "Ledger" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
