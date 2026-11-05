import { asNumber, formatKickoff, formatMoney } from "@/lib/format";
import type { Equity } from "@/lib/types";

import { EmptyState } from "./ui";

interface PlotPoint {
  t: string | null;
  value: number;
}

interface Series {
  key: "v1" | "v2";
  label: string;
  className: string;
  plot: PlotPoint[];
  initial: number | null;
}

const WIDTH = 960;
const HEIGHT = 260;
const PAD = { top: 18, right: 18, bottom: 30, left: 78 };

function buildSeries(
  key: "v1" | "v2",
  label: string,
  className: string,
  equity: Equity | null,
): Series | null {
  const rawPoints = Array.isArray(equity?.points) ? equity.points : [];
  const plot = rawPoints
    .map((point) => ({ t: point.t ?? null, value: asNumber(point.bankroll) }))
    .filter((point): point is PlotPoint => point.value !== null);
  if (plot.length === 0) return null;
  return {
    key,
    label,
    className,
    plot,
    initial: asNumber(equity?.initial),
  };
}

export function EquityChart({
  equity,
  challengerEquity = null,
  currency,
  unavailable = false,
  primaryLabel = "V1",
}: {
  equity: Equity | null;
  challengerEquity?: Equity | null;
  currency: string;
  unavailable?: boolean;
  primaryLabel?: string;
}) {
  const series = [
    buildSeries("v1", primaryLabel, "equity__line--v1", equity),
    buildSeries("v2", "V2", "equity__line--v2", challengerEquity),
  ].filter((item): item is Series => item !== null);

  if (series.length === 0) {
    return (
      <EmptyState>
        {unavailable
          ? "Equity data could not be loaded. See the error above."
          : "No settled bets yet — the equity curve starts after the first settlement."}
      </EmptyState>
    );
  }

  const allValues = series.flatMap((item) => [
    ...item.plot.map((point) => point.value),
    ...(item.initial !== null ? [item.initial] : []),
  ]);
  const rawMin = Math.min(...allValues);
  const rawMax = Math.max(...allValues);
  const span = rawMax - rawMin;
  const padding = span === 0 ? Math.max(Math.abs(rawMax) * 0.01, 1) : span * 0.12;
  const min = rawMin - padding;
  const max = rawMax + padding;
  const chartWidth = WIDTH - PAD.left - PAD.right;
  const chartHeight = HEIGHT - PAD.top - PAD.bottom;
  const x = (index: number, length: number) =>
    PAD.left +
    (length === 1 ? chartWidth / 2 : (index / (length - 1)) * chartWidth);
  const y = (value: number) =>
    PAD.top + ((max - value) / Math.max(max - min, 0.0001)) * chartHeight;
  const gridValues = [0, 0.25, 0.5, 0.75, 1].map((fraction) => max - fraction * (max - min));
  const primary = series.find((item) => item.key === "v1") ?? series[0];
  const first = primary?.plot[0];
  const last = primary?.plot[primary.plot.length - 1];
  if (!primary || !first || !last) return <EmptyState>No equity points recorded yet.</EmptyState>;

  const lastValues = series.map((item) => ({
    item,
    value: item.plot[item.plot.length - 1]?.value ?? null,
  }));
  const change = last.value - (primary.initial ?? first.value);
  const primarySeriesLabel = primary.label;

  return (
    <figure className="equity">
      <div className="equity__legend" aria-label="Equity series">
        {series.map((item) => (
          <span className="equity__legend-item" key={item.key}>
            <i className={`equity__swatch equity__swatch--${item.key}`} aria-hidden="true" />
            {item.label}
          </span>
        ))}
      </div>
      <svg
        className="equity__svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`Paper bankroll equity curves for ${series
          .map((item) => item.label)
          .join(" and ")} from ${formatMoney(
          primary.initial ?? first.value,
          currency,
        )} opening across ${series.reduce((count, item) => count + item.plot.length, 0)} points`}
      >
        <title>Paper bankroll equity curves</title>
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

        {primary.initial !== null && primary.initial >= min && primary.initial <= max ? (
          <g>
            <line
              x1={PAD.left}
              y1={y(primary.initial)}
              x2={WIDTH - PAD.right}
              y2={y(primary.initial)}
              className="equity__baseline"
            />
            <text
              x={WIDTH - PAD.right}
              y={y(primary.initial) - 6}
              textAnchor="end"
              className="equity__note"
            >
              {primarySeriesLabel} initial
            </text>
          </g>
        ) : null}

        {series.map((item) => {
          const itemLine = item.plot
            .map((point, index) => `${x(index, item.plot.length)},${y(point.value)}`)
            .join(" ");
          const itemLast = item.plot[item.plot.length - 1];
          if (!itemLast) return null;
          return (
            <g key={item.key}>
              {item.key === "v1" ? (
                <polygon
                  points={`${PAD.left},${PAD.top + chartHeight} ${itemLine} ${
                    x(item.plot.length - 1, item.plot.length)
                  },${PAD.top + chartHeight}`}
                  fill="url(#equity-area)"
                />
              ) : null}
              <polyline points={itemLine} className={`equity__line ${item.className}`} />
              <circle
                cx={x(item.plot.length - 1, item.plot.length)}
                cy={y(itemLast.value)}
                r="3.5"
                className={`equity__dot equity__dot--${item.key}`}
              />
            </g>
          );
        })}

        <text x={PAD.left} y={HEIGHT - 8} className="equity__axis">
          {formatKickoff(first.t)}
        </text>
        <text x={WIDTH - PAD.right} y={HEIGHT - 8} textAnchor="end" className="equity__axis">
          {formatKickoff(last.t)}
        </text>
      </svg>

      <figcaption className="equity__caption">
        {lastValues.map(({ item, value }) => (
          <span key={item.key}>
            {item.label} current <b>{value === null ? "—" : formatMoney(value, currency)}</b>
          </span>
        ))}
        <span>
          Peak <b>{formatMoney(Math.max(...allValues), currency)}</b>
        </span>
        <span>
          Trough <b>{formatMoney(Math.min(...allValues), currency)}</b>
        </span>
        <span>
          Window <b>{`${formatKickoff(first.t)} → ${formatKickoff(last.t)}`}</b>
        </span>
        <span>
          {primarySeriesLabel} change{" "}
          <b className={change > 0 ? "text-positive" : change < 0 ? "text-negative" : ""}>
            {change > 0 ? "+" : change < 0 ? "−" : ""}
            {formatMoney(Math.abs(change), currency)}
          </b>
        </span>
        <span className="equity__points">
          {series.map((item) => `${item.label} ${item.plot.length}`).join(" · ")} points
        </span>
      </figcaption>
    </figure>
  );
}
