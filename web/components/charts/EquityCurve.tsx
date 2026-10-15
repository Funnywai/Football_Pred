import { LineChart } from "lucide-react";

import { ChartTableFallback } from "@/components/charts/ChartTableFallback";
import { EmptyState } from "@/components/ui/EmptyState";
import { equityModel } from "@/lib/equity";
import { formatDateTime, formatHkd } from "@/lib/format";
import type { EquityPoint } from "@/lib/types";

const WIDTH = 720;
const HEIGHT = 240;
const PAD = 24;

export interface EquityCurveProps {
  points: EquityPoint[] | null;
}

export function EquityCurve({ points }: EquityCurveProps) {
  if (points === null) {
    return (
      <EmptyState
        icon={LineChart}
        title="Equity curve unavailable"
        detail="the API did not return /bets/equity-curve"
      />
    );
  }
  if (points.length < 2) {
    return (
      <EmptyState
        icon={LineChart}
        title="No equity points yet"
        detail="the curve appears once the first bet settles"
      />
    );
  }

  const model = equityModel(points);
  const values = points.map((point) => point.bankroll);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const flat = max === min;
  const plotW = WIDTH - PAD * 2;
  const plotH = HEIGHT - PAD * 2;
  const lastIndex = points.length - 1;

  const xFor = (index: number) => PAD + (index / lastIndex) * plotW;
  const yFor = (value: number) =>
    flat ? PAD + plotH / 2 : PAD + (1 - (value - min) / (max - min)) * plotH;
  const coordAt = (index: number) => {
    const point = points[index];
    if (point === undefined) return { x: PAD, y: PAD };
    return { x: xFor(index), y: yFor(point.bankroll) };
  };

  const mainPath = Array.from({ length: lastIndex }, (_, index) => {
    const { x, y } = coordAt(index);
    return `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  const previous = coordAt(lastIndex - 1);
  const last = coordAt(lastIndex);
  const finalSegment = `M ${previous.x.toFixed(1)} ${previous.y.toFixed(1)} L ${last.x.toFixed(1)} ${last.y.toFixed(1)}`;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-body text-text-secondary">{model.summary}</p>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full"
        role="img"
        aria-label={`Equity curve. ${model.summary}`}
      >
        <line
          x1={PAD}
          y1={PAD + plotH}
          x2={WIDTH - PAD}
          y2={PAD + plotH}
          stroke="var(--border-hairline)"
          strokeWidth={1}
        />
        <path
          d={mainPath}
          fill="none"
          stroke="var(--accent-signal)"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <path
          key={points.length}
          d={finalSegment}
          fill="none"
          stroke="var(--accent-signal)"
          strokeWidth={2}
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray={1}
          className="draw-in"
        />
        <circle
          key={`marker-${points.length}`}
          cx={last.x}
          cy={last.y}
          r={4}
          fill="var(--accent-signal)"
          className="marker-in"
        />
      </svg>
      <ChartTableFallback
        caption="Equity curve points"
        columns={["Time", "Bankroll"]}
        rows={points.map((point) => [
          point.t === null ? "start" : formatDateTime(point.t),
          formatHkd(point.bankroll),
        ])}
      />
    </div>
  );
}
