import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PerformancePage from "@/app/(dashboard)/performance/page";
import TechnicalPage from "@/app/(dashboard)/technical/page";
import { PERFORMANCE_SECTIONS, TECHNICAL_SECTIONS } from "@/lib/sections";

describe("route smoke — /performance", () => {
  it("renders a shell for every performance section with a pending state", () => {
    render(<PerformancePage />);

    for (const section of PERFORMANCE_SECTIONS) {
      expect(screen.getByRole("heading", { name: section.title })).toBeInTheDocument();
    }
    expect(screen.getAllByText("pending — next increment")).toHaveLength(
      PERFORMANCE_SECTIONS.length,
    );
  });
});

describe("route smoke — /technical", () => {
  it("renders a shell for every technical section with a pending state", () => {
    render(<TechnicalPage />);

    for (const section of TECHNICAL_SECTIONS) {
      expect(screen.getByRole("heading", { name: section.title })).toBeInTheDocument();
    }
    expect(screen.getAllByText("pending — next increment")).toHaveLength(
      TECHNICAL_SECTIONS.length,
    );
  });
});
