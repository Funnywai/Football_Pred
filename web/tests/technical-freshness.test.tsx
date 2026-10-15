import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FreshnessPanel } from "@/components/technical/FreshnessPanel";
import { FRESHNESS_THRESHOLDS, HOUR, MINUTE, freshnessRows } from "@/lib/freshness";
import type { OpsData, OpsRun } from "@/lib/types";

const NOW = new Date("2026-10-15T12:00:00Z");

function data(overrides: Partial<OpsData["last_arrived"]>): OpsData {
  return {
    table_counts: {},
    odds: { total: 0, last_captured_at: null, by_source_type: [] },
    match_features: { count: 0, max_built_at: null },
    results: { total: 0, confirmed: 0, payout_confirmed: 0, max_confirmed_at: null },
    model_versions: [],
    alembic_revision: "0003_ledger_bets",
    last_arrived: {
      odds_captured_at: null,
      features_built_at: null,
      results_confirmed_at: null,
      model_created_at: null,
      model_promoted_at: null,
      ...overrides,
    },
  };
}

function run(overrides: Partial<OpsRun>): OpsRun {
  return {
    id: 1,
    job: "ml_predict",
    started_at: "2026-10-15T11:30:00Z",
    finished_at: "2026-10-15T11:31:00Z",
    status: "success",
    records_upserted: 10,
    error: null,
    ...overrides,
  };
}

function rowOf(rows: ReturnType<typeof freshnessRows>, id: string) {
  const found = rows.find((row) => row.id === id);
  if (found === undefined) throw new Error(`missing freshness row ${id}`);
  return found;
}

describe("freshnessRows", () => {
  it("is healthy one millisecond before the degraded threshold", () => {
    const iso = new Date(NOW.getTime() - (30 * MINUTE - 1)).toISOString();
    const rows = freshnessRows(data({ odds_captured_at: iso }), [], NOW);
    expect(rowOf(rows, "odds").state).toBe("healthy");
  });

  it("is degraded exactly at the degraded threshold", () => {
    const iso = new Date(NOW.getTime() - 30 * MINUTE).toISOString();
    const rows = freshnessRows(data({ odds_captured_at: iso }), [], NOW);
    expect(rowOf(rows, "odds").state).toBe("degraded");
  });

  it("is stale exactly at the stale threshold", () => {
    const iso = new Date(NOW.getTime() - 3 * HOUR).toISOString();
    const rows = freshnessRows(data({ odds_captured_at: iso }), [], NOW);
    expect(rowOf(rows, "odds").state).toBe("stale");
  });

  it("marks a null timestamp as never tracked, not stale", () => {
    const rows = freshnessRows(data({ results_confirmed_at: null }), [], NOW);
    expect(rowOf(rows, "results").state).toBe("never-tracked");
  });

  it("marks the predictions row unavailable when /ops/runs is missing", () => {
    const rows = freshnessRows(data({}), null, NOW);
    expect(rowOf(rows, "predictions").state).toBe("unavailable");
  });

  it("derives prediction freshness from the newest ml_predict run", () => {
    const runs: OpsRun[] = [
      run({ id: 1, finished_at: "2026-10-15T11:30:00Z" }),
      run({ id: 2, finished_at: "2026-10-15T11:45:00Z" }),
      run({ id: 3, job: "sync_odds", finished_at: "2026-10-15T11:59:00Z" }),
    ];
    const rows = freshnessRows(data({}), runs, NOW);
    expect(rowOf(rows, "predictions").iso).toBe("2026-10-15T11:45:00Z");
    expect(rowOf(rows, "predictions").state).toBe("healthy");
  });

  it("exposes the thresholds it used", () => {
    const rows = freshnessRows(data({}), [], NOW);
    expect(rowOf(rows, "odds").thresholds).toEqual(FRESHNESS_THRESHOLDS.odds);
  });
});

describe("FreshnessPanel", () => {
  it("shows the labelled state, the threshold and the raw timestamp", () => {
    render(
      <FreshnessPanel
        data={data({ odds_captured_at: "2026-10-15T11:58:00Z" })}
        runs={[]}
        now={NOW}
      />,
    );
    expect(screen.getByText("fresh")).toBeInTheDocument();
    expect(screen.getByText("degraded > 30m · stale > 3h")).toBeInTheDocument();
    expect(screen.getByText("15/10/2026, 11:58")).toBeInTheDocument();
  });

  it("renders an explicit unavailable state when /ops/data failed", () => {
    render(<FreshnessPanel data={null} runs={null} now={NOW} />);
    expect(screen.getByText("Freshness unavailable")).toBeInTheDocument();
  });
});
