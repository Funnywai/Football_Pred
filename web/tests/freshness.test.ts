import { describe, expect, it } from "vitest";

import { heartbeatFrom, statusForAge, FRESHNESS_THRESHOLDS } from "@/lib/freshness";
import { thinkingFrom } from "@/lib/header-model";
import type { OpsJob, OpsRun } from "@/lib/types";

const NOW = new Date("2026-10-15T12:00:00Z");

function job(id: string): OpsJob {
  return { id, trigger: "interval", next_run_time: "2026-10-15T12:10:00Z", pending: false, last_run: null };
}

function run(overrides: Partial<OpsRun>): OpsRun {
  return {
    id: 1,
    job: "sync_odds",
    started_at: "2026-10-15T11:57:00Z",
    finished_at: "2026-10-15T11:58:00Z",
    status: "success",
    records_upserted: 1,
    error: null,
    ...overrides,
  };
}

describe("statusForAge", () => {
  it("is healthy inside the degraded window", () => {
    expect(statusForAge("2026-10-15T11:55:00Z", FRESHNESS_THRESHOLDS.odds, NOW)).toBe("healthy");
  });

  it("is degraded past the degraded threshold", () => {
    expect(statusForAge("2026-10-15T11:20:00Z", FRESHNESS_THRESHOLDS.odds, NOW)).toBe("degraded");
  });

  it("is stale past the stale threshold", () => {
    expect(statusForAge("2026-10-15T08:00:00Z", FRESHNESS_THRESHOLDS.odds, NOW)).toBe("stale");
  });

  it("treats a missing timestamp as stale", () => {
    expect(statusForAge(null, FRESHNESS_THRESHOLDS.odds, NOW)).toBe("stale");
  });
});

describe("heartbeatFrom", () => {
  it("is stale when there are no scheduled jobs", () => {
    expect(heartbeatFrom({ jobs: [], runs: [], now: NOW }).status).toBe("stale");
  });

  it("is healthy with a recent successful run", () => {
    expect(heartbeatFrom({ jobs: [job("sync_odds")], runs: [run({})], now: NOW }).status).toBe(
      "healthy",
    );
  });

  it("is degraded after a recent failure", () => {
    const failed = run({ status: "failed", error: "boom" });
    expect(heartbeatFrom({ jobs: [job("sync_odds")], runs: [failed], now: NOW }).status).toBe(
      "degraded",
    );
  });

  it("is degraded when a run is stuck in running", () => {
    const stuck = run({ status: "running", finished_at: null, started_at: "2026-10-15T11:00:00Z" });
    expect(heartbeatFrom({ jobs: [job("sync_odds")], runs: [stuck], now: NOW }).status).toBe(
      "degraded",
    );
  });
});

describe("thinkingFrom", () => {
  it("is idle with no running run", () => {
    expect(thinkingFrom([run({})])).toEqual({ active: false, stage: null, label: "idle" });
  });

  it("maps a running job to its pipeline stage", () => {
    const running = run({ job: "ml_predict", status: "running", finished_at: null });
    expect(thinkingFrom([running])).toEqual({
      active: true,
      stage: "PREDICT",
      label: "thinking · PREDICT",
    });
  });
});
