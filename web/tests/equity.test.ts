import { describe, expect, it } from "vitest";

import { equityModel } from "@/lib/equity";
import type { EquityPoint } from "@/lib/types";

describe("equityModel", () => {
  it("reports an empty model for no points", () => {
    const model = equityModel([]);
    expect(model.first).toBeNull();
    expect(model.last).toBeNull();
    expect(model.summary).toBe("no equity points yet");
  });

  it("treats initial + final only as no settlements", () => {
    const points: EquityPoint[] = [
      { t: null, bankroll: 1000 },
      { t: "2026-10-15T12:00:00Z", bankroll: 1000 },
    ];
    const model = equityModel(points);
    expect(model.hasSettlements).toBe(false);
    expect(model.change).toBe(0);
  });

  it("computes change and percentage across settlements", () => {
    const points: EquityPoint[] = [
      { t: null, bankroll: 1000 },
      { t: "2026-10-02T00:00:00Z", bankroll: 1010 },
      { t: "2026-10-03T00:00:00Z", bankroll: 1005 },
      { t: "2026-10-15T12:00:00Z", bankroll: 1005 },
    ];
    const model = equityModel(points);
    expect(model.hasSettlements).toBe(true);
    expect(model.first).toBe(1000);
    expect(model.last).toBe(1005);
    expect(model.change).toBe(5);
    expect(model.changePct).toBeCloseTo(0.005);
    expect(model.summary).toContain("HK$1,000.00");
    expect(model.summary).toContain("+HK$5.00");
  });

  it("handles a zero initial bankroll without dividing by zero", () => {
    const model = equityModel([
      { t: null, bankroll: 0 },
      { t: "2026-10-02T00:00:00Z", bankroll: 10 },
      { t: "2026-10-15T12:00:00Z", bankroll: 10 },
    ]);
    expect(model.changePct).toBeNull();
  });
});
