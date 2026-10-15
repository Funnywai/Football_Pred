import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DbSizeTable } from "@/components/technical/DbSizeTable";
import { oddsGroupRows, tableCountRows } from "@/lib/db-size";
import type { OpsData } from "@/lib/types";

function opsData(): OpsData {
  return {
    table_counts: {
      leagues: 6,
      seasons: 15,
      teams: 320,
      matches: 29164,
      odds_snapshots: 46085,
      results: 12000,
      predictions: 8000,
      match_features: 9000,
      model_versions: 2,
      ledger_bets: 40,
      ingestion_runs: 983,
    },
    odds: {
      total: 46085,
      last_captured_at: "2026-10-15T11:58:00Z",
      by_source_type: [
        {
          source: "hkjc",
          odds_type: "HAD",
          inplay: true,
          count: 30000,
          max_captured_at: "2026-10-15T11:58:00Z",
        },
        {
          source: "football_data",
          odds_type: "HAD",
          inplay: false,
          count: 16085,
          max_captured_at: "2026-10-14T20:00:00Z",
        },
      ],
    },
    match_features: { count: 9000, max_built_at: "2026-10-15T11:00:00Z" },
    results: {
      total: 12000,
      confirmed: 11900,
      payout_confirmed: 11800,
      max_confirmed_at: "2026-10-15T10:00:00Z",
    },
    model_versions: [],
    alembic_revision: "0003_ledger_bets",
    last_arrived: {
      odds_captured_at: "2026-10-15T11:58:00Z",
      features_built_at: "2026-10-15T11:00:00Z",
      results_confirmed_at: "2026-10-15T10:00:00Z",
      model_created_at: null,
      model_promoted_at: null,
    },
  };
}

describe("tableCountRows", () => {
  it("preserves the API's table order", () => {
    const rows = tableCountRows({ leagues: 6, matches: 100, odds_snapshots: 46085 });
    expect(rows.map((row) => row.table)).toEqual(["leagues", "matches", "odds_snapshots"]);
  });
});

describe("oddsGroupRows", () => {
  it("maps each group with its newest capture", () => {
    const rows = oddsGroupRows([
      {
        source: "hkjc",
        odds_type: "HAD",
        inplay: true,
        count: 30000,
        max_captured_at: "2026-10-15T11:58:00Z",
      },
    ]);
    expect(rows).toEqual([
      {
        source: "hkjc",
        oddsType: "HAD",
        inplay: true,
        count: 30000,
        newest: "2026-10-15T11:58:00Z",
      },
    ]);
  });
});

describe("DbSizeTable", () => {
  it("renders right-aligned tabular counts and the row-count note", () => {
    render(<DbSizeTable data={opsData()} />);
    const count = screen.getByText("29,164");
    expect(count).toHaveClass("text-right");
    expect(count).toHaveClass("tnum");
    expect(screen.getByText(/All values are row counts, not rates\./)).toBeInTheDocument();
  });

  it("renders the odds breakdown and the compaction note", () => {
    render(<DbSizeTable data={opsData()} />);
    expect(screen.getByText("hkjc")).toBeInTheDocument();
    expect(screen.getByText("football_data")).toBeInTheDocument();
    expect(screen.getByText(/keeps 3 anchors/)).toBeInTheDocument();
  });

  it("renders an explicit unavailable state when /ops/data failed", () => {
    render(<DbSizeTable data={null} />);
    expect(screen.getByText("DB size unavailable")).toBeInTheDocument();
  });
});
