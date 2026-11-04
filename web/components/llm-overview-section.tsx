import type { ReactNode } from "react";

import type { EndpointResult } from "@/lib/api";
import { formatKickoff, formatNumber, formatSignedPercent } from "@/lib/format";
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
  tone?: "neutral" | "muted" | "accent";
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

function LaneFact({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="llm-state__row">
      <dt>{label}</dt>
      <dd>{children}</dd>
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
  const runtime = data?.runtime ?? {};
  const ledger = data?.ledger ?? null;
  const allFixtures = Array.isArray(data?.next_fixtures) ? data.next_fixtures : [];
  const fixtures = allFixtures.slice(0, 5);
  const competitions = Array.isArray(data?.competitions)
    ? data.competitions.filter((item) => typeof item === "string" && item.trim())
    : [];

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
              label="Evidence packets"
              value={countOrDash(counts?.evidence_packets)}
              hint="frozen pre-kickoff inputs"
            />
            <LlmKpi
              label="Agent runs"
              value={countOrDash(counts?.agent_runs)}
              hint={
                counts?.agent_runs === 0
                  ? "not executed in this snapshot"
                  : typeof counts?.agent_runs === "number"
                    ? "recorded at snapshot time"
                    : "run count not reported"
              }
            />
            <LlmKpi
              label="Predictions"
              value={countOrDash(counts?.predictions)}
              hint="ensemble output rows"
            />
            <LlmKpi
              label="Paper bets"
              value={countOrDash(counts?.paper_bets)}
              hint="separate LLM paper ledger"
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

            <Panel
              title="Lane state"
              kicker="Read-only runtime"
              meta={textOr(data.phase, "phase unknown")}
              className="llm-state-panel"
            >
              <dl className="llm-state">
                <LaneFact label="Provider">
                  <span className="llm-state__value">
                    {textOr(runtime.provider, "not reported")}
                  </span>
                </LaneFact>
                <LaneFact label="Model">
                  <span className="llm-state__value">
                    {textOr(runtime.model, "not reported")}
                  </span>
                </LaneFact>
                <LaneFact label="Decision layer">
                  <span className="llm-state__value">
                    {textOr(runtime.decision_layer, "not reported")}
                  </span>
                </LaneFact>
                <LaneFact label="Phase">
                  <StatusTag status={data.phase} tone="neutral" />
                </LaneFact>
                <LaneFact label="Competitions">
                  <span className="llm-state__value">
                    {competitions.length > 0 ? competitions.join(" · ") : "not reported"}
                  </span>
                </LaneFact>
                <LaneFact label="Paper ledger">
                  <StatusTag status={runtime.paper_ledger} tone="muted" />
                </LaneFact>
                <LaneFact label="LLM ROI">
                  <span className="llm-state__value">
                    {ledger
                      ? `${formatSignedPercent(ledger.roi, 2)} · ${formatNumber(ledger.settled_bets)} settled`
                      : "not opened"}
                  </span>
                </LaneFact>
                <LaneFact label="LLM bankroll">
                  <span className="llm-state__value">
                    {ledger?.bankroll ?? "—"}
                  </span>
                </LaneFact>
                <LaneFact label="Prompt / agent counts">
                  <span className="llm-state__value">
                    {countOrDash(counts?.prompts)} prompts · {countOrDash(counts?.agents)} agents
                  </span>
                </LaneFact>
              </dl>
            </Panel>
          </div>

          <p className="llm-note llm-overview-note">
            The LLM lane has a separate paper ledger and bankroll: agents cannot
            write directly to the database or settle bets; the deterministic
            orchestrator persists frozen evidence, runs, ensemble output and the
            EV/Kelly paper-bet decision. The next run is the T-28m pre-kickoff
            window; until a run is recorded, the lane stays on standby.
          </p>
        </>
      )}
    </section>
  );
}
