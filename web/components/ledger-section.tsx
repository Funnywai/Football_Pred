"use client";

import { useMemo, useState } from "react";

import {
  asNumber,
  formatDateTime,
  formatFixed,
  formatKickoff,
  formatMoney,
  formatNumber,
  formatOdds,
  formatSignedMoney,
  formatSignedPercent,
  hktDateKey,
  profitTone,
  statusTone,
} from "@/lib/format";
import type { EndpointResult } from "@/lib/api";
import type { Bet, Equity } from "@/lib/types";

import { DayNavigator } from "./day-navigator";
import { EquityChart } from "./equity-chart";
import {
  DataWarning,
  EmptyState,
  MatchCell,
  Panel,
  SectionHeader,
  StatusTag,
} from "./ui";
import { TableFrame } from "./table-frame";

const PAGE_SIZE = 10;

type DisplayBet = Bet & { displayLane: "V1" | "V2" };

function isOpen(status: string | null | undefined): boolean {
  return statusTone(status) === "accent";
}

function isSettled(bet: Bet): boolean {
  const status = (bet.status ?? "").toLowerCase();
  return Boolean(bet.settled_at) || ["won", "win", "lost", "loss", "void", "push", "settled"].includes(status);
}

function summarize(bets: Bet[]) {
  return {
    staked: bets.reduce((total, bet) => total + (asNumber(bet.stake) ?? 0), 0),
    profit: bets.reduce((total, bet) => total + (asNumber(bet.profit) ?? 0), 0),
    open: bets.filter((bet) => isOpen(bet.status)).length,
    settled: bets.filter(isSettled).length,
  };
}

function LaneSummary({
  lane,
  bets,
  unavailable,
  currency,
}: {
  lane: "V1" | "V2";
  bets: Bet[];
  unavailable: boolean;
  currency: string;
}) {
  const total = summarize(bets);
  const netTone = profitTone(total.profit);
  return (
    <div className="ledger-summary ledger-summary--lane">
      <span className={`lane-tag lane-tag--${lane.toLowerCase()}`}>{lane}</span>
      <div className="ledger-summary__item">
        <span>Stake in window</span>
        <b>{unavailable || bets.length === 0 ? "—" : formatMoney(total.staked, currency)}</b>
      </div>
      <div className="ledger-summary__item">
        <span>Realised P/L</span>
        <b className={`text-${netTone}`}>
          {unavailable || bets.length === 0 ? "—" : formatSignedMoney(total.profit, currency)}
        </b>
      </div>
      <div className="ledger-summary__item">
        <span>Open</span>
        <b>{unavailable ? "—" : formatNumber(total.open)}</b>
      </div>
      <div className="ledger-summary__item">
        <span>Settled</span>
        <b>{unavailable ? "—" : formatNumber(total.settled)}</b>
      </div>
    </div>
  );
}

function SearchBox({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="ledger-search">
      <span className="ledger-search__label">Search ledger</span>
      <input
        className="ledger-search__input"
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Team, pick, lane, status or model"
      />
    </label>
  );
}


