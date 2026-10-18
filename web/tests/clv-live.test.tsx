import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClvCard } from "@/components/clv/ClvCard";
import type { ClvGate, ClvSummary, ModelVersion } from "@/lib/types";

function summary(overrides: Partial<ClvSummary> = {}): ClvSummary {
  return {
    source: "hkjc",
    n: 240,
    mean_edge: 0.012,
    beat_fraction: 0.583,
    beat_ci95: [0.521, 0.645],
    mean_edge_ci95: [0.002, 0.022],
    by_outcome: {
      H: {
        n: 100,
        mean_edge: 0.01,
        beat_fraction: 0.58,
        beat_ci95: [0.48, 0.68],
        mean_edge_ci95: [0.0, 0.02],
      },
      D: {
        n: 60,
        mean_edge: 0.004,
        beat_fraction: 0.55,
        beat_ci95: [0.42, 0.67],
        mean_edge_ci95: [-0.01, 0.02],
      },
      A: {
        n: 80,
        mean_edge: 0.02,
        beat_fraction: 0.61,
        beat_ci95: [0.5, 0.71],
        mean_edge_ci95: [0.01, 0.03],
      },
    },
    by_model: [],
    value: {
      n: 120,
      mean_edge: 0.021,
      beat_fraction: 0.61,
      beat_ci95: [0.52, 0.7],
      mean_edge_ci95: [0.01, 0.03],
    },
    source_counts: { hkjc: 228, football_data: 12 },
    fallback: 12,
    calibration: {
      model_brier: 0.1923,
      model_logloss: 0.5512,
      market_brier: 0.2011,
      market_logloss: 0.5604,
      n_matches: 240,
    },
    roi_real: 0.032,
    roi_real_ci95: [0.004, 0.06],
    n_settled_bets: 512,
    settled_stakes: 12345,
    gate: {
      ready: false,
      verdict: "collecting",
      days_elapsed: 30,
      days_remaining: 60,
      criteria: [
        { key: "clv_n", passed: true, actual: 240, required: 200 },
        { key: "clv_fraction", passed: true, actual: 0.583, required: 0.52 },
        { key: "roi_real", passed: false, actual: 0.032, required: 0 },
      ],
    },
    ...overrides,
  };
}

function gate(overrides: Partial<ClvGate> = {}): ClvGate {
  return {
    ready: false,
    verdict: "collecting",
    days_elapsed: 30,
    days_remaining: 60,
    criteria: [
      { key: "clv_n", passed: true, actual: 240, required: 200 },
      { key: "clv_fraction", passed: true, actual: 0.583, required: 0.52 },
      { key: "roi_real", passed: false, actual: 0.032, required: 0 },
    ],
    ...overrides,
  };
}

function model(overrides: Partial<ModelVersion>): ModelVersion {
  return {
    id: 7,
    target: "1x2",
    algorithm: "lightgbm",
    status: "champion",
    metrics: {},
    artifact_path: "artifacts/ml/model.txt",
    created_at: "2026-10-14T00:00:00Z",
    promoted_at: "2026-10-14T12:00:00Z",
    ...overrides,
  };
}

