import { describe, expect, it } from "vitest";

import { pipelineStages } from "@/lib/pipeline";
import type { OpsData, OpsJob, OpsRun } from "@/lib/types";

const NOW = new Date("2026-10-15T12:00:00Z");

function job(
  id: string,
  lastRun: OpsJob["last_run"],
  nextRunTime: string | null = "2026-10-15T12:10:00Z",
): OpsJob {
  return { id, trigger: "interval", next_run_time: nextRunTime, pending: false, last_run: lastRun };
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

function data(featuresBuiltAt: string | null): OpsData {
  return {
    table_counts: {},
    odds: { total: 0, last_captured_at: null, by_source_type: [] },
    match_features: { count: 0, max_built_at: featuresBuiltAt },
    results: { total: 0, confirmed: 0, payout_confirmed: 0, max_confirmed_at: null },
    model_versions: [],
    alembic_revision: "0003",
    last_arrived: {
      odds_captured_at: null,
      features_built_at: featuresBuiltAt,
      results_confirmed_at: null,
      model_created_at: null,
      model_promoted_at: null,
    },
  };
}

function stageOf(stages: ReturnType<typeof pipelineStages>, id: string) {
  const found = stages.find((stage) => stage.id === id);
  if (found === undefined) throw new Error(`missing stage ${id}`);
  return found;
}

describe("pipelineStages", () => {
  it("always returns the six stages in order", () => {
    const stages = pipelineStages({ jobs: [], runs: [], data: null, now: NOW });
    expect(stages.map((stage) => stage.id)).toEqual([
      "INGEST",
      "FEATURES",
      "PREDICT",
      "BET",
      "SETTLE",
      "RETRAIN",
    ]);
  });

  it("marks a stage never-tracked when its job has no last_run", () => {
    const stages = pipelineStages({
      jobs: [job("sync_odds", null)],
      runs: [],
      data: null,
      now: NOW,
    });
    expect(stageOf(stages, "INGEST").status).toBe("never-tracked");
  });

  it("marks a recent successful run as success", () => {
    const stages = pipelineStages({
      jobs: [
        job("sync_odds", {
          status: "success",
          finished_at: "2026-10-15T11:58:00Z",
          records_upserted: 5,
          error: null,
        }),
      ],
      runs: [],
      data: null,
      now: NOW,
    });
    expect(stageOf(stages, "INGEST").status).toBe("success");
    expect(stageOf(stages, "INGEST").lastActionAt).toBe("2026-10-15T11:58:00Z");
  });

  it("marks a running last_run as active", () => {
    const stages = pipelineStages({
      jobs: [
        job("ml_predict", {
          status: "running",
          finished_at: null,
          records_upserted: null,
          error: null,
        }),
      ],
      runs: [run({ job: "ml_predict", status: "running", finished_at: null, started_at: "2026-10-15T11:59:00Z" })],
      data: null,
      now: NOW,
    });
    expect(stageOf(stages, "PREDICT").status).toBe("active");
  });

  it("marks a failed last_run as failed and surfaces the error", () => {
    const stages = pipelineStages({
      jobs: [
        job("ledger_update", {
          status: "failed",
          finished_at: "2026-10-15T11:00:00Z",
          records_upserted: null,
          error: "ValueError: boom",
        }),
      ],
      runs: [],
      data: null,
      now: NOW,
    });
    expect(stageOf(stages, "BET").status).toBe("failed");
    expect(stageOf(stages, "BET").detail).toBe("ValueError: boom");
  });

  it("marks a flagged last_run as ageing", () => {
    const stages = pipelineStages({
      jobs: [
        job("settle_results", {
          status: "flagged",
          finished_at: "2026-10-15T11:00:00Z",
          records_upserted: 2,
          error: null,
        }),
      ],
      runs: [],
      data: null,
      now: NOW,
    });
    expect(stageOf(stages, "SETTLE").status).toBe("ageing");
  });

  it("marks a stale successful run as stale", () => {
    const stages = pipelineStages({
      jobs: [
        job("sync_odds", {
          status: "success",
          finished_at: "2026-10-15T06:00:00Z",
          records_upserted: 5,
          error: null,
        }),
      ],
      runs: [],
      data: null,
      now: NOW,
    });
    expect(stageOf(stages, "INGEST").status).toBe("stale");
  });

  it("marks a stuck running run as failed", () => {
    const stages = pipelineStages({
      jobs: [
        job("sync_odds", {
          status: "running",
          finished_at: null,
          records_upserted: null,
          error: null,
        }),
      ],
      runs: [run({ job: "sync_odds", status: "running", finished_at: null, started_at: "2026-10-15T11:00:00Z" })],
      data: null,
      now: NOW,
    });
    expect(stageOf(stages, "INGEST").status).toBe("failed");
    expect(stageOf(stages, "INGEST").detail).toBe("a run is stuck");
  });

  it("derives FEATURES from the features-built timestamp", () => {
    const stages = pipelineStages({
      jobs: [],
      runs: [],
      data: data("2026-10-15T11:00:00Z"),
      now: NOW,
    });
    expect(stageOf(stages, "FEATURES").status).toBe("success");
    expect(stageOf(stages, "FEATURES").lastActionAt).toBe("2026-10-15T11:00:00Z");
  });

  it("marks FEATURES stale when the timestamp is old", () => {
    const stages = pipelineStages({
      jobs: [],
      runs: [],
      data: data("2026-10-15T04:00:00Z"),
      now: NOW,
    });
    expect(stageOf(stages, "FEATURES").status).toBe("stale");
  });

  it("marks FEATURES never-tracked with no timestamp", () => {
    const stages = pipelineStages({ jobs: [], runs: [], data: data(null), now: NOW });
    expect(stageOf(stages, "FEATURES").status).toBe("never-tracked");
  });
});

describe("overdue stages", () => {
  it("marks a stage overdue when next_run_time is past the grace period", () => {
    const stages = pipelineStages({
      jobs: [
        job(
          "sync_odds",
          {
            status: "success",
            finished_at: "2026-10-15T11:58:00Z",
            records_upserted: 5,
            error: null,
          },
          "2026-10-15T10:00:00Z",
        ),
      ],
      runs: [],
      data: null,
      now: NOW,
    });
    expect(stageOf(stages, "INGEST").status).toBe("overdue");
    expect(stageOf(stages, "INGEST").detail).toBe("next run was due 2h ago");
  });

  it("does not mark a stage overdue within the grace period", () => {
    const stages = pipelineStages({
      jobs: [
        job(
          "sync_odds",
          {
            status: "success",
            finished_at: "2026-10-15T11:58:00Z",
            records_upserted: 5,
            error: null,
          },
          "2026-10-15T11:56:00Z",
        ),
      ],
      runs: [],
      data: null,
      now: NOW,
    });
    expect(stageOf(stages, "INGEST").status).toBe("success");
  });

  it("keeps failed precedence over overdue", () => {
    const stages = pipelineStages({
      jobs: [
        job(
          "ledger_update",
          {
            status: "failed",
            finished_at: "2026-10-15T11:00:00Z",
            records_upserted: null,
            error: "ValueError: boom",
          },
          "2026-10-15T10:00:00Z",
        ),
      ],
      runs: [],
      data: null,
      now: NOW,
    });
    expect(stageOf(stages, "BET").status).toBe("failed");
    expect(stageOf(stages, "BET").detail).toBe("ValueError: boom");
  });

  it("keeps flagged precedence over overdue", () => {
    const stages = pipelineStages({
      jobs: [
        job(
          "settle_results",
          {
            status: "flagged",
            finished_at: "2026-10-15T11:00:00Z",
            records_upserted: 2,
            error: null,
          },
          "2026-10-15T10:00:00Z",
        ),
      ],
      runs: [],
      data: null,
      now: NOW,
    });
    expect(stageOf(stages, "SETTLE").status).toBe("ageing");
  });

  it("marks a never-run job overdue when its next run is past", () => {
    const stages = pipelineStages({
      jobs: [job("ml_retrain", null, "2026-10-14T12:00:00Z")],
      runs: [],
      data: null,
      now: NOW,
    });
    expect(stageOf(stages, "RETRAIN").status).toBe("overdue");
  });
});

describe("partial degradation", () => {
  it("marks job-derived stages unavailable when /ops/jobs is missing", () => {
    const stages = pipelineStages({
      jobs: null,
      runs: [],
      data: data("2026-10-15T11:00:00Z"),
      now: NOW,
    });
    for (const id of ["INGEST", "PREDICT", "BET", "SETTLE", "RETRAIN"]) {
      expect(stageOf(stages, id).status).toBe("unavailable");
    }
    expect(stageOf(stages, "FEATURES").status).toBe("success");
  });

  it("marks FEATURES unavailable when /ops/data is missing", () => {
    const stages = pipelineStages({ jobs: [], runs: [], data: null, now: NOW });
    expect(stageOf(stages, "FEATURES").status).toBe("unavailable");
  });
});
