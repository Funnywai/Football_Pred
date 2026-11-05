"use client";

import type { EndpointResult } from "@/lib/api";
import { useMemo, useState } from "react";

import {
  asNumber,
  formatKickoff,
  formatMoney,
  formatNumber,
  formatPercent,
  formatSignedPercent,
  hktDateKey,
} from "@/lib/format";
import type { LlmStatus } from "@/lib/llm-types";

import { DayNavigator } from "./day-navigator";
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
  const allFixtures = useMemo(
    () => (Array.isArray(data?.next_fixtures) ? data.next_fixtures : []),
    [data],
  );
  const dayKeys = useMemo(
    () =>
      Array.from(
        new Set(
          allFixtures
            .map((fixture) => hktDateKey(fixture.kickoff_at))
            .filter((key): key is string => Boolean(key)),
        ),
      ).sort(),
    [allFixtures],
  );
  const [dayIndex, setDayIndex] = useState(0);
  const [fixtureQuery, setFixtureQuery] = useState("");
  const selectedDay = dayKeys[dayIndex] ?? null;
  const fixtures = useMemo(() => {
    const needle = fixtureQuery.trim().toLowerCase();
    return allFixtures.filter((fixture) => {
      if (hktDateKey(fixture.kickoff_at) !== selectedDay) return false;
      if (!needle) return true;
      return [fixture.home_team, fixture.away_team, fixture.competition, fixture.status]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle));
    });
  }, [allFixtures, fixtureQuery, selectedDay]);
  const roi = asNumber(ledger?.roi);
  const drawdown = asNumber(ledger?.max_drawdown);
  const drawdownLabel =
    drawdown === null
      ? "—"
      : Math.abs(drawdown) <= 1
        ? formatPercent(drawdown)
        : formatMoney(drawdown, ledger?.currency ?? "HKD");
  const currency = ledger?.currency?.trim() || "HKD";

  const fixtureMeta = `${fixtures.length} / ${allFixtures.length} listed`;

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

          <div className="overview-grid overview-grid--single">
            <Panel
              title="Next fixtures"
              kicker="Scheduled LLM competitions"
              meta={fixtureMeta}
              className="overview-grid__fixtures"
              bodyClassName="panel__body--flush"
            >
              <div className="ledger-toolbar">
                <label className="ledger-search">
                  <span className="ledger-search__label">Search fixtures</span>
                  <input
                    className="ledger-search__input"
                    type="search"
                    value={fixtureQuery}
                    onChange={(event) => {
                      setFixtureQuery(event.target.value);
                      setDayIndex(0);
                    }}
                    placeholder="Team, competition or status"
                  />
                </label>
                <DayNavigator
                  dayKey={selectedDay}
                  dayIndex={dayIndex}
                  dayCount={dayKeys.length}
                  onFirst={() => setDayIndex(0)}
                  onPrevious={() => setDayIndex((current) => Math.max(0, current - 1))}
                  onNext={() =>
                    setDayIndex((current) => Math.min(dayKeys.length - 1, current + 1))
                  }
                  direction="ascending"
                />
              </div>
              {fixtures.length === 0 ? (
                <EmptyState>
                  {fixtureQuery.trim()
                    ? "No fixtures match this search on the selected day."
                    : "No scheduled LLM fixtures were returned in this snapshot. Fixtures are not inferred from the deterministic schedule."}
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