describe("ClvCard live summary", () => {
  it("renders the live HKJC CLV metrics, calibration, fallback, ROI and gate", () => {
    render(<ClvCard models={null} summary={summary()} />);

    const header = screen.getByText(/Live CLV \(HKJC close\)/);
    expect(header).toBeInTheDocument();
    expect(header.textContent).toContain("n = 240");
    expect(header.textContent).toContain("fallback = 12");
    expect(screen.getAllByText("240").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("58.3%")).toBeInTheDocument();
    expect(screen.getByText("95% CI 52.1%–64.5%")).toBeInTheDocument();
    expect(screen.getByText("+1.2%")).toBeInTheDocument();
    expect(screen.getByText("95% CI +0.2%–+2.2%")).toBeInTheDocument();
    expect(screen.getByText("0.1923")).toBeInTheDocument();
    expect(screen.getByText("market 0.2011")).toBeInTheDocument();
    expect(screen.getByText("0.5512")).toBeInTheDocument();
    expect(screen.getByText("market 0.5604")).toBeInTheDocument();
    expect(screen.getByText("+3.2%")).toBeInTheDocument();
    expect(screen.getByText(/95% CI \+0\.4%–\+6\.0%/)).toBeInTheDocument();
    expect(screen.getByText("HK$12,345.00")).toBeInTheDocument();
    expect(screen.getByLabelText("gate verdict collecting")).toBeInTheDocument();
  });

  it("renders the value-bet line and the source split", () => {
    render(<ClvCard models={null} summary={summary()} />);

    expect(screen.getByText(/Value bets:/)).toBeInTheDocument();
    expect(screen.getByText("61.0%")).toBeInTheDocument();
    expect(screen.getByText("+2.1%")).toBeInTheDocument();
    expect(screen.getByText(/Sources: HKJC/)).toBeInTheDocument();
    expect(screen.getByText("228")).toBeInTheDocument();
    expect(screen.getAllByText("12").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the gate criteria with key, pass state, actual and required", () => {
    render(<ClvCard models={null} summary={summary()} />);

    const panel = screen.getByRole("region", { name: "Stop/go gate" });
    expect(within(panel).getByText("clv_n")).toBeInTheDocument();
    expect(within(panel).getByText("actual 240")).toBeInTheDocument();
    expect(within(panel).getByText("required 200")).toBeInTheDocument();
    expect(within(panel).getByText("actual 58.3%")).toBeInTheDocument();
    expect(within(panel).getByText("required 52.0%")).toBeInTheDocument();
    expect(within(panel).getByText("actual +3.2%")).toBeInTheDocument();
    expect(within(panel).getByText("required 0.0%")).toBeInTheDocument();
    expect(within(panel).getAllByText("pass")).toHaveLength(2);
    expect(within(panel).getAllByText("fail")).toHaveLength(1);
  });

  it.each([
    ["pass", true],
    ["fail", false],
    ["collecting", false],
  ] as const)("renders the %s gate verdict", (verdict, ready) => {
    render(
      <ClvCard
        models={null}
        summary={summary({ gate: gate({ verdict, ready }) })}
      />,
    );

    expect(screen.getByLabelText(`gate verdict ${verdict}`)).toBeInTheDocument();
    expect(screen.getByText(/ready/)).toBeInTheDocument();
  });

  it("states that CLV is not execution-vs-close and not profit", () => {
    render(<ClvCard models={null} summary={summary()} />);

    expect(
      screen.getByText(/not execution-versus-close, and not profit/),
    ).toBeInTheDocument();
    expect(screen.getByText(/needs 200–500 observations/)).toBeInTheDocument();
  });
});

describe("ClvCard fallback", () => {
  it("falls back to the champion metrics when the live summary is null", () => {
    render(
      <ClvCard
        models={[
          model({
            metrics: {
              clv_mean_edge: 0.012,
              clv_fraction: 0.583,
              clv_n: 36,
              brier: 0.1923,
              logloss: 0.5512,
            },
          }),
        ]}
        summary={null}
      />,
    );

    expect(screen.queryByText(/Live CLV/)).not.toBeInTheDocument();
    expect(screen.getByText("CLV mean edge")).toBeInTheDocument();
    expect(screen.getByText("CLV fraction")).toBeInTheDocument();
    expect(screen.getByText("CLV n")).toBeInTheDocument();
    expect(screen.getByText("Brier")).toBeInTheDocument();
    expect(screen.getByText("Logloss")).toBeInTheDocument();
    expect(screen.getByText("+1.2%")).toBeInTheDocument();
    expect(screen.getByText("58.3%")).toBeInTheDocument();
    expect(screen.getByText("36")).toBeInTheDocument();
  });

  it("keeps the unavailable state when both sources are missing", () => {
    render(<ClvCard models={null} summary={null} />);

    expect(screen.getByText("CLV unavailable")).toBeInTheDocument();
    expect(screen.getByText("the API did not return /models")).toBeInTheDocument();
  });
});
