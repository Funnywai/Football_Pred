import { Inbox } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { RollingNumber } from "@/components/ui/RollingNumber";
import { formatCount, formatHkd, formatPercent } from "@/lib/format";
import { bankrollBullet, breakevenBullet, winRateFrom, type WinRate } from "@/lib/kpi";
import type { Bet, BetSummary } from "@/lib/types";

import { KpiTile } from "./KpiTile";

export interface KpiStripProps {
  summary: BetSummary | null;
  bets: Bet[] | null;
}

export function KpiStrip({ summary, bets }: KpiStripProps) {
  if (summary === null) {
    return (
      <EmptyState
        icon={Inbox}
        title="KPI data unavailable"
        detail="the API did not return /bets/summary"
      />
    );
  }

  const winRate = bets === null ? null : winRateFrom(bets);
  const profitPositive = summary.realized_profit >= 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border-default bg-border-hairline md:grid-cols-4 xl:grid-cols-7">
        <KpiTile
          label="Bankroll"
          value={<RollingNumber value={summary.bankroll} format="hkd" />}
          bullet={bankrollBullet(summary.bankroll, summary.initial_bankroll)}
          bulletLabel={`Bankroll ${formatHkd(summary.bankroll)} against initial ${formatHkd(summary.initial_bankroll)}`}
          hint={`initial ${formatHkd(summary.initial_bankroll)}`}
        />
        <KpiTile
          label="Realised"
          value={<RollingNumber value={summary.realized_profit} format="signed-hkd" />}
          trend={profitPositive ? "up" : "down"}
        />
        <KpiTile
          label="ROI"
          value={<RollingNumber value={summary.roi} format="percent" />}
          bullet={breakevenBullet(summary.roi)}
          bulletLabel={`ROI ${formatPercent(summary.roi)} against breakeven`}
          hint="vs settled stakes"
        />
        <KpiTile
          label="Yield"
          value={<RollingNumber value={summary.yield_pct} format="percent" />}
          bullet={breakevenBullet(summary.yield_pct)}
          bulletLabel={`Yield ${formatPercent(summary.yield_pct)} against breakeven`}
          hint="vs total stakes"
        />
        <KpiTile
          label="Open stakes"
          value={<RollingNumber value={summary.open_stakes} format="hkd" />}
          hint={`${formatCount(summary.n_open)} open`}
        />
        <KpiTile
          label="Bets"
          value={<RollingNumber value={summary.n_bets} format="count" />}
          hint={`${formatCount(summary.n_settled)} settled`}
        />
        <KpiTile
          label="Win rate"
          value={
            winRate === null || winRate.rate === null ? (
              "—"
            ) : (
              <RollingNumber value={winRate.rate} format="percent" />
            )
          }
          hint={winRateHint(winRate)}
        />
      </div>
      <KpiTableFallback summary={summary} winRate={winRate} />
    </div>
  );
}

function winRateHint(winRate: WinRate | null): string {
  if (winRate === null) return "no settled bets";
  if (winRate.rate === null) return "no decided bets";
  return `${winRate.wins}W / ${winRate.losses}L · ${winRate.pushes} push excluded`;
}

function KpiTableFallback({ summary, winRate }: { summary: BetSummary; winRate: WinRate | null }) {
  const rows: Array<[string, string]> = [
    ["Bankroll", formatHkd(summary.bankroll)],
    ["Initial bankroll", formatHkd(summary.initial_bankroll)],
    ["Realised profit", formatHkd(summary.realized_profit)],
    ["ROI", formatPercent(summary.roi)],
    ["Yield", formatPercent(summary.yield_pct)],
    ["Open stakes", formatHkd(summary.open_stakes)],
    ["Bets", formatCount(summary.n_bets)],
    ["Settled", formatCount(summary.n_settled)],
    ["Win rate", winRate === null || winRate.rate === null ? "—" : formatPercent(winRate.rate)],
  ];
  return (
    <details className="text-caption text-text-tertiary">
      <summary className="cursor-pointer select-none">table view</summary>
      <table className="mt-2 w-full border-collapse text-data">
        <caption className="sr-only">KPI strip values</caption>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label} className="border-b border-border-hairline">
              <th scope="row" className="py-1 text-left font-normal text-text-secondary">
                {label}
              </th>
              <td className="py-1 text-right tnum text-text-primary">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
