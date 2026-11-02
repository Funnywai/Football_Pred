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
  profitTone,
  statusTone,
} from "@/lib/format";
import type { EndpointResult } from "@/lib/api";
import type { Bet, Equity } from "@/lib/types";

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

function isOpen(status: string | null | undefined): boolean {
  return statusTone(status) === "accent";
}

function isSettled(bet: Bet): boolean {
  const status = (bet.status ?? "").toLowerCase();
  return Boolean(bet.settled_at) || ["won", "win", "lost", "loss", "void", "push", "settled"].includes(status);
}

export function LedgerSection({
  betsResult,
  equityResult,
}: {
  betsResult: EndpointResult<Bet[]>;
  equityResult: EndpointResult<Equity>;
}) {
  const bets = Array.isArray(betsResult.data) ? betsResult.data : [];
  const equity = equityResult.data;
  const currency = "HKD";

  const staked = bets.reduce((total, bet) => total + (asNumber(bet.stake) ?? 0), 0);
  const settledProfit = bets.reduce((total, bet) => {
    const profit = asNumber(bet.profit);
    return total + (profit ?? 0);
  }, 0);
  const openCount = bets.filter((bet) => isOpen(bet.status)).length;
  const settledCount = bets.filter(isSettled).length;
  const netTone = profitTone(settledProfit);
  const betsUnavailable = Boolean(betsResult.error);
  const observations = Array.isArray(equity?.points)
    ? equity.points.filter((point) => point.t).length
    : 0;

  return (
    <section id="paper-ledger" className="section" aria-labelledby="paper-ledger-title">
      <SectionHeader
        index="03"
        kicker="Paper account"
        title="Paper Ledger"
        meta={
          betsResult.error || equityResult.error
            ? "ledger unavailable"
            : `${bets.length} ${bets.length === 1 ? "bet" : "bets"} · ${formatMoney(
                equity?.initial,
                currency,
              )} opening`
        }
      />

      {equityResult.error ? (
        <DataWarning label="Equity" endpoint="/dashboard/equity" error={equityResult.error} />
      ) : null}
      {betsResult.error ? (
        <DataWarning label="Bets" endpoint="/dashboard/bets?limit=100" error={betsResult.error} />
      ) : null}

      <Panel
        title="Equity curve"
        kicker="Bankroll over time"
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
        />
      </Panel>

      <div className="ledger-summary" role="group" aria-label="Derived ledger totals">
        <div className="ledger-summary__item">
          <span>Stake in window</span>
          <b>{betsUnavailable || bets.length === 0 ? "—" : formatMoney(staked, currency)}</b>
        </div>
        <div className="ledger-summary__item">
          <span>Realised P/L</span>
          <b className={`text-${netTone}`}>
            {betsUnavailable || bets.length === 0 ? "—" : formatSignedMoney(settledProfit, currency)}
          </b>
        </div>
        <div className="ledger-summary__item">
          <span>Open</span>
          <b>{betsUnavailable ? "—" : formatNumber(openCount)}</b>
        </div>
        <div className="ledger-summary__item">
          <span>Settled</span>
          <b>{betsUnavailable ? "—" : formatNumber(settledCount)}</b>
        </div>
      </div>

      <Panel
        title="Bet ledger"
        kicker="Placed and settled paper bets"
        meta={betsResult.error ? "bets unavailable" : `${bets.length} rows · newest first`}
        bodyClassName="panel__body--flush"
      >
        {bets.length === 0 ? (
          <EmptyState>
            {betsResult.error
              ? "Bet rows could not be loaded."
              : "No paper bets have been placed yet. The ledger is intentionally empty."}
          </EmptyState>
        ) : (
          <TableFrame label="Paper bet ledger" wide>
            <table className="table--bets">
              <caption className="sr-only">
                Paper bet ledger including stake, settlement profit, closing-line value and
                Brier score
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
                {bets.map((bet, index) => {
                  const profit = asNumber(bet.profit);
                  const tone = profitTone(profit);
                  return (
                    <tr key={bet.bet_id ?? `bet-${index}`}>
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
                        {bet.decision_slot_key ? (
                          <span className="subline mono">{bet.decision_slot_key}</span>
                        ) : null}
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
