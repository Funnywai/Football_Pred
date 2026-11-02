import { asNumber, formatKickoff, formatMoney } from "@/lib/format";
import type { Equity } from "@/lib/types";

import { EmptyState } from "./ui";

interface PlotPoint {
  t: string | null;
  value: number;
}

const WIDTH = 960;
const HEIGHT = 260;
const PAD = { top: 18, right: 18, bottom: 30, left: 78 };

function buildPlot(equity: Equity | null): {
  plot: PlotPoint[];
  initial: number | null;
  min: number;
  max: number;
} | null {
  const rawPoints = Array.isArray(equity?.points) ? equity.points : [];
  const plot = rawPoints
    .map((point) => ({ t: point.t ?? null, value: asNumber(point.bankroll) }))
    .filter((point): point is PlotPoint => point.value !== null);
  if (plot.length === 0) return null;

  const initial = asNumber(equity?.initial);
  const values = plot.map((point) => point.value);
  if (initial !== null) values.push(initial);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const span = rawMax - rawMin;
  const padding = span === 0 ? Math.max(Math.abs(rawMax) * 0.01, 1) : span * 0.12;

  return {
    plot,
    initial,
    min: rawMin - padding,
    max: rawMax + padding,
  };
}

export function EquityChart({
  equity,
  currency,
  unavailable = false,
}: {
  equity: Equity | null;
  currency: string;
  unavailable?: boolean;
}) {
  const built = buildPlot(equity);
  if (!built) {
    return (
      <EmptyState>
        {unavailable
          ? "Equity data could not be loaded. See the error above."
          : "No settled bets yet — the equity curve starts after the first settlement."}
      </EmptyState>
    );
  }

  const { plot, initial, min, max } = built;
  const chartWidth = WIDTH - PAD.left - PAD.right;
  const chartHeight = HEIGHT - PAD.top - PAD.bottom;
  const x = (index: number) =>
    PAD.left + (plot.length === 1 ? chartWidth / 2 : (index / (plot.length - 1)) * chartWidth);
  const y = (value: number) =>
    PAD.top + ((max - value) / Math.max(max - min, 0.0001)) * chartHeight;

  const line = plot.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const first = plot[0];
  const last = plot[plot.length - 1];
  if (!first || !last) return <EmptyState>No equity points recorded yet.</EmptyState>;

  const area = `${PAD.left},${PAD.top + chartHeight} ${line} ${x(plot.length - 1)},${
    PAD.top + chartHeight
  }`;
  const gridValues = [0, 0.25, 0.5, 0.75, 1].map((fraction) => max - fraction * (max - min));
  const change = last.value - (initial ?? first.value);

  return (
    <figure className="equity">
      <svg
        className="equity__svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`Paper bankroll equity curve from ${formatMoney(
          initial ?? first.value,
          currency,
        )} to ${formatMoney(last.value, currency)} across ${plot.length} points`}
      >
        <title>Paper bankroll equity curve</title>
        <defs>
          <linearGradient id="equity-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" className="equity__fill-start" />
            <stop offset="100%" className="equity__fill-end" />
          </linearGradient>
        </defs>

        {gridValues.map((value, index) => {
          const lineY = y(value);
          return (
            <g key={`grid-${index}`}>
              <line
                x1={PAD.left}
                y1={lineY}
                x2={WIDTH - PAD.right}
                y2={lineY}
                className="equity__grid"
              />
              <text x={PAD.left - 10} y={lineY + 3.5} textAnchor="end" className="equity__axis">
                {formatMoney(value, currency).replace(/\.00$/, "")}
              </text>
            </g>
          );
        })}

        {initial !== null && initial >= min && initial <= max ? (
          <g>
            <line
              x1={PAD.left}
              y1={y(initial)}
              x2={WIDTH - PAD.right}
              y2={y(initial)}
              className="equity__baseline"
            />
            <text x={WIDTH - PAD.right} y={y(initial) - 6} textAnchor="end" className="equity__note">
              initial
            </text>
          </g>
        ) : null}

        <polygon points={area} fill="url(#equity-area)" />
        <polyline points={line} className="equity__line" />
        <circle cx={x(plot.length - 1)} cy={y(last.value)} r="3.5" className="equity__dot" />

        <text x={PAD.left} y={HEIGHT - 8} className="equity__axis">
          {formatKickoff(first.t)}
        </text>
        <text x={WIDTH - PAD.right} y={HEIGHT - 8} textAnchor="end" className="equity__axis">
          {formatKickoff(last.t)}
        </text>
      </svg>

      <figcaption className="equity__caption">
        <span>
          Current <b>{formatMoney(last.value, currency)}</b>
        </span>
        <span>
          Peak <b>{formatMoney(Math.max(...plot.map((point) => point.value)), currency)}</b>
        </span>
        <span>
          Trough <b>{formatMoney(Math.min(...plot.map((point) => point.value)), currency)}</b>
        </span>
        <span>
          Window <b>{`${formatKickoff(first.t)} → ${formatKickoff(last.t)}`}</b>
        </span>
        <span>
          Change{" "}
          <b className={change > 0 ? "text-positive" : change < 0 ? "text-negative" : ""}>
            {change > 0 ? "+" : change < 0 ? "−" : ""}
            {formatMoney(Math.abs(change), currency)}
          </b>
        </span>
        <span className="equity__points">{plot.length} points</span>
      </figcaption>
    </figure>
  );
}
