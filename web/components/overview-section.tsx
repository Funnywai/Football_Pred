import {
  asNumber,
  formatDateTime,
  formatKickoff,
  formatMoney,
  formatNumber,
  formatPercent,
  formatSignedPercent,
} from "@/lib/format";
import type { EndpointResult } from "@/lib/api";
import type { ChallengerSummary, Overview } from "@/lib/types";

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
  challengerResult,
}: {
  result: EndpointResult<Overview>;
  challengerResult: EndpointResult<ChallengerSummary>;
}) {
  const data = result.data;
  const v2 = challengerResult.data;
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
  const v2Currency = v2?.bankroll?.currency?.trim() || "HKD";
  const v2Roi = asNumber(v2?.ledger?.roi);
  const v2Drawdown = asNumber(v2?.ledger?.max_drawdown);
  const v2DrawdownLabel =
    v2Drawdown === null
      ? "—"
      : Math.abs(v2Drawdown) <= 1
        ? formatPercent(v2Drawdown)
        : formatMoney(v2Drawdown, v2Currency);

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
          <div className="kpi-lane">
            <div className="kpi-lane__head">
              <span className="kpi-lane__badge">V1</span>
              <span>{data.experiment?.model_version ?? "poisson-v1"} · {data.experiment?.strategy_version ?? "g1"}</span>
            </div>
            <div className="kpi-strip" role="group" aria-label="V1 key performance indicators">
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
              value={formatNumber(data.counts?.predicted_matches)}
              hint={`max DD ${drawdownLabel}`}
            />
            </div>
          </div>

          <div className="kpi-lane">
            <div className="kpi-lane__head">
              <span className="kpi-lane__badge kpi-lane__badge--v2">V2</span>
              <span>
                {v2?.experiment?.model_version ?? "poisson-v2-shrunk"} ·{" "}
                {v2?.experiment?.strategy_version ?? "g1"}
                {v2?.experiment ? " · active" : " · not active"}
              </span>
            </div>
            <div className="kpi-strip" role="group" aria-label="V2 key performance indicators">
              <Kpi
                label="Bankroll"
                value={formatMoney(v2?.bankroll?.balance, v2Currency)}
                hint={`initial ${formatMoney(v2?.bankroll?.initial, v2Currency)} · ${v2Currency}`}
              />
              <Kpi
                label="Available"
                value={formatMoney(v2?.bankroll?.available, v2Currency)}
                hint={`reserved ${formatMoney(v2?.bankroll?.reserved, v2Currency)}`}
              />
              <Kpi
                label="ROI"
                value={formatSignedPercent(v2Roi)}
                tone={v2Roi === null ? "muted" : v2Roi > 0 ? "positive" : v2Roi < 0 ? "negative" : "neutral"}
                hint={`${formatMoney(v2?.ledger?.total_stake, v2Currency)} staked`}
              />
              <Kpi
                label="Open bets"
                value={formatNumber(v2?.ledger?.pending_bets)}
                unit="bets"
                hint={`${formatNumber(v2?.ledger?.settled_bets)} settled`}
                tone="accent"
              />
              <Kpi
                label="Predictions"
                value={formatNumber(v2?.counts?.predicted_matches)}
                hint={`max DD ${v2DrawdownLabel}`}
              />
            </div>
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

        </>
      )}
    </section>
  );
}
