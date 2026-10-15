import { describe, expect, it } from "vitest";

import { predictionsWindowPhrase } from "@/lib/predictions-window";

// `/predictions` orders by (Match.kickoff_time, target, outcome) ascending and has no
// ordering parameter and no total-count endpoint, so the first page is the EARLIEST
// kickoffs and the newest page cannot be located by offset. The phrase must never claim
// a window that was not fetched.
describe("predictionsWindowPhrase", () => {
  it("names the first page and the missing ordering parameter when the page is full", () => {
    expect(predictionsWindowPhrase(200, 200)).toBe(
      "the first 200 champion and challenger predictions by kickoff time (earliest first); the API exposes no ordering parameter, so newer fixtures may fall outside this window",
    );
  });

  it("states the whole set when the API returned fewer rows than the page size", () => {
    expect(predictionsWindowPhrase(54, 200)).toBe(
      "all 54 champion and challenger predictions by kickoff time (earliest first)",
    );
  });
});