export function LedgerSection({
  betsResult,
  equityResult,
  challengerBetsResult,
  challengerEquityResult,
}: {
  betsResult: EndpointResult<Bet[]>;
  equityResult: EndpointResult<Equity>;
  challengerBetsResult: EndpointResult<Bet[]>;
  challengerEquityResult: EndpointResult<Equity>;
}) {
  const bets = useMemo(
    () => (Array.isArray(betsResult.data) ? betsResult.data : []),
    [betsResult.data],
  );
  const challengerBets = useMemo(
    () =>
      Array.isArray(challengerBetsResult.data)
        ? challengerBetsResult.data
        : [],
    [challengerBetsResult.data],
  );
  const equity = equityResult.data;
  const challengerEquity = challengerEquityResult.data;
  const currency = "HKD";
  const [query, setQuery] = useState("");
  const [dayIndex, setDayIndex] = useState(0);

  const merged = useMemo<DisplayBet[]>(
    () =>
      [
        ...bets.map((bet) => ({ ...bet, displayLane: "V1" as const })),
        ...challengerBets.map((bet) => ({ ...bet, displayLane: "V2" as const })),
      ].sort((left, right) =>
        (right.placed_at ?? "").localeCompare(left.placed_at ?? ""),
      ),
    [bets, challengerBets],
  );

  const dayKeys = useMemo(
    () =>
      Array.from(
        new Set(
          merged
            .map((bet) => hktDateKey(bet.placed_at ?? bet.kickoff_at))
            .filter((key): key is string => Boolean(key)),
        ),
      ).sort((left, right) => right.localeCompare(left)),
    [merged],
  );
  const selectedDay = dayKeys[dayIndex] ?? null;
  const dayBets = useMemo(
    () =>
      merged.filter(
        (bet) => hktDateKey(bet.placed_at ?? bet.kickoff_at) === selectedDay,
      ),
    [merged, selectedDay],
  );
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return dayBets;
    return dayBets.filter((bet) =>
      [
        bet.displayLane,
        bet.home_team,
        bet.away_team,
        bet.competition,
        bet.market,
        bet.selection,
        bet.status,
        bet.model_version,
        bet.lane,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle)),
    );
  }, [dayBets, query]);

  const visibleBets = filtered.slice(0, PAGE_SIZE);
  const totalRows = merged.length;
  const betsUnavailable = Boolean(betsResult.error);
  const challengerUnavailable = Boolean(challengerBetsResult.error);
  const observations = Array.isArray(equity?.points)
    ? equity.points.filter((point) => point.t).length
    : 0;
  const challengerObservations = Array.isArray(challengerEquity?.points)
    ? challengerEquity.points.filter((point) => point.t).length
    : 0;

  const updateQuery = (next: string) => {
    setQuery(next);
  };

  return (
    <section id="paper-ledger" className="section" aria-labelledby="paper-ledger-title">
      <SectionHeader
        index="03"
        kicker="Paper account"
        title="Paper Ledger"
        meta={
          betsResult.error || equityResult.error || challengerBetsResult.error
            ? "ledger partially unavailable"
            : `${totalRows} ${totalRows === 1 ? "bet" : "bets"} · V1 + V2`
        }
      />

      {equityResult.error ? (
        <DataWarning label="V1 equity" endpoint="/dashboard/equity" error={equityResult.error} />
      ) : null}
      {betsResult.error ? (
        <DataWarning label="V1 bets" endpoint="/dashboard/bets?limit=500" error={betsResult.error} />
      ) : null}
      {challengerEquityResult.error ? (
        <DataWarning
          label="V2 equity"
          endpoint="/dashboard/challenger/equity"
          error={challengerEquityResult.error}
        />
      ) : null}
      {challengerBetsResult.error ? (
        <DataWarning
          label="V2 bets"
          endpoint="/dashboard/challenger/bets?limit=500"
          error={challengerBetsResult.error}
        />
      ) : null}

      <Panel
        title="Equity curve"
        kicker="Bankroll over time"
        meta={
          equityResult.error && challengerEquityResult.error
            ? "equity unavailable"
            : `${observations + challengerObservations} settled observation${
                observations + challengerObservations === 1 ? "" : "s"
              }`
        }
      >
        <EquityChart
          equity={equity}
          challengerEquity={challengerEquity}
          currency={currency}
          unavailable={Boolean(equityResult.error && challengerEquityResult.error)}
        />
      </Panel>

      <div className="ledger-summary-stack" role="group" aria-label="Derived ledger totals by lane">
        <LaneSummary lane="V1" bets={bets} unavailable={betsUnavailable} currency={currency} />
        <LaneSummary
          lane="V2"
          bets={challengerBets}
          unavailable={challengerUnavailable}
          currency={currency}
        />
      </div>

      <Panel
        title="Bet ledger"
        kicker="V1 and V2 paper bets"
        meta={`${visibleBets.length} / ${dayBets.length} rows · ${PAGE_SIZE} max`}
        bodyClassName="panel__body--flush"
      >
        <div className="ledger-toolbar">
          <SearchBox value={query} onChange={updateQuery} />
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

        {visibleBets.length === 0 ? (
          <EmptyState>
            {betsResult.error || challengerBetsResult.error
              ? "Bet rows could not be loaded."
              : query.trim()
                ? "No bets match this search."
                : dayKeys.length > 0
                  ? "No paper bets on this day."
                  : "No paper bets have been placed yet. The ledger is intentionally empty."}
          </EmptyState>
        ) : (
          <TableFrame label="V1 and V2 paper bet ledger" wide>
            <table className="table--bets">
              <caption className="sr-only">
                V1 and V2 paper bet ledger including lane, match result, stake,
                settlement profit, closing-line value and Brier score
              </caption>
              <thead>
                <tr>
                  <th scope="col">Lane</th>
                  <th scope="col">Placed (HKT)</th>
                  <th scope="col">Match</th>
                  <th scope="col">Result</th>
                  <th scope="col">Market / selection</th>
                  <th scope="col" className="num">Odds</th>
                  <th scope="col" className="num">Stake</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">P/L</th>
                  <th scope="col" className="num">CLV</th>
                  <th scope="col" className="num">Brier</th>
                  <th scope="col">Model</th>
                </tr>
              </thead>
              <tbody>
                {visibleBets.map((bet) => {
                  const profit = asNumber(bet.profit);
                  const tone = profitTone(profit);
                  return (
                    <tr key={bet.bet_id ?? `${bet.match_id}-${bet.placed_at}`}>
                      <td>
                        <span className={`lane-tag lane-tag--${bet.displayLane.toLowerCase()}`}>
                          {bet.displayLane}
                        </span>
                      </td>
                      <td className="cell-time">
                        <time dateTime={bet.placed_at ?? undefined}>
                          {formatDateTime(bet.placed_at)}
                        </time>
                        {bet.settled_at ? (
                          <span className="subline">settled {formatDateTime(bet.settled_at)}</span>
                        ) : null}
                      </td>
                      <td>
                        <MatchCell
                          home={bet.home_team}
                          away={bet.away_team}
                          competition={bet.competition}
                          matchId={bet.match_id}
                        />
                        <span className="subline">
                          <time dateTime={bet.kickoff_at ?? undefined}>
                            kickoff {formatKickoff(bet.kickoff_at)}
                          </time>
                        </span>
                      </td>
                      <td className="mono" title="90-minute score">
                        {bet.home_goals_90 === null ||
                        bet.home_goals_90 === undefined ||
                        bet.away_goals_90 === null ||
                        bet.away_goals_90 === undefined
                          ? "—"
                          : `${bet.home_goals_90}–${bet.away_goals_90}`}
                      </td>
                      <td>
                        <span className="selection">
                          <span className="selection__market">{bet.market ?? "—"}</span>
                          <span className="selection__pick">{bet.selection ?? "—"}</span>
                        </span>
                        {bet.line_key ? <span className="subline mono">{bet.line_key}</span> : null}
                      </td>
                      <td className="num">{formatOdds(bet.odds)}</td>
                      <td className="num">{formatMoney(bet.stake, currency)}</td>
                      <td>
                        <StatusTag status={bet.status} />
                      </td>
                      <td className={`num text-${tone}`}>
                        {profit === null ? "—" : formatSignedMoney(profit, currency)}
                        {bet.payout !== null && bet.payout !== undefined ? (
                          <span className="subline">payout {formatMoney(bet.payout, currency)}</span>
                        ) : null}
                      </td>
                      <td className="num">{formatSignedPercent(bet.clv)}</td>
                      <td className="num">{formatFixed(bet.brier, 3)}</td>
                      <td>
                        <span className="mono cell-model">{bet.model_version ?? "—"}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableFrame>
        )}
      </Panel>
    </section>
  );
}
