import { bulletIsDegenerate, type BulletSpec } from "@/lib/kpi";

export interface BulletChartProps {
  spec: BulletSpec;
  label: string;
}

// A bullet bar: a track, a measure bar from the origin to the value, and a target tick.
// The numeral and target are always visible as text elsewhere; this bar is supplementary.
export function BulletChart({ spec, label }: BulletChartProps) {
  if (bulletIsDegenerate(spec)) return null;

  const span = spec.max - spec.min;
  const position = (value: number) => ((value - spec.min) / span) * 100;
  const originPct = position(spec.origin);
  const valuePct = position(spec.value);
  const targetPct = position(spec.target);
  const positive = spec.value >= spec.origin;

  return (
    <div
      role="img"
      aria-label={label}
      className="relative h-2 w-full overflow-hidden rounded-pill bg-surface-raised"
    >
      <span
        className={`absolute inset-y-0 rounded-pill ${positive ? "bg-accent-mint" : "bg-status-neg"}`}
        style={{ left: `${Math.min(originPct, valuePct)}%`, width: `${Math.abs(valuePct - originPct)}%` }}
      />
      <span
        aria-hidden
        className="absolute inset-y-0 w-1 bg-text-primary"
        style={{ left: `${targetPct}%` }}
      />
    </div>
  );
}
