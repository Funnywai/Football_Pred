import { Database } from "lucide-react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { Note } from "@/components/ui/Note";
import {
  oddsGroupRows,
  tableCountRows,
  type OddsGroupRow,
  type TableCountRow,
} from "@/lib/db-size";
import { formatCount, formatDateTime } from "@/lib/format";
import type { OpsData } from "@/lib/types";

export interface DbSizeTableProps {
  data: OpsData | null;
}

export function DbSizeTable({ data }: DbSizeTableProps) {
  if (data === null) {
    return (
      <EmptyState
        icon={Database}
        title="DB size unavailable"
        detail="the API did not return /ops/data"
      />
    );
  }

  const countColumns: Column<TableCountRow>[] = [
    {
      key: "table",
      header: "Table",
      render: (row) => <span className="font-mono">{row.table}</span>,
    },
    { key: "count", header: "Rows", numeric: true, render: (row) => formatCount(row.count) },
  ];

  const groupColumns: Column<OddsGroupRow>[] = [
    {
      key: "source",
      header: "Source",
      render: (row) => <span className="font-mono">{row.source}</span>,
    },
    {
      key: "type",
      header: "Type",
      render: (row) => <span className="font-mono">{row.oddsType}</span>,
    },
    { key: "inplay", header: "Inplay", render: (row) => (row.inplay ? "true" : "false") },
    { key: "count", header: "Rows", numeric: true, render: (row) => formatCount(row.count) },
    {
      key: "newest",
      header: "Newest capture",
      render: (row) => <span className="tnum">{formatDateTime(row.newest)}</span>,
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      <Note>
        All values are row counts, not rates. After the daily 04:00 UTC compaction each (match
        × odds_type × inplay) group keeps 3 anchors — entry, kickoff − ML_PRIOR_LEAD_HOURS
        (default 48h) prior, closing; the newest capture per group is the closing anchor.
        football_data historical rows are never compacted.
      </Note>
      <div className="flex flex-col gap-3">
        <h3 className="text-h3 text-text-primary">Row counts per table</h3>
        <DataTable
          columns={countColumns}
          rows={tableCountRows(data.table_counts)}
          rowKey={(row) => row.table}
          caption="Row counts per table"
        />
      </div>
      <div className="flex flex-col gap-3">
        <h3 className="text-h3 text-text-primary">Odds snapshots by source and type</h3>
        <Note>
          <span className="tnum text-text-secondary">{formatCount(data.odds.total)}</span>{" "}
          snapshots total · newest capture{" "}
          <span className="tnum text-text-secondary">
            {formatDateTime(data.odds.last_captured_at)}
          </span>
        </Note>
        <DataTable
          columns={groupColumns}
          rows={oddsGroupRows(data.odds.by_source_type)}
          rowKey={(row) => `${row.source}-${row.oddsType}-${String(row.inplay)}`}
          caption="Odds snapshots by source and type"
          empty={
            <p className="text-caption text-text-tertiary">no odds snapshots recorded yet</p>
          }
        />
      </div>
    </div>
  );
}
