import { describe, expect, it } from "vitest";

import { champion1x2, clvMetrics, clvNotes, type ClvMetrics } from "@/lib/clv";
import type { ModelVersion } from "@/lib/types";

function model(overrides: Partial<ModelVersion>): ModelVersion {
  return {
    id: 1,
    target: "1x2",
    algorithm: "lightgbm",
    status: "challenger",
    metrics: {},
    artifact_path: "artifacts/ml/model.txt",
    created_at: "2026-10-14T00:00:00Z",
    promoted_at: null,
    ...overrides,
  };
}

const FULL_METRICS: ClvMetrics = {
  clvMeanEdge: 0.012,
  clvFraction: 0.583,
  clvN: 36,
  brier: 0.1923,
  logloss: 0.5512,
};

describe("champion1x2", () => {
  it("returns the champion 1x2 version", () => {
    const models = [
      model({ id: 1, target: "1x2", status: "retired" }),
      model({ id: 2, target: "1x2", status: "champion" }),
      model({ id: 3, target: "handicap", status: "champion" }),
    ];
    expect(champion1x2(models)?.id).toBe(2);
  });

  it("returns null when no 1x2 champion exists", () => {
    expect(champion1x2([model({ id: 3, target: "handicap", status: "champion" })])).toBeNull();
  });
});

describe("clvMetrics", () => {
  it("extracts the five metrics the card shows", () => {
    const metrics = clvMetrics(
      model({
        metrics: {
          brier: 0.1923,
          logloss: 0.5512,
          n: 100,
          clv_fraction: 0.583,
          clv_mean_edge: 0.012,
          clv_n: 36,
        },
      }),
    );
    expect(metrics).toEqual(FULL_METRICS);
  });

  it("returns null when the version reports no metrics at all", () => {
    expect(clvMetrics(model({ metrics: {} }))).toBeNull();
  });

  it("keeps missing CLV fields null instead of inventing a value", () => {
    const metrics = clvMetrics(model({ metrics: { brier: 0.1923, logloss: 0.5512, n: 100 } }));
    expect(metrics).toEqual({
      clvMeanEdge: null,
      clvFraction: null,
      clvN: null,
      brier: 0.1923,
      logloss: 0.5512,
    });
  });
});

describe("clvNotes", () => {
  it("names the sample size and calls CLV a weak signal, not proof", () => {
    expect(clvNotes(FULL_METRICS)[0]).toBe(
      "CLV is the only evidence available before wins and losses accumulate. With clv_n = 36 so far, it is a weak signal, not proof.",
    );
  });

  it("states that no CLV time series and no per-bet CLV exist in v1", () => {
    expect(clvNotes(FULL_METRICS)[1]).toBe(
      "No CLV time series and no per-bet CLV exist in v1 — no endpoint exposes either. The series is deferred until clv_n grows past roughly 100.",
    );
  });

  it("states that the ledger's execution price never enters CLV", () => {
    expect(clvNotes(FULL_METRICS)[2]).toBe(
      "The ledger's execution price never enters CLV: it is computed in the ML layer from the model's fair price against the closing price, a different number from the ledger's edge and odds.",
    );
  });

  it("does not name a sample size the version does not report", () => {
    expect(clvNotes({ ...FULL_METRICS, clvN: null })[0]).toBe(
      "CLV is the only evidence available before wins and losses accumulate. This version does not report clv_n, so the sample size is unknown.",
    );
  });
});
