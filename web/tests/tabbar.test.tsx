import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ pathname: "/performance" }));

vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
}));

import { TabBar } from "@/components/nav/TabBar";

describe("TabBar", () => {
  beforeEach(() => {
    state.pathname = "/performance";
  });

  it("renders Performance, Agent and Technical as real routes", () => {
    render(<TabBar />);

    expect(screen.getByRole("tablist", { name: "Dashboard sections" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(screen.getByRole("tab", { name: "Performance" })).toHaveAttribute(
      "href",
      "/performance",
    );
    expect(screen.getByRole("tab", { name: "Agent" })).toHaveAttribute("href", "/agent");
    expect(screen.getByRole("tab", { name: "Technical" })).toHaveAttribute(
      "href",
      "/technical",
    );
  });

  it("marks the current route with aria-selected", () => {
    const { rerender } = render(<TabBar />);
    expect(screen.getByRole("tab", { name: "Performance" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    state.pathname = "/agent";
    rerender(<TabBar />);
    expect(screen.getByRole("tab", { name: "Agent" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Performance" })).toHaveAttribute(
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
});
