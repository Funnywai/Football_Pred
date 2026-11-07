"use client";

import { useMemo, useState } from "react";

import { asNumber, formatKickoff } from "@/lib/format";
import type { LlmResearchRun } from "@/lib/llm-types";

import { LlmRunDialog } from "./llm-run-dialog";
import { TableFrame } from "./table-frame";
import { EmptyState, MatchCell, Panel, StatusTag } from "./ui";

function runStatus(run: LlmResearchRun): string {
  return run.status?.trim() || "unknown";
}

function recommendationLabel(run: LlmResearchRun): string {
  const side = run.recommended_side?.trim();
  if (!side || side.toLowerCase() === "abstain") return "—";
  const stake = asNumber(run.recommended_stake_pct);
  return `${side} · ${stake === null ? "—" : `${(stake * 100).toFixed(2)}%`}`;
}

function AnalystsCell({ run }: { run: LlmResearchRun }) {
  const active = run.active_findings;
  const total = run.total_findings;
  if (typeof active !== "number" || typeof total !== "number") {
    return <span className="cell-muted">—</span>;
  }
  return (
    <span className={active < 3 ? "cell-muted" : undefined}>
      {active}/{total}
    </span>
  );
}

export function LlmRunsTable({ runs }: { runs: LlmResearchRun[] }) {
  const [query, setQuery] = useState("");
  const [activeStatus, setActiveStatus] = useState<string | null>(null);
  const [selection, setSelection] = useState<{
    run: LlmResearchRun;
    token: number;
  } | null>(null);

  const statuses = useMemo(() => {
    const seen = new Set<string>();
    const list: string[] = [];
    for (const run of runs) {
      const status = runStatus(run);
      if (!seen.has(status)) {
        seen.add(status);
        list.push(status);
      }
    }
    return list;
  }, [runs]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return runs.filter((run) => {
      if (activeStatus !== null && runStatus(run) !== activeStatus) return false;
      if (!needle) return true;
      return [run.home_team, run.away_team, run.competition, run.status]
        .filter((value): value is string => typeof value === "string" && Boolean(value))
        .some((value) => value.toLowerCase().includes(needle));
    });
  }, [activeStatus, query, runs]);

  return (
    <Panel
      title="Research runs"
      kicker="Evidence → synthesis → risk"
      meta={`${visible.length} / ${runs.length}`}
      bodyClassName="panel__body--flush"
    >
      <div className="ledger-toolbar llm-runs-toolbar">
        <label className="ledger-search">
          <span className="ledger-search__label">Search runs</span>
          <input
            className="ledger-search__input"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Team, competition or status"
          />
        </label>
        <div className="llm-filter">
          <span className="llm-filter__label">Status</span>
          <div className="llm-filter__chips" role="group" aria-label="Filter by status">
            <button
              type="button"
              className={
                activeStatus === null
                  ? "llm-filter__chip llm-filter__chip--active"
                  : "llm-filter__chip"
              }
              aria-pressed={activeStatus === null}
              onClick={() => setActiveStatus(null)}
            >
              All
            </button>
            {statuses.map((status) => (
              <button
                key={status}
                type="button"
                className={
                  activeStatus === status
                    ? "llm-filter__chip llm-filter__chip--active"
                    : "llm-filter__chip"
                }
                aria-pressed={activeStatus === status}
                onClick={() => setActiveStatus(status)}
              >
                {status.replaceAll("_", " ")}
              </button>
            ))}
          </div>
        </div>
      </div>

      {visible.length === 0 ? (
        <EmptyState>No research runs match this filter.</EmptyState>
      ) : (
        <TableFrame label="LLM research runs" wide>
          <table className="table--llm-runs">
            <caption className="sr-only">
              LLM research runs with Hong Kong kickoff time, recommendation,
              analyst coverage and detail reports
            </caption>
            <thead>
              <tr>
                <th scope="col">Kickoff (HKT)</th>
                <th scope="col">Match</th>
                <th scope="col">Comp</th>
                <th scope="col">Status</th>
                <th scope="col">Recommendation</th>
                <th scope="col" className="num">
                  Analysts
                </th>
                <th scope="col">Detail report</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((run, index) => (
                <tr key={run.run_id ?? `llm-run-${index}`}>
                  <td className="cell-time">
                    <time dateTime={run.kickoff_at ?? undefined}>
                      {formatKickoff(run.kickoff_at)}
                    </time>
                  </td>
                  <td>
                    <MatchCell home={run.home_team} away={run.away_team} />
                  </td>
                  <td className="cell-muted">{run.competition?.trim() || "—"}</td>
                  <td>
                    <StatusTag status={run.status} />
                  </td>
                  <td className="mono">{recommendationLabel(run)}</td>
                  <td className="num">
                    <AnalystsCell run={run} />
                  </td>
                  <td>
                    <button
                      type="button"
                      className="llm-report-action"
                      aria-haspopup="dialog"
                      onClick={() =>
                        setSelection((current) => ({
                          run,
                          token: (current?.token ?? 0) + 1,
                        }))
                      }
                    >
                      View report →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableFrame>
      )}

      <LlmRunDialog
        run={selection?.run ?? null}
        openToken={selection?.token ?? 0}
        onCloseAction={() => setSelection(null)}
      />
    </Panel>
  );
}
