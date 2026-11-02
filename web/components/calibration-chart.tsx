import { clamp, formatFixed, formatNumber } from "@/lib/format";
import { toAxisPercent, type CalibrationBin } from "@/lib/calibration";
import type { CalibrationMetric } from "@/lib/types";

const SIZE = 240;
const PAD = { top: 16, right: 14, bottom: 34, left: 46 };

export function CalibrationBinChart({
  metric,
  bins,
}: {
  metric: CalibrationMetric;
  bins: CalibrationBin[];
}) {
  const points = bins
    .map((bin) => ({
      bin,
      predicted: toAxisPercent(bin.predicted),
      observed: toAxisPercent(bin.observed),
    }))
    .filter(
      (point): point is { bin: CalibrationBin; predicted: number; observed: number } =>
        point.predicted !== null && point.observed !== null,
    );

  if (points.length === 0) return null;

  const plotW = SIZE - PAD.left - PAD.right;
  const plotH = SIZE - PAD.top - PAD.bottom;
  const px = (value: number) => PAD.left + (value / 100) * plotW;
  const py = (value: number) => PAD.top + (1 - value / 100) * plotH;
  const slice = [metric.competition, metric.market, metric.time_block]
    .filter(Boolean)
    .join(" · ");

  const summary = points
    .map(
      (point) =>
        `${point.bin.label}: predicted ${point.predicted.toFixed(0)}%, observed ${point.observed.toFixed(0)}%`,
    )
    .join("; ");

  return (
    <figure className="cal-chart">
      <div className="cal-chart__head">
        <span className="cal-chart__model">{metric.model_version ?? "model"}</span>
        <span className="cal-chart__n">n={formatNumber(metric.sample_count)}</span>
      </div>
      <p className="cal-chart__slice">{slice || "all slices"}</p>

      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="cal-chart__svg"
        role="img"
        aria-label={`Reliability plot for ${metric.model_version ?? "model"} ${
          slice || "all slices"
        }: ${summary}`}
      >
        <title>Predicted probability versus observed frequency</title>

        {[0, 25, 50, 75, 100].map((tick) => (
          <g key={`tick-${tick}`}>
            <line
              x1={px(0)}
              y1={py(tick)}
              x2={px(100)}
              y2={py(tick)}
              className="cal-chart__grid"
            />
            <line
              x1={px(tick)}
              y1={py(0)}
              x2={px(tick)}
              y2={py(100)}
              className="cal-chart__grid"
            />
          </g>
        ))}

        {[0, 50, 100].map((tick) => (
          <text
            key={`y-${tick}`}
            x={PAD.left - 6}
            y={py(tick) + 3}
            textAnchor="end"
            className="cal-chart__axis"
          >
            {tick}%
          </text>
        ))}

        <line
          x1={px(0)}
          y1={py(0)}
          x2={px(100)}
          y2={py(100)}
          className="cal-chart__diagonal"
        />

        {points.map((point, index) => {
          const count = point.bin.count;
          const radius = count
            ? clamp(2.6 + Math.log10(count + 1) * 1.7, 2.6, 7)
            : 3;
          return (
            <g key={`${point.bin.label}-${index}`}>
              <line
                x1={px(point.predicted)}
                y1={py(point.observed)}
                x2={px(point.predicted)}
                y2={py(point.predicted)}
                className="cal-chart__residual"
              />
              <circle
                cx={px(point.predicted)}
                cy={py(point.observed)}
                r={radius}
                className="cal-chart__point"
              >
                <title>
                  {`${point.bin.label} — predicted ${point.predicted.toFixed(
                    1,
                  )}%, observed ${point.observed.toFixed(1)}%, n=${formatNumber(count)}`}
                </title>
              </circle>
            </g>
          );
        })}

        <text x={PAD.left} y={SIZE - 16} className="cal-chart__axis">
          0%
        </text>
        <text x={px(50)} y={SIZE - 16} textAnchor="middle" className="cal-chart__axis">
          50% predicted
        </text>
        <text x={px(100)} y={SIZE - 16} textAnchor="end" className="cal-chart__axis">
          100%
        </text>
        <text
          x={12}
          y={py(50)}
          textAnchor="middle"
          transform={`rotate(-90 12 ${py(50)})`}
          className="cal-chart__axis"
        >
          observed
        </text>
      </svg>

      <figcaption className="cal-chart__caption">
        {bins.length} bins · brier {formatFixed(metric.brier, 3)}
      </figcaption>
    </figure>
  );
}
