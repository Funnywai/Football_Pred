import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ pathname: "/agent" }));

vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
}));

import { TabBar } from "@/components/nav/TabBar";

describe("TabBar", () => {
  beforeEach(() => {
    state.pathname = "/agent";
  });

  it("renders Agent and Technical as real routes", () => {
    render(<TabBar />);

    expect(screen.getByRole("tablist", { name: "Dashboard sections" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(screen.getByRole("tab", { name: "Agent" })).toHaveAttribute("href", "/agent");
    expect(screen.getByRole("tab", { name: "Technical" })).toHaveAttribute(
      "href",
      "/technical",
    );
  });

  it("marks the current route with aria-selected", () => {
    const { rerender } = render(<TabBar />);
    expect(screen.getByRole("tab", { name: "Agent" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    state.pathname = "/technical";
    rerender(<TabBar />);
    expect(screen.getByRole("tab", { name: "Technical" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Agent" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("keeps the agent tab selected on an agent variant URL", () => {
    state.pathname = "/agent";
    render(<TabBar />);

    expect(screen.getByRole("tab", { name: "Agent" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
