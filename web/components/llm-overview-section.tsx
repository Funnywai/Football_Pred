import type { EndpointResult } from "@/lib/api";
import {
  asNumber,
  formatKickoff,
  formatMoney,
  formatNumber,
  formatPercent,
  formatSignedPercent,
} from "@/lib/format";
import type { LlmStatus } from "@/lib/llm-types";

import { TableFrame } from "./table-frame";
import {
  DataWarning,
  EmptyState,
  MatchCell,
  Panel,
  SectionHeader,
  StatusTag,
} from "./ui";

function textOr(value: string | null | undefined, fallback: string): string {
  return value?.trim() ? value.trim() : fallback;
}

function countOrDash(value: number | null | undefined): string {
  return typeof value === "number" ? formatNumber(value) : "—";
}

function LlmKpi({
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
  tone?: "neutral" | "muted" | "accent" | "positive" | "negative";
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


export function LlmOverviewSection({
  result,
}: {
  result: EndpointResult<LlmStatus>;
}) {
  const data = result.data;
  const counts = data?.counts;
  const ledger = data?.ledger ?? null;
  const allFixtures = Array.isArray(data?.next_fixtures) ? data.next_fixtures : [];
  const fixtures = allFixtures.slice(0, 5);
  const roi = asNumber(ledger?.roi);
  const drawdown = asNumber(ledger?.max_drawdown);
  const drawdownLabel =
    drawdown === null
      ? "—"
      : Math.abs(drawdown) <= 1
        ? formatPercent(drawdown)
        : formatMoney(drawdown, ledger?.currency ?? "HKD");
  const currency = ledger?.currency?.trim() || "HKD";

  const fixtureMeta =
    allFixtures.length > fixtures.length
      ? `${fixtures.length} of ${allFixtures.length} listed`
      : `${fixtures.length} listed`;

  return (
    <section id="llm-overview" className="section" aria-labelledby="overview-title">
      <SectionHeader
        index="01"
        kicker="Lane overview"
        title="Overview"
        meta={
          result.error
            ? "snapshot unavailable"
            : data
              ? `paper lane · ${textOr(data.phase, "phase unknown")}`
              : "no snapshot"
        }
      />

      {result.error ? (
        <DataWarning label="LLM status" endpoint="/llm/status" error={result.error} />
      ) : null}

      {!data ? (
        <EmptyState>
          {result.error
            ? "No LLM status snapshot could be loaded. Resolve the API connection shown above; no counts, fixtures or lane state are invented."
            : "The LLM status endpoint returned no payload. The lane may still be starting up."}
        </EmptyState>
      ) : (
        <>
          <div
            className="kpi-strip llm-kpi-strip"
            role="group"
            aria-label="LLM lane key indicators"
          >
            <LlmKpi
              label="Bankroll"
              value={formatMoney(ledger?.bankroll, currency)}
              hint={`initial ${formatMoney(ledger?.initial_bankroll, currency)} · ${currency}`}
            />
            <LlmKpi
              label="Available"
              value={formatMoney(ledger?.available, currency)}
              hint={`reserved ${formatMoney(ledger?.reserved, currency)}`}
            />
            <LlmKpi
              label="ROI"
              value={formatSignedPercent(roi)}
              tone={
                roi === null
                  ? "muted"
                  : roi > 0
                    ? "positive"
                    : roi < 0
                      ? "negative"
                      : "neutral"
              }
              hint={`${formatMoney(ledger?.total_stake, currency)} staked`}
            />
            <LlmKpi
              label="Open bets"
              value={formatNumber(ledger?.pending_bets)}
              unit="bets"
              hint={`${formatNumber(ledger?.settled_bets)} settled`}
              tone="accent"
            />
            <LlmKpi
              label="Predictions"
              value={countOrDash(counts?.research_runs ?? counts?.predictions)}
              hint={`${countOrDash(counts?.research_runs ?? counts?.predictions)} reports · max DD ${drawdownLabel}`}
            />
          </div>

          <div className="overview-grid">
            <Panel
              title="Next fixtures"
              kicker="Scheduled LLM competitions"
              meta={fixtureMeta}
              className="overview-grid__fixtures"
              bodyClassName="panel__body--flush"
            >
              {fixtures.length === 0 ? (
                <EmptyState>
                  No scheduled LLM fixtures were returned in this snapshot. Fixtures
                  are not inferred from the deterministic schedule.
                </EmptyState>
              ) : (
                <TableFrame label="Upcoming LLM fixtures">
                  <table className="table--fixtures">
                    <caption className="sr-only">
                      Upcoming LLM competition fixtures with kickoff time in Hong Kong
                      time
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
                        <tr key={fixture.match_id ?? `llm-fixture-${index}`}>
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
          </div>

          <p className="llm-note llm-overview-note">
            The LLM lane has a separate paper ledger and bankroll. Seven research
            analysts produce evidence-backed findings, the main agent writes the
            betting report and recommendation, and the deterministic safety layer
            alone can place or reject the paper bet.
          </p>
        </>
      )}
    </section>
  );
}
