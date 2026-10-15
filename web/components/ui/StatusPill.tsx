import { AlertTriangle, Check, Clock, Hourglass, Loader2, Minus, TimerOff } from "lucide-react";
import type { ComponentType } from "react";

export type StatusVariant =
  | "running"
  | "success"
  | "failed"
  | "never-tracked"
  | "queued"
  | "ageing"
  | "stale";

interface VariantSpec {
  Icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  label: string;
  className: string;
  spin?: boolean;
}

// Colour is never the sole carrier of meaning: every variant pairs its token with a
// Lucide glyph and a text label (DESIGN.md 2.2).
const VARIANTS: Record<StatusVariant, VariantSpec> = {
  running: {
    Icon: Loader2,
    label: "running",
    className: "text-accent-signal border-accent-signal/40",
    spin: true,
  },
  success: { Icon: Check, label: "success", className: "text-accent-mint border-accent-mint/40" },
  failed: {
    Icon: AlertTriangle,
    label: "failed",
    className: "text-status-neg border-status-neg/40",
  },
  "never-tracked": {
    Icon: Minus,
    label: "never tracked",
    className: "text-text-tertiary border-border-default",
  },
  queued: { Icon: Clock, label: "queued", className: "text-status-warn border-status-warn/40" },
  ageing: { Icon: Hourglass, label: "ageing", className: "text-status-warn border-status-warn/40" },
  stale: { Icon: TimerOff, label: "stale", className: "text-status-neg border-status-neg/40" },
};

export interface StatusPillProps {
  variant: StatusVariant;
  label?: string;
  live?: boolean;
}

export function StatusPill({ variant, label, live = false }: StatusPillProps) {
  const spec = VARIANTS[variant];
  const { Icon } = spec;
  return (
    <span
      role={live ? "status" : undefined}
      className={`inline-flex items-center gap-1 rounded-pill border px-2 py-1 text-caption font-medium ${spec.className}`}
    >
      <Icon className={`size-3 ${spec.spin ? "motion-safe:animate-spin" : ""}`} aria-hidden />
      <span>{label ?? spec.label}</span>
    </span>
  );
}
