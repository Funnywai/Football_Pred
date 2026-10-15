import { describe, expect, it } from "vitest";

import { matchesQuery } from "@/lib/row-search";

describe("matchesQuery", () => {
  it("matches a lowercased query against any field, case-insensitively", () => {
    expect(matchesQuery(["Arsenal", "Chelsea", "EPL"], "arsenal")).toBe(true);
    expect(matchesQuery(["Arsenal", "Chelsea", "EPL"], "epl")).toBe(true);
  });

  it("does not match when no field contains the query", () => {
    expect(matchesQuery(["Arsenal", "Chelsea"], "liverpool")).toBe(false);
  });

  it("matches every row on an empty query", () => {
    expect(matchesQuery(["anything"], "")).toBe(true);
  });

  it("treats null and undefined fields as empty strings", () => {
    expect(matchesQuery([null, undefined, "Arsenal"], "arsenal")).toBe(true);
    expect(matchesQuery([null, undefined], "x")).toBe(false);
  });
});
