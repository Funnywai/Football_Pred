import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SchedulerTable } from "@/components/technical/SchedulerTable";
import { pipelineStages } from "@/lib/pipeline";
import { schedulerRows } from "@/lib/scheduler";
import type { OpsJob, OpsRun } from "@/lib/types";

const NOW = new Date("2026-10-15T12:00:00Z");

function job(overrides: Partial<OpsJob> & { id: string }): OpsJob {
  return {
    trigger: "interval[0:10:00]",
    next_run_time: "2026-10-15T12:10:00Z",
    pending: false,
    last_run: null,
    ...overrides,
  };
}

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

function first<T>(items: T[]): T {
  const item = items[0];
  if (item === undefined) throw new Error("expected at least one item");
  return item;
}

describe("schedulerRows", () => {
  it("marks a job overdue when next_run_time is past the grace period", () => {
    const rows = schedulerRows(
      [job({ id: "sync_odds", next_run_time: "2026-10-15T10:00:00Z" })],
      [],
      NOW,
    );
    expect(first(rows).status).toBe("overdue");
    expect(first(rows).detail).toBe("next run was due 2h ago");
  });

  it("agrees with the pipeline derivation for the same job", () => {
    const jobs = [job({ id: "sync_odds", next_run_time: "2026-10-15T10:00:00Z" })];
    const stages = pipelineStages({ jobs, runs: [], data: null, now: NOW });
    const ingest = stages.find((stage) => stage.id === "INGEST");
    expect(first(schedulerRows(jobs, [], NOW)).status).toBe(ingest?.status);
  });

  it("surfaces the error of a failed last run", () => {
    const rows = schedulerRows(
      [
        job({
          id: "ledger_update",
          last_run: {
            status: "failed",
            finished_at: "2026-10-15T11:00:00Z",
            records_upserted: null,
            error: "ValueError: boom",
          },
        }),
      ],
      [],
      NOW,
    );
    expect(first(rows).status).toBe("failed");
    expect(first(rows).detail).toBe("ValueError: boom");
  });

  it("marks a recent success as success and a stale one as stale", () => {
    const fresh = schedulerRows(
      [
        job({
          id: "sync_odds",
          last_run: {
            status: "success",
            finished_at: "2026-10-15T11:58:00Z",
            records_upserted: 5,
            error: null,
          },
        }),
      ],
      [],
      NOW,
    );
    expect(first(fresh).status).toBe("success");

    const stale = schedulerRows(
      [
        job({
          id: "sync_odds",
          last_run: {
            status: "success",
            finished_at: "2026-10-15T06:00:00Z",
            records_upserted: 5,
            error: null,
          },
        }),
      ],
      [],
      NOW,
    );
    expect(first(stale).status).toBe("stale");
  });

  it("marks a job with no run record as never tracked", () => {
    const rows = schedulerRows(
      [job({ id: "prune_odds", next_run_time: "2026-10-16T04:00:00Z" })],
      [],
      NOW,
    );
    expect(first(rows).status).toBe("never-tracked");
  });

  it("marks a stuck running run as failed", () => {
    const jobs = [
      job({
        id: "sync_odds",
        last_run: { status: "running", finished_at: null, records_upserted: null, error: null },
      }),
    ];
    const runs = [
      run({ job: "sync_odds", status: "running", finished_at: null, started_at: "2026-10-15T11:00:00Z" }),
    ];
    expect(first(schedulerRows(jobs, runs, NOW)).status).toBe("failed");
  });
});

describe("SchedulerTable", () => {
  it("renders every job with its trigger, status and error", () => {
    render(
      <SchedulerTable
        jobs={[
          job({
            id: "sync_odds",
            last_run: {
              status: "success",
              finished_at: "2026-10-15T11:58:00Z",
              records_upserted: 5,
              error: null,
            },
          }),
          job({
            id: "ledger_update",
            trigger: "interval[0:60:00]",
            last_run: {
              status: "failed",
              finished_at: "2026-10-15T11:00:00Z",
              records_upserted: null,
              error: "ValueError: boom",
            },
          }),
        ]}
        runs={[]}
        now={NOW}
      />,
    );
    expect(screen.getByText("sync_odds")).toBeInTheDocument();
    expect(screen.getByText("interval[0:10:00]")).toBeInTheDocument();
    expect(screen.getAllByText("ValueError: boom").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("success")).toBeInTheDocument();
  });

  it("renders an explicit unavailable state when /ops/jobs failed", () => {
    render(<SchedulerTable jobs={null} runs={null} now={NOW} />);
    expect(screen.getByText("Scheduler unavailable")).toBeInTheDocument();
  });

  it("says the scheduler is disabled when there are no jobs", () => {
    render(<SchedulerTable jobs={[]} runs={[]} now={NOW} />);
    expect(screen.getByText("No scheduled jobs")).toBeInTheDocument();
  });
});
