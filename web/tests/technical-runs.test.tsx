import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IngestionRunsTimeline } from "@/components/technical/IngestionRunsTimeline";
import { runStage, runStatusKind } from "@/lib/runs";
import type { OpsRun } from "@/lib/types";

function run(overrides: Partial<OpsRun>): OpsRun {
  return {
    id: 1,
    job: "sync_odds",
    started_at: "2026-10-15T11:57:00Z",
    finished_at: "2026-10-15T11:58:00Z",
    status: "success",
    records_upserted: 5,
    error: null,
    ...overrides,
  };
}

describe("runStatusKind", () => {
  it("maps the four recorded statuses and falls back to unknown", () => {
    expect(runStatusKind("running")).toBe("running");
    expect(runStatusKind("success")).toBe("success");
    expect(runStatusKind("failed")).toBe("failed");
    expect(runStatusKind("flagged")).toBe("flagged");
    expect(runStatusKind("weird")).toBe("unknown");
  });
});

describe("runStage", () => {
  it("maps tracked run variants to their pipeline stage", () => {
    expect(runStage("sync_odds")).toBe("INGEST");
    expect(runStage("settle_results_hkjc")).toBe("SETTLE");
    expect(runStage("settle_results_fallback")).toBe("SETTLE");
    expect(runStage("ml_predict")).toBe("PREDICT");
    expect(runStage("ledger_update")).toBe("BET");
  });

  it("falls back to the raw job name for unknown jobs", () => {
    expect(runStage("backfill")).toBe("backfill");
  });
});

describe("IngestionRunsTimeline", () => {
  it("highlights a failure with a glyph and the failed label", () => {
    render(
      <IngestionRunsTimeline
        runs={[run({ status: "failed", error: "ValueError: boom" })]}
        total={1}
        limit={200}
      />,
    );
    const label = screen.getByText("failed");
    expect(label.parentElement?.querySelector("svg")).not.toBeNull();
    expect(screen.getByText("ValueError: boom")).toBeInTheDocument();
  });

  it("states the fetched window and never reads as all runs when truncated", () => {
    const runs = Array.from({ length: 200 }, (_, index) => run({ id: index + 1 }));
    render(<IngestionRunsTimeline runs={runs} total={983} limit={200} />);
    expect(
      screen.getByText(/showing the newest 200 of 983 runs \(API max limit 200\)/),
    ).toBeInTheDocument();
  });

  it("says all runs when the window covers the table", () => {
    render(<IngestionRunsTimeline runs={[run({})]} total={1} limit={200} />);
    expect(screen.getByText(/all 1 run \(API max limit 200\)/)).toBeInTheDocument();
  });

  it("renders an explicit unavailable state when /ops/runs failed", () => {
    render(<IngestionRunsTimeline runs={null} total={null} limit={200} />);
    expect(screen.getByText("Runs unavailable")).toBeInTheDocument();
  });

  it("renders an empty state when no runs exist", () => {
    render(<IngestionRunsTimeline runs={[]} total={0} limit={200} />);
    expect(screen.getByText("No ingestion runs recorded yet")).toBeInTheDocument();
  });

  it("reveals runs 10 at a time and searches job, status and error text", () => {
    const runs = Array.from({ length: 30 }, (_, index) =>
      run({
        id: index + 1,
        status: index === 0 ? "failed" : "success",
        error: index === 0 ? "HTTP 503 from HKJC" : null,
      }),
    );
    render(<IngestionRunsTimeline runs={runs} total={30} limit={200} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(10);
    fireEvent.click(screen.getByRole("button", { name: /Expand/ }));
    expect(screen.getAllByRole("listitem")).toHaveLength(20);
    fireEvent.change(screen.getByLabelText("Search runs"), { target: { value: "503" } });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });
});
