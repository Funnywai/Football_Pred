import { formatDateTime, formatNumber } from "@/lib/format";
import type { EndpointResult } from "@/lib/api";
import type { Calibration, Technical } from "@/lib/types";

import { ModelsPanel, StrategiesPanel } from "./calibration-section";

import {
  DataWarning,
  EmptyState,
  HealthPill,
  JsonDetails,
  Panel,
  SectionHeader,
  StatusTag,
} from "./ui";
import { TableFrame } from "./table-frame";

function asText(value: unknown, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    const rendered = JSON.stringify(value);
    return rendered.length > 48 ? `${rendered.slice(0, 48)}…` : rendered;
  } catch {
    return fallback;
  }
}

const COUNT_LABELS: Array<{ key: keyof NonNullable<Technical["counts"]>; label: string }> = [
  { key: "matches", label: "Matches" },
  { key: "predictions", label: "Predictions" },
  { key: "bets", label: "Bets" },
  { key: "settlements", label: "Settlements" },
  { key: "decisions", label: "Decisions" },
  { key: "raw_payloads", label: "Raw payloads" },
  { key: "source_runs", label: "Source runs" },
];

export function TechnicalSection({
  result,
  calibrationResult,
}: {
  result: EndpointResult<Technical>;
  calibrationResult: EndpointResult<Calibration>;
}) {
  const data = result.data;
  const models = Array.isArray(calibrationResult.data?.models)
    ? calibrationResult.data.models
    : [];
  const strategies = Array.isArray(calibrationResult.data?.strategies)
    ? calibrationResult.data.strategies
    : [];
  const counts = data?.counts;
  const sources = Array.isArray(data?.sources) ? data.sources : [];
  const visibleSources = sources.slice(0, 5);
  const totalSources = Math.max(sources.length, data?.counts?.source_runs ?? 0);
  const decisions = Array.isArray(data?.decisions) ? data.decisions : [];
  const visibleDecisions = decisions.slice(0, 5);
  const totalDecisions = Math.max(decisions.length, data?.counts?.decisions ?? 0);
  const odds = data?.latest_odds;

  return (
    <section id="technical" className="section" aria-labelledby="technical-title">
      <SectionHeader
        index="04"
        kicker="Runtime and ingestion"
        title="Technical"
        meta={
          result.error
            ? "technical unavailable"
            : data?.alembic_revision
              ? `rev ${data.alembic_revision}`
              : "revision unknown"
        }
      />

      {result.error ? (
        <DataWarning label="Technical" endpoint="/dashboard/technical" error={result.error} />
      ) : null}

      {!data ? (
        <EmptyState>No technical snapshot was returned.</EmptyState>
      ) : (
        <>
          <div className="tech-grid">
            <Panel title="Runtime" kicker="Service state" meta="read-only probe">
              <dl className="facts">
                <div>
                  <dt>Alembic revision</dt>
                  <dd className="mono">{data.alembic_revision ?? "—"}</dd>
                </div>
                <div>
                  <dt>Database</dt>
                  <dd>
                    <HealthPill label="DB" state={data.database} />
                  </dd>
                </div>
                <div>
                  <dt>Redis</dt>
                  <dd>
                    <HealthPill label="Redis" state={data.redis} />
                  </dd>
                </div>
                <div>
                  <dt>Latest odds snapshot</dt>
                  <dd>
                    {odds ? (
                      <span>
                        <span className="mono">{odds.market ?? "—"}</span>{" "}
                        <span className="text-muted">
                          {formatDateTime(odds.snapshot_at)}
                        </span>
                        {odds.match_id ? (
                          <span className="subline mono">match {odds.match_id}</span>
                        ) : null}
                      </span>
                    ) : (
                      "—"
                    )}
                  </dd>
                </div>
              </dl>
            </Panel>

            <Panel
              title="Table counts"
              kicker="Database"
              meta={`${COUNT_LABELS.length} tables`}
            >
              <dl className="count-grid">
                {COUNT_LABELS.map((entry) => (
                  <div key={entry.key}>
                    <dt>{entry.label}</dt>
                    <dd>{formatNumber(counts?.[entry.key])}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
          </div>

          <ModelsPanel models={models} />
          <StrategiesPanel strategies={strategies} />

          <Panel
            title="Source runs"
            kicker="Ingestion"
            meta={
              totalSources > visibleSources.length
                ? `latest ${visibleSources.length} of ${totalSources}`
                : `${visibleSources.length} rows`
            }
            bodyClassName="panel__body--flush"
          >
            {visibleSources.length === 0 ? (
              <EmptyState>No ingestion source runs recorded.</EmptyState>
            ) : (
              <TableFrame label="Recent ingestion source runs" wide>
                <table className="table--sources">
                  <caption className="sr-only">Recent ingestion source runs</caption>
                  <thead>
                    <tr>
                      <th scope="col">Source</th>
                      <th scope="col">Status</th>
                      <th scope="col">Finished (HKT)</th>
                      <th scope="col" className="num">Errors</th>
                      <th scope="col">Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleSources.map((source, index) => {
                      const extras = Object.fromEntries(
                        Object.entries(source).filter(
                          ([key]) =>
                            ![
                              "source_name",
                              "status",
                              "finished_at",
                              "error_count",
                            ].includes(key),
                        ),
                      );
                      return (
                        <tr key={`${source.source_name ?? "source"}-${index}`}>
                          <td className="mono">{source.source_name ?? "unnamed"}</td>
                          <td>
                            <StatusTag status={source.status} />
                          </td>
                          <td className="cell-time">{formatDateTime(source.finished_at)}</td>
                          <td
                            className={`num ${
                              (source.error_count ?? 0) > 0 ? "text-negative" : ""
                            }`}
                          >
                            {formatNumber(source.error_count)}
                          </td>
                          <td>
                            {Object.keys(extras).length > 0 ? (
                              <JsonDetails label="extra fields" value={extras} />
                            ) : (
                              <span className="text-muted">—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableFrame>
            )}
          </Panel>

          <Panel
            title="Recent decisions"
            kicker="Decision audit"
            meta={
              totalDecisions > visibleDecisions.length
                ? `latest ${visibleDecisions.length} of ${totalDecisions}`
                : `${visibleDecisions.length} rows`
            }
            bodyClassName="panel__body--flush"
          >
            {visibleDecisions.length === 0 ? (
              <EmptyState>No decision rows returned.</EmptyState>
            ) : (
              <TableFrame label="Recent bet decisions" wide>
                <table className="table--decisions">
                  <caption className="sr-only">Most recent bet decisions</caption>
                  <thead>
                    <tr>
                      <th scope="col">Time (HKT)</th>
                      <th scope="col">Match</th>
                      <th scope="col">Status</th>
                      <th scope="col">Model</th>
                      <th scope="col">Strategy</th>
                      <th scope="col">Reason</th>
                      <th scope="col">Raw</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleDecisions.map((decision, index) => {
                      const status = decision.decision_status ?? decision.status;
                      return (
                        <tr key={`${asText(decision.match_id, String(index))}-${index}`}>
                          <td className="cell-time">
                            {formatDateTime(
                              asText(decision.decision_at ?? decision.created_at, "") || null,
                            )}
                          </td>
                          <td className="mono">
                            {asText(decision.match_id ?? decision.slot_key)}
                          </td>
                          <td>
                            {typeof status === "string" ? (
                              <StatusTag status={status} />
                            ) : (
                              <span className="text-muted">—</span>
                            )}
                          </td>
                          <td className="mono">{asText(decision.model_version)}</td>
                          <td className="mono cell-muted">{asText(decision.strategy_version)}</td>
                          <td className="decision__reason">
                            {asText(decision.reason ?? decision.decision_reason)}
                          </td>
                          <td>
                            <JsonDetails label="row" value={decision} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableFrame>
            )}
          </Panel>

        </>
      )}
    </section>
  );
}
