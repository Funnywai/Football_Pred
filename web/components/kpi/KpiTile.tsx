import { ArrowDown, ArrowUp } from "lucide-react";
import type { ReactNode } from "react";

import type { BulletSpec } from "@/lib/kpi";

import { BulletChart } from "./BulletChart";

export interface KpiTileProps {
  label: ReactNode;
  value: ReactNode;
  trend?: "up" | "down";
  bullet?: BulletSpec;
  bulletLabel?: string;
  hint?: ReactNode;
}

export function KpiTile({ label, value, trend, bullet, bulletLabel, hint }: KpiTileProps) {
  const trendClass =
    trend === "up" ? "text-accent-mint" : trend === "down" ? "text-status-neg" : "text-text-primary";
  const bulletText = bulletLabel ?? (typeof label === "string" ? label : "KPI value");
  return (
    <div className="flex flex-col gap-2 bg-surface-base px-4 py-4">
      <span className="text-overline uppercase text-text-tertiary">{label}</span>
      <span className={`flex items-center gap-1 text-h1 font-semibold ${trendClass}`}>
        {trend === "up" ? <ArrowUp className="size-4" aria-hidden /> : null}
        {trend === "down" ? <ArrowDown className="size-4" aria-hidden /> : null}
        <span className="tnum">{value}</span>
      </span>
      {bullet === undefined ? null : (
        <BulletChart spec={bullet} label={bulletText} />
      )}
      {hint === undefined ? null : (
        <span className="text-caption text-text-tertiary">{hint}</span>
      )}
    </div>
  );
}
