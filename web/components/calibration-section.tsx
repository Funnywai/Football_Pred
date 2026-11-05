import {
  asNumber,
  formatDateTime,
  formatFixed,
  formatNumber,
  formatSignedPercent,
} from "@/lib/format";
import { extractCalibrationBins } from "@/lib/calibration";
import type { EndpointResult } from "@/lib/api";
import type {
  Calibration,
  CalibrationMetric,
  ModelRecord,
  StrategyRecord,
  WeightSnapshot,
} from "@/lib/types";

import { CalibrationBinChart } from "./calibration-chart";
import {
  DataWarning,
  EmptyState,
  JsonDetails,
  Panel,
  SectionHeader,
  StatusTag,
} from "./ui";
import { TableFrame } from "./table-frame";

function summarize(record: Record<string, unknown> | null | undefined, limit = 3): string[] {
  if (!record) return [];
  return Object.entries(record)
    .slice(0, limit)
    .map(([key, value]) => {
      const printed =
        typeof value === "string" || typeof value === "number" || typeof value === "boolean"
          ? String(value)
          : Array.isArray(value)
            ? `[${value.length}]`
            : "object";
      return `${key}=${printed.length > 18 ? `${printed.slice(0, 18)}…` : printed}`;
    });
}

function EntityCard({
  version,
  status,
  rows,
  chips,
  raw,
}: {
  version: string | null | undefined;
  status: string | null | undefined;
  rows: Array<{ label: string; value: string }>;
  chips: string[];
  raw: Array<{ label: string; value: unknown }>;
}) {
  return (
    <article className="entity-card">
      <header className="entity-card__head">
        <span className="entity-card__version mono">{version ?? "unversioned"}</span>
        <StatusTag status={status} />
      </header>
      <dl className="entity-card__facts">
        {rows.map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
      {chips.length > 0 ? (
        <ul className="chips" aria-label="Selected parameters">
          {chips.map((chip) => (
            <li key={chip} className="chip">
              {chip}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="entity-card__raw">
        {raw.map((item) => (
          <JsonDetails key={item.label} label={item.label} value={item.value} />
        ))}
      </div>
    </article>
  );
}

export function ModelsPanel({ models }: { models: ModelRecord[] }) {
  return (
    <Panel
      title="Models"
      kicker="Registry"
      meta={`${models.length} ${models.length === 1 ? "version" : "versions"}`}
    >
      {models.length === 0 ? (
        <EmptyState>No model versions registered.</EmptyState>
      ) : (
        <div className="entity-grid">
          {models.map((model, index) => (
            <EntityCard
              key={model.version ?? model.created_at ?? `model-${index}`}
              version={model.version}
              status={model.status}
              rows={[
                { label: "family", value: model.family ?? "—" },
                { label: "created", value: formatDateTime(model.created_at) },
              ]}
              chips={summarize(model.params)}
              raw={[
                { label: "params", value: model.params },
                { label: "validation metrics", value: model.validation_metrics },
              ]}
            />
          ))}
        </div>
      )}
    </Panel>
  );
}

export function StrategiesPanel({ strategies }: { strategies: StrategyRecord[] }) {
  return (
    <Panel
      title="Strategies"
      kicker="Policy registry"
      meta={`${strategies.length} ${strategies.length === 1 ? "version" : "versions"}`}
    >
      {strategies.length === 0 ? (
        <EmptyState>No strategy versions registered.</EmptyState>
      ) : (
        <div className="entity-grid">
          {strategies.map((strategy, index) => (
            <EntityCard
              key={strategy.version ?? strategy.created_at ?? `strategy-${index}`}
              version={strategy.version}
              status={strategy.status}
              rows={[
                { label: "model", value: strategy.model_version ?? "—" },
                { label: "created", value: formatDateTime(strategy.created_at) },
              ]}
              chips={summarize(strategy.policy_params)}
              raw={[{ label: "policy params", value: strategy.policy_params }]}
            />
          ))}
        </div>
      )}
    </Panel>
  );
}

function WeightsPanel({ snapshots }: { snapshots: WeightSnapshot[] }) {
  return (
    <Panel
      title="Weight snapshots"
      kicker="Strategy evaluation"
      meta={`${snapshots.length} snapshots`}
      bodyClassName="panel__body--flush"
    >
      {snapshots.length === 0 ? (
        <EmptyState>No strategy weight snapshots recorded.</EmptyState>
      ) : (
        <TableFrame label="Strategy weight snapshots" wide>
          <table className="table--weights">
            <caption className="sr-only">Strategy weight snapshots</caption>
            <thead>
              <tr>
                <th scope="col">Strategy</th>
                <th scope="col">Reason</th>
                <th scope="col">Evaluation period</th>
                <th scope="col">Created (HKT)</th>
                <th scope="col">Weights</th>
              </tr>
            </thead>
            <tbody>
              {snapshots.map((snapshot, index) => (
                <tr key={`${snapshot.strategy_version ?? "strategy"}-${index}`}>
                  <td className="mono">{snapshot.strategy_version ?? "—"}</td>
                  <td>{snapshot.reason ?? "—"}</td>
                  <td className="cell-muted">{snapshot.evaluation_period ?? "—"}</td>
                  <td className="cell-time">{formatDateTime(snapshot.created_at)}</td>
                  <td>
                    <div className="chips">
                      {summarize(snapshot.weights, 4).map((chip) => (
                        <span className="chip" key={chip}>
                          {chip}
                        </span>
                      ))}
                      {!snapshot.weights ? <span className="text-muted">—</span> : null}
                    </div>
                    <JsonDetails label="all weights" value={snapshot.weights} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableFrame>
      )}
    </Panel>
  );
}

function MetricsPanel({ metrics }: { metrics: CalibrationMetric[] }) {
  return (
    <Panel
      title="Calibration metrics"
      kicker="Out-of-sample review"
      meta={`${metrics.length} rows`}
      bodyClassName="panel__body--flush"
    >
      {metrics.length === 0 ? (
        <EmptyState>No calibration metrics have been computed.</EmptyState>
      ) : (
        <TableFrame label="Calibration metrics" wide>
          <table className="table--calibration">
            <caption className="sr-only">Calibration metrics by model, strategy and slice</caption>
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Strategy</th>
                <th scope="col">Slice</th>
                <th scope="col" className="num">N</th>
                <th scope="col" className="num">Brier</th>
                <th scope="col" className="num">Log loss</th>
                <th scope="col" className="num">ROI</th>
                <th scope="col" className="num">CLV</th>
                <th scope="col" className="num">Bins</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((metric, index) => {
                const roi = asNumber(metric.roi);
                const binCount = extractCalibrationBins(metric.calibration).length;
                return (
                  <tr key={`${metric.model_version ?? "model"}-${index}`}>
                    <td className="mono">{metric.model_version ?? "—"}</td>
                    <td className="mono cell-muted">{metric.strategy_version ?? "—"}</td>
                    <td className="cell-muted">
                      {[metric.competition, metric.market, metric.time_block]
                        .filter(Boolean)
                        .join(" · ") || "—"}
                    </td>
                    <td className="num">{formatNumber(metric.sample_count)}</td>
                    <td className="num">{formatFixed(metric.brier, 3)}</td>
                    <td className="num">{formatFixed(metric.log_loss, 3)}</td>
                    <td
                      className={`num ${
                        roi !== null && roi > 0
                          ? "text-positive"
                          : roi !== null && roi < 0
                            ? "text-negative"
                            : ""
                      }`}
                    >
                      {formatSignedPercent(roi)}
                    </td>
                    <td className="num">{formatSignedPercent(metric.clv)}</td>
                    <td className="num">{binCount > 0 ? formatNumber(binCount) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableFrame>
      )}
    </Panel>
  );
}

export function CalibrationSection({
  result,
}: {
  result: EndpointResult<Calibration>;
}) {
  const data = result.data;
  const models = Array.isArray(data?.models) ? data.models : [];
  const strategies = Array.isArray(data?.strategies) ? data.strategies : [];
  const metrics = Array.isArray(data?.metrics) ? data.metrics : [];
  const weights = Array.isArray(data?.weight_snapshots) ? data.weight_snapshots : [];
  const charted = metrics
    .map((metric) => ({ metric, bins: extractCalibrationBins(metric.calibration) }))
    .filter((entry) => entry.bins.some((bin) => bin.predicted !== null && bin.observed !== null))
    .slice(0, 6);

  return (
    <section id="calibration" className="section" aria-labelledby="calibration-title">
      <SectionHeader
        index="04"
        kicker="Reliability and policy"
        title="Calibration"
        meta={
          result.error
            ? "registry unavailable"
            : `${models.length} models · ${strategies.length} strategies`
        }
      />

      {result.error ? (
        <DataWarning
          label="Calibration"
          endpoint="/dashboard/calibration"
          error={result.error}
        />
      ) : null}

      {!data ? (
        <EmptyState>No calibration registry was returned.</EmptyState>
      ) : (
        <>
          <ModelsPanel models={models} />
          <StrategiesPanel strategies={strategies} />
          <MetricsPanel metrics={metrics} />

          <Panel
            title="Reliability plots"
            kicker="Predicted vs observed"
            meta={`${charted.length} plotted`}
          >
            {charted.length === 0 ? (
              <EmptyState>
                No calibration bins were supplied. Metrics remain available in the table above.
              </EmptyState>
            ) : (
              <>
                <p className="panel__note">
                  Each point is a probability bin. The dashed diagonal is perfect
                  calibration; points below it are overconfident, above it are
                  underconfident. Marker size scales with bin count.
                </p>
                <div className="cal-grid">
                  {charted.map((entry, index) => (
                    <CalibrationBinChart
                      key={`${entry.metric.model_version ?? "model"}-${index}`}
                      metric={entry.metric}
                      bins={entry.bins}
                    />
                  ))}
                </div>
              </>
            )}
          </Panel>

          <WeightsPanel snapshots={weights} />
        </>
      )}
    </section>
  );
}
