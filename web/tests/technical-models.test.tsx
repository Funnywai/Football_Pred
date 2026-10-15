import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ModelTimeline } from "@/components/technical/ModelTimeline";
import { formatMetric, metricCells, modelTimelineRows } from "@/lib/model-metrics";
import type { ModelVersion, OpsModelVersion } from "@/lib/types";

const ONE_X_TWO = {
  brier: 0.19,
  logloss: 0.61,
  n: 1200,
  clv_fraction: 0.55,
  clv_mean_edge: 0.012,
  clv_n: 40,
};

const HANDICAP = { brier: 0.21, logloss: 0.65, n: 800 };

function model(overrides: Partial<ModelVersion> & { id: number }): ModelVersion {
  return {
    target: "1x2",
    algorithm: "lightgbm",
    status: "challenger",
    metrics: {},
    artifact_path: "artifacts/ml/model.joblib",
    created_at: "2026-10-01T00:00:00Z",
    promoted_at: null,
    ...overrides,
  };
}

function opsVersion(overrides: Partial<OpsModelVersion> & { id: number }): OpsModelVersion {
  return {
    target: "1x2",
    algorithm: "lightgbm",
    status: "challenger",
    params: {},
    metrics: {},
    artifact_path: "artifacts/ml/model.joblib",
    created_at: "2026-10-01T00:00:00Z",
    promoted_at: null,
    ...overrides,
  };
}

describe("metricCells", () => {
  it("renders all six keys for a 1x2 model", () => {
    const cells = metricCells(ONE_X_TWO);
    expect(cells.map((cell) => cell.key)).toEqual([
      "brier",
      "logloss",
      "n",
      "clv_fraction",
      "clv_mean_edge",
      "clv_n",
    ]);
    expect(cells.every((cell) => cell.value !== null)).toBe(true);
  });

  it("marks the CLV keys not tracked for a handicap model instead of zero", () => {
    const cells = metricCells(HANDICAP);
    expect(cells.map((cell) => cell.key)).toEqual([
      "brier",
      "logloss",
      "n",
      "clv_fraction",
      "clv_mean_edge",
      "clv_n",
    ]);
    const clv = cells.filter((cell) => cell.key.startsWith("clv_"));
    expect(clv.every((cell) => cell.value === null)).toBe(true);
  });

  it("treats a null metric value as not tracked", () => {
    const cells = metricCells({ brier: 0.19, clv_fraction: null });
    expect(cells.find((cell) => cell.key === "clv_fraction")?.value).toBeNull();
  });

  it("keeps unknown extra keys after the known ones", () => {
    const cells = metricCells({ brier: 0.19, custom: 1 });
    expect(cells.map((cell) => cell.key)).toEqual([
      "brier",
      "logloss",
      "n",
      "clv_fraction",
      "clv_mean_edge",
      "clv_n",
      "custom",
    ]);
  });
});

describe("formatMetric", () => {
  it("formats counts, fractions and calibration values", () => {
    expect(formatMetric("n", 1200)).toBe("1,200");
    expect(formatMetric("clv_n", 40)).toBe("40");
    expect(formatMetric("clv_fraction", 0.55)).toBe("55.0%");
    expect(formatMetric("clv_mean_edge", 0.012)).toBe("+1.2%");
    expect(formatMetric("brier", 0.19)).toBe("0.1900");
  });
});

describe("modelTimelineRows", () => {
  it("orders by created_at newest first and joins params by id", () => {
    const older = model({ id: 1, created_at: "2026-10-01T00:00:00Z" });
    const newer = model({ id: 2, created_at: "2026-10-10T00:00:00Z" });
    const rows = modelTimelineRows(
      [older, newer],
      [opsVersion({ id: 2, params: { n_estimators: 400 } })],
    );
    expect(rows.map((row) => row.model.id)).toEqual([2, 1]);
    expect(rows[0]?.params).toEqual({ n_estimators: 400 });
    expect(rows[1]?.params).toBeNull();
  });
});

describe("ModelTimeline", () => {
  it("renders champion and challenger with honest metrics", () => {
    render(
      <ModelTimeline
        models={[
          model({
            id: 1,
            target: "1x2",
            status: "champion",
            metrics: ONE_X_TWO,
            created_at: "2026-10-10T00:00:00Z",
            promoted_at: "2026-10-11T00:00:00Z",
          }),
          model({
            id: 2,
            target: "handicap",
            status: "challenger",
            metrics: HANDICAP,
            created_at: "2026-10-01T00:00:00Z",
          }),
        ]}
        opsVersions={[opsVersion({ id: 1, params: { n_estimators: 400 } })]}
      />,
    );
    expect(screen.getByText("champion")).toBeInTheDocument();
    expect(screen.getByText("challenger")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByText("0.0000")).not.toBeInTheDocument();
    expect(screen.getByText(/n_estimators/)).toBeInTheDocument();
  });

  it("renders an explicit unavailable state when /models failed", () => {
    render(<ModelTimeline models={null} opsVersions={null} />);
    expect(screen.getByText("Model versions unavailable")).toBeInTheDocument();
  });
});
