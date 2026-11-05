"use client";

import { useMemo, useState } from "react";

import type { EndpointResult } from "@/lib/api";
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
import type { LlmLedger } from "@/lib/llm-types";
import type { Bet, Equity } from "@/lib/types";

import { DayNavigator } from "./day-navigator";
import { EquityChart } from "./equity-chart";
import { TableFrame } from "./table-frame";
import {
  DataWarning,
  EmptyState,
  MatchCell,
  Panel,
  SectionHeader,
  StatusTag,
} from "./ui";

const PAGE_SIZE = 10;

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

export function LlmLedgerSection({
  ledger,
  betsResult,
  equityResult,
}: {
  ledger: LlmLedger | null;
  betsResult: EndpointResult<Bet[]>;
  equityResult: EndpointResult<Equity>;
}) {
  const bets = useMemo(
    () => (Array.isArray(betsResult.data) ? betsResult.data : []),
    [betsResult.data],
  );
  const equity = equityResult.data;
  const currency = ledger?.currency?.trim() || "HKD";
  const [query, setQuery] = useState("");
  const [dayIndex, setDayIndex] = useState(0);

  const sorted = useMemo(
    () =>
      [...bets].sort((left, right) =>
        (right.placed_at ?? "").localeCompare(left.placed_at ?? ""),
      ),
    [bets],
  );
  const dayKeys = useMemo(
    () =>
      Array.from(
        new Set(
          sorted
            .map((bet) => hktDateKey(bet.placed_at ?? bet.kickoff_at))
            .filter((key): key is string => Boolean(key)),
        ),
      ).sort((left, right) => right.localeCompare(left)),
    [sorted],
  );
  const selectedDay = dayKeys[dayIndex] ?? null;
  const dayBets = useMemo(
    () =>
      sorted.filter(
        (bet) => hktDateKey(bet.placed_at ?? bet.kickoff_at) === selectedDay,
      ),
    [sorted, selectedDay],
  );
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return dayBets;
    return dayBets.filter((bet) =>
      [bet.home_team, bet.away_team, bet.competition, bet.market, bet.selection, bet.status, bet.model_version]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle)),
    );
  }, [dayBets, query]);
  const visibleBets = filtered.slice(0, PAGE_SIZE);
  const summary = summarize(bets);
  const netTone = profitTone(summary.profit);
  const observations = Array.isArray(equity?.points)
    ? equity.points.filter((point) => point.t).length
    : 0;

  return (
    <section id="llm-paper-ledger" className="section" aria-labelledby="llm-paper-ledger-title">
      <SectionHeader
        index="05"
        kicker="Separate paper account"
        title="Paper Ledger"
        meta={
          betsResult.error || equityResult.error
            ? "ledger partially unavailable"
            : `${bets.length} ${bets.length === 1 ? "bet" : "bets"} · LLM lane`
        }
      />

      {betsResult.error ? (
        <DataWarning label="LLM bets" endpoint="/llm/bets" error={betsResult.error} />
      ) : null}
      {equityResult.error ? (
        <DataWarning label="LLM equity" endpoint="/llm/equity" error={equityResult.error} />
      ) : null}

      <Panel
        title="Equity curve"
        kicker="LLM bankroll over time"
        meta={
          equityResult.error
            ? "equity unavailable"
            : observations > 0
              ? `${observations} settled observation${observations === 1 ? "" : "s"}`
              : "no settled observations"
        }
      >
        <EquityChart
          equity={equity}
          currency={currency}
          unavailable={Boolean(equityResult.error)}
          primaryLabel="LLM"
        />
      </Panel>

      <div className="ledger-summary" role="group" aria-label="LLM ledger totals">
        <div className="ledger-summary__item">
          <span>Stake in window</span>
          <b>{betsResult.error || bets.length === 0 ? "—" : formatMoney(summary.staked, currency)}</b>
        </div>
        <div className="ledger-summary__item">
          <span>Realised P/L</span>
          <b className={`text-${netTone}`}>
            {betsResult.error || bets.length === 0 ? "—" : formatSignedMoney(summary.profit, currency)}
          </b>
        </div>
        <div className="ledger-summary__item">
          <span>Open</span>
          <b>{betsResult.error ? "—" : formatNumber(summary.open)}</b>
        </div>
        <div className="ledger-summary__item">
          <span>Settled</span>
          <b>{betsResult.error ? "—" : formatNumber(summary.settled)}</b>
        </div>
      </div>

      <Panel
        title="Bet ledger"
        kicker="LLM paper bets"
        meta={`${visibleBets.length} / ${dayBets.length} rows · ${PAGE_SIZE} max`}
        bodyClassName="panel__body--flush"
      >
        <div className="ledger-toolbar">
          <label className="ledger-search">
            <span className="ledger-search__label">Search ledger</span>
            <input
              className="ledger-search__input"
              type="search"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setDayIndex(0);
              }}
              placeholder="Team, pick, status or model"
            />
          </label>
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
            {betsResult.error
              ? "LLM bet rows could not be loaded."
              : query.trim()
                ? "No LLM bets match this search."
                : "No LLM paper bets have been placed yet."}
          </EmptyState>
        ) : (
          <TableFrame label="LLM paper bet ledger" wide>
            <table className="table--bets llm-bets-table">
              <caption className="sr-only">
                LLM paper bet ledger including stake, settlement profit,
                closing-line value and Brier score
              </caption>
              <thead>
                <tr>
                  <th scope="col">Placed (HKT)</th>
                  <th scope="col">Match</th>
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
