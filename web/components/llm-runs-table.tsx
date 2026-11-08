"use client";

import { useMemo, useState } from "react";

import { asNumber, formatKickoff, hktDateKey } from "@/lib/format";
import type { LlmResearchRun } from "@/lib/llm-types";
import { buildLlmRunsTsv } from "@/lib/llm-runs-export";

import { CopyTableButton } from "./copy-table-button";
import { DayNavigator } from "./day-navigator";
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
  const [dayIndex, setDayIndex] = useState(0);
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

  const dayKeys = useMemo(
    () =>
      Array.from(
        new Set(
          runs
            .map((run) => hktDateKey(run.kickoff_at))
            .filter((key): key is string => Boolean(key)),
        ),
      ).sort((left, right) => right.localeCompare(left)),
    [runs],
  );
  const selectedDay = dayKeys[dayIndex] ?? null;

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return runs.filter((run) => {
      if (selectedDay !== null && hktDateKey(run.kickoff_at) !== selectedDay) {
        return false;
      }
      if (activeStatus !== null && runStatus(run) !== activeStatus) return false;
      if (!needle) return true;
      return [run.home_team, run.away_team, run.competition, run.status]
        .filter((value): value is string => typeof value === "string" && Boolean(value))
        .some((value) => value.toLowerCase().includes(needle));
    });
  }, [activeStatus, query, runs, selectedDay]);

  const copyText = useMemo(() => buildLlmRunsTsv(visible), [visible]);

  return (
    <Panel
      title="Research runs"
      kicker="Evidence → synthesis → risk"
      meta={
        <div className="panel__meta-group">
          <span>
            {visible.length} / {runs.length}
          </span>
          {visible.length > 0 ? (
            <CopyTableButton
              text={copyText}
              label="Copy"
              title="Copy the filtered research runs as tab-separated values"
              copiedMessage="Filtered research runs copied to clipboard"
            />
          ) : null}
        </div>
      }
      bodyClassName="panel__body--flush"
    >
      <div className="ledger-toolbar llm-runs-toolbar">
        <label className="ledger-search">
          <span className="ledger-search__label">Search runs</span>
          <input
            className="ledger-search__input"
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setDayIndex(0);
            }}
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
              onClick={() => {
                setActiveStatus(null);
                setDayIndex(0);
              }}
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
                onClick={() => {
                  setActiveStatus(status);
                  setDayIndex(0);
                }}
              >
                {status.replaceAll("_", " ")}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="prediction-day-nav">
        <DayNavigator
          dayKey={selectedDay}
          dayIndex={dayIndex}
          dayCount={dayKeys.length}
          onFirst={() => setDayIndex(0)}
          onPrevious={() =>
            setDayIndex((current) => Math.min(dayKeys.length - 1, current + 1))
          }
          onNext={() => setDayIndex((current) => Math.max(0, current - 1))}
        />
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
