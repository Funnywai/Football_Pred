import { describe, expect, it } from "vitest";

import { betStatusKind, betStatusLabel } from "@/lib/bets";

describe("betStatusKind", () => {
  it.each([
    ["pending", "pending"],
    ["won", "won"],
    ["lost", "lost"],
    ["push", "push"],
    ["half_won", "half-won"],
    ["half_lost", "half-lost"],
  ] as const)("maps %s to %s", (status, kind) => {
    expect(betStatusKind(status)).toBe(kind);
  });

  it("maps an unknown status to unknown", () => {
    expect(betStatusKind("void")).toBe("unknown");
  });
});

describe("betStatusLabel", () => {
  it("humanises the half statuses", () => {
    expect(betStatusLabel("half-won")).toBe("half won");
    expect(betStatusLabel("half-lost")).toBe("half lost");
  });

  it("passes through the simple statuses", () => {
    expect(betStatusLabel("won")).toBe("won");
    expect(betStatusLabel("push")).toBe("push");
  });
});
