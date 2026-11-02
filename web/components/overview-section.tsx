import {
  asNumber,
  formatDateTime,
  formatFixed,
  formatKickoff,
  formatMoney,
  formatNumber,
  formatPercent,
  formatSignedPercent,
} from "@/lib/format";
import type { EndpointResult } from "@/lib/api";
import type { Overview } from "@/lib/types";

import {
  DataWarning,
  EmptyState,
  MatchCell,
  Panel,
  SectionHeader,
  StatusTag,
} from "./ui";
import { TableFrame } from "./table-frame";

function Kpi({
  label,
  value,
  unit,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="kpi">
      <span className="kpi__label">{label}</span>
      <span className={`kpi__value kpi__value--${tone}`}>
        {value}
        {unit ? <span className="kpi__unit">{unit}</span> : null}
      </span>
      {hint ? <span className="kpi__hint">{hint}</span> : null}
    </div>
  );
}

export function OverviewSection({
  result,
}: {
  result: EndpointResult<Overview>;
}) {
  const data = result.data;
  const currency = data?.bankroll?.currency?.trim() || "HKD";
  const roi = asNumber(data?.ledger?.roi);
  const drawdown = asNumber(data?.ledger?.max_drawdown);
  const drawdownLabel =
    drawdown === null
      ? "—"
      : Math.abs(drawdown) <= 1
        ? formatPercent(drawdown)
        : formatMoney(drawdown, currency);
  const fixtures = Array.isArray(data?.next_fixtures) ? data.next_fixtures : [];
  const sources = Array.isArray(data?.latest_sources) ? data.latest_sources : [];
  const calibration = Array.isArray(data?.latest_calibration)
    ? data.latest_calibration
    : [];

  return (
    <section id="overview" className="section" aria-labelledby="overview-title">
      <SectionHeader
        index="01"
        kicker="Account and fixtures"
        title="Overview"
        meta={
          result.error
            ? "snapshot unavailable"
            : result.data
              ? `${formatNumber(data?.counts?.matches)} matches tracked`
              : "no snapshot"
        }
      />

      {result.error ? (
        <DataWarning label="Overview" endpoint="/dashboard/overview" error={result.error} />
      ) : null}

      {!data ? (
        <EmptyState>
          {result.error
            ? "No overview snapshot could be loaded. Resolve the API connection shown above."
            : "No overview snapshot was returned. The API may still be warming up."}
        </EmptyState>
      ) : (
        <>
          <div className="kpi-strip" role="group" aria-label="Key performance indicators">
            <Kpi
              label="Bankroll"
              value={formatMoney(data.bankroll?.balance, currency)}
              hint={`initial ${formatMoney(data.bankroll?.initial, currency)} · ${currency}`}
            />
            <Kpi
              label="Available"
              value={formatMoney(data.bankroll?.available, currency)}
              hint={`reserved ${formatMoney(data.bankroll?.reserved, currency)}`}
            />
            <Kpi
              label="ROI"
              value={formatSignedPercent(roi)}
              tone={roi === null ? "muted" : roi > 0 ? "positive" : roi < 0 ? "negative" : "neutral"}
              hint={`${formatMoney(data.ledger?.total_stake, currency)} staked`}
            />
            <Kpi
              label="Open bets"
              value={formatNumber(data.ledger?.pending_bets)}
              unit="bets"
              hint={`${formatNumber(data.ledger?.settled_bets)} settled`}
              tone="accent"
            />
            <Kpi
              label="Predictions"
              value={formatNumber(data.counts?.predictions)}
              hint={`${formatNumber(data.counts?.decisions)} decisions · max DD ${drawdownLabel}`}
            />
          </div>

          <div className="overview-grid">
            <Panel
              title="Next fixtures"
              kicker="Schedule"
              meta={`${fixtures.length} listed`}
              className="overview-grid__fixtures"
              bodyClassName="panel__body--flush"
            >
              {fixtures.length === 0 ? (
                <EmptyState>No upcoming fixtures in this snapshot.</EmptyState>
              ) : (
                <TableFrame label="Upcoming fixtures">
                  <table className="table--fixtures">
                    <caption className="sr-only">
                      Upcoming fixtures with kickoff time in Hong Kong time
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Kickoff (HKT)</th>
                        <th scope="col">Match</th>
                        <th scope="col">Competition</th>
                        <th scope="col">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fixtures.map((fixture, index) => (
                        <tr key={fixture.match_id ?? `fixture-${index}`}>
                          <td className="cell-time">
                            <time dateTime={fixture.kickoff_at ?? undefined}>
                              {formatKickoff(fixture.kickoff_at)}
                            </time>
                          </td>
                          <td>
                            <MatchCell
                              home={fixture.home_team}
                              away={fixture.away_team}
                              matchId={fixture.match_id}
                            />
                          </td>
                          <td className="cell-muted">{fixture.competition ?? "—"}</td>
                          <td>
                            <StatusTag status={fixture.status} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableFrame>
              )}
            </Panel>

            <Panel
              title="Source health"
              kicker="Ingestion"
              meta={`${sources.length} sources`}
              className="overview-grid__sources"
            >
              {sources.length === 0 ? (
                <EmptyState>No source runs have been recorded.</EmptyState>
              ) : (
                <ul className="source-list">
                  {sources.map((source, index) => (
                    <li className="source-row" key={`${source.source_name ?? "source"}-${index}`}>
                      <div className="source-row__main">
                        <span className="source-row__name">{source.source_name ?? "unnamed source"}</span>
                        <StatusTag status={source.status} />
                      </div>
                      <div className="source-row__meta">
                        <span>{formatDateTime(source.finished_at)}</span>
                        <span
                          className={
                            (source.error_count ?? 0) > 0 ? "text-negative" : "text-muted"
                          }
                        >
                          {formatNumber(source.error_count)} errors
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          <Panel
            title="Latest calibration"
            kicker="Model review"
            meta={`${calibration.length} slices`}
            bodyClassName="panel__body--flush"
          >
            {calibration.length === 0 ? (
              <EmptyState>No calibration slices have been computed yet.</EmptyState>
            ) : (
              <TableFrame label="Latest calibration slices" wide>
                <table className="table--calibration">
                  <caption className="sr-only">Latest calibration metrics by model slice</caption>
                  <thead>
                    <tr>
                      <th scope="col">Model</th>
                      <th scope="col">Slice</th>
                      <th scope="col" className="num">N</th>
                      <th scope="col" className="num">Brier</th>
                      <th scope="col" className="num">Log loss</th>
                      <th scope="col" className="num">ROI</th>
                      <th scope="col" className="num">CLV</th>
                    </tr>
                  </thead>
                  <tbody>
                    {calibration.map((row, index) => {
                      const rowRoi = asNumber(row.roi);
                      return (
                        <tr key={`${row.model_version ?? "model"}-${index}`}>
                          <td>
                            <span className="mono">{row.model_version ?? "—"}</span>
                            {row.strategy_version ? (
                              <span className="subline">strategy {row.strategy_version}</span>
                            ) : null}
                          </td>
                          <td className="cell-muted">
                            {[row.competition, row.market, row.time_block]
                              .filter(Boolean)
                              .join(" · ") || "—"}
                          </td>
                          <td className="num">{formatNumber(row.sample_count)}</td>
                          <td className="num">{formatFixed(row.brier, 3)}</td>
                          <td className="num">{formatFixed(row.log_loss, 3)}</td>
                          <td
                            className={`num ${
                              rowRoi !== null && rowRoi > 0
                                ? "text-positive"
                                : rowRoi !== null && rowRoi < 0
                                  ? "text-negative"
                                  : ""
                            }`}
                          >
                            {formatSignedPercent(rowRoi)}
                          </td>
                          <td className="num">{formatSignedPercent(row.clv)}</td>
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
