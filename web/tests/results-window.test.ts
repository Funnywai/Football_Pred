import { describe, expect, it } from "vitest";

import { resultsWindowPhrase } from "@/lib/results-window";

// `/results` orders by Match.kickoff_time descending, so the first page IS the newest
// page: newer rows cannot fall outside the window, older ones can. There is no
// total-count endpoint, so the phrase never states a fetched count as a total.
describe("resultsWindowPhrase", () => {
  it("names the newest page and that newer rows cannot be outside it", () => {
    expect(resultsWindowPhrase(200, 200)).toBe(
      "the newest 200 results by kickoff time (newest first); newer results cannot fall outside this window, older ones can",
    );
  });

  it("states the whole set when the API returned fewer rows than the page size", () => {
    expect(resultsWindowPhrase(54, 200)).toBe("all 54 results by kickoff time (newest first)");
  });
});
