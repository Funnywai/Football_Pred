import { AlertTriangle, Check, Clock, Minus, TrendingDown, TrendingUp } from "lucide-react";
import type { ComponentType } from "react";

import { betStatusKind, betStatusLabel, type BetStatusKind } from "@/lib/bets";

interface BetStatusSpec {
  Icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  className: string;
}

// Colour is never the sole carrier of meaning: every status pairs its token with a glyph
// and a text label (DESIGN.md 2.2).
const SPEC: Record<BetStatusKind, BetStatusSpec> = {
  pending: { Icon: Clock, className: "text-status-warn border-status-warn/40" },
  won: { Icon: Check, className: "text-accent-mint border-accent-mint/40" },
  lost: { Icon: AlertTriangle, className: "text-status-neg border-status-neg/40" },
  push: { Icon: Minus, className: "text-text-tertiary border-border-default" },
  "half-won": { Icon: TrendingUp, className: "text-accent-mint border-accent-mint/40" },
  "half-lost": { Icon: TrendingDown, className: "text-status-neg border-status-neg/40" },
  unknown: { Icon: Minus, className: "text-text-tertiary border-border-default" },
};

export interface BetStatusPillProps {
  status: string;
}

export function BetStatusPill({ status }: BetStatusPillProps) {
  const kind = betStatusKind(status);
  const { Icon, className } = SPEC[kind];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-pill border px-2 py-1 text-caption font-medium ${className}`}
    >
      <Icon className="size-3" aria-hidden />
      <span>{betStatusLabel(kind)}</span>
    </span>
  );
}
