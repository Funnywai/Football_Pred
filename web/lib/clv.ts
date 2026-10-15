// The CLV card's data: the champion 1x2 version's metrics from /models. CLV is the ML
// layer's proxy (model fair price vs closing price); the ledger's execution price never
// enters it (docs/superpowers/specs/2026-10-15-dashboard-design.md section 4.3). There is
// no CLV time series and no per-bet CLV endpoint in v1. Pure and free of `server-only`.

import type { ModelVersion } from "./types";

export interface ClvMetrics {
  clvMeanEdge: number | null;
  clvFraction: number | null;
  clvN: number | null;
  brier: number | null;
  logloss: number | null;
}

/** The champion 1x2 version, or null when the registry has none. */
export function champion1x2(models: ModelVersion[]): ModelVersion | null {
  return models.find((model) => model.target === "1x2" && model.status === "champion") ?? null;
}

/**
 * The five metrics the card shows. Null when the version reports no metrics at all; a
 * metric the version does not report stays null rather than becoming a fabricated zero.
 */
export function clvMetrics(model: ModelVersion): ClvMetrics | null {
  const metrics = model.metrics;
  const values = [
    metrics.clv_mean_edge,
    metrics.clv_fraction,
    metrics.clv_n,
    metrics.brier,
    metrics.logloss,
  ];
  if (values.every((value) => typeof value !== "number")) return null;
  return {
    clvMeanEdge: numberOrNull(metrics.clv_mean_edge),
    clvFraction: numberOrNull(metrics.clv_fraction),
    clvN: numberOrNull(metrics.clv_n),
    brier: numberOrNull(metrics.brier),
    logloss: numberOrNull(metrics.logloss),
  };
}

function numberOrNull(value: number | undefined): number | null {
  return typeof value === "number" ? value : null;
}

/** The three statements the card must carry in on-screen prose. */
export function clvNotes(metrics: ClvMetrics): string[] {
  const sample =
    metrics.clvN === null
      ? "This version does not report clv_n, so the sample size is unknown."
      : `With clv_n = ${metrics.clvN} so far, it is a weak signal, not proof.`;
  return [
    `CLV is the only evidence available before wins and losses accumulate. ${sample}`,
    "No CLV time series and no per-bet CLV exist in v1 — no endpoint exposes either. The series is deferred until clv_n grows past roughly 100.",
    "The ledger's execution price never enters CLV: it is computed in the ML layer from the model's fair price against the closing price, a different number from the ledger's edge and odds.",
  ];
}
