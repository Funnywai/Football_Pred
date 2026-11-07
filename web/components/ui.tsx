import type { ReactNode } from "react";

import { statusTone, type Tone } from "@/lib/format";

export function Panel({
  title,
  kicker,
  meta,
  children,
  className = "",
  bodyClassName = "",
}: {
  title: string;
  kicker?: string;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`panel ${className}`.trim()}>
      <header className="panel__head">
        <div>
          {kicker ? <p className="panel__kicker">{kicker}</p> : null}
          <h3 className="panel__title">{title}</h3>
        </div>
        {meta ? <div className="panel__meta">{meta}</div> : null}
      </header>
      <div className={`panel__body ${bodyClassName}`.trim()}>{children}</div>
    </section>
  );
}

export function DataWarning({
  label,
  endpoint,
  error,
}: {
  label: string;
  endpoint: string;
  error: string;
}) {
  return (
    <div className="alert" role="status">
      <span className="alert__tag">degraded</span>
      <div>
        <p className="alert__title">{label} unavailable</p>
        <p className="alert__body">
          <code>{endpoint}</code> — {error}
        </p>
      </div>
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="empty" role="status">
      <span className="empty__mark" aria-hidden="true">
        ∅
      </span>
      <p>{children}</p>
    </div>
  );
}

export function HealthPill({
  label,
  state,
}: {
  label: string;
  state: string | null | undefined;
}) {
  const tone = statusTone(state);
  const normalized = state?.trim() ? state : "unknown";
  return (
    <span className={`health health--${tone}`}>
      <span className="health__dot" aria-hidden="true" />
      <span className="health__label">{label}</span>
      <span className="health__state">{normalized.replaceAll("_", " ")}</span>
    </span>
  );
}

export function StatusTag({
  status,
  tone,
}: {
  status: string | null | undefined;
  tone?: Tone;
}) {
  const resolved = tone ?? statusTone(status);
  const text = status?.trim() ? status.replaceAll("_", " ") : "unknown";
  return <span className={`tag tag--${resolved}`}>{text}</span>;
}

export function SectionHeader({
  index,
  kicker,
  title,
  meta,
}: {
  index: string;
  kicker: string;
  title: string;
  meta?: ReactNode;
}) {
  const headingId = `${title.toLowerCase().replaceAll(" ", "-")}-title`;
  return (
    <div className="section__head">
      <span className="section__index" aria-hidden="true">
        {index}
      </span>
      <div className="section__heading">
        <p className="section__kicker">{kicker}</p>
        <h2 className="section__title" id={headingId}>
          {title}
        </h2>
      </div>
      {meta ? <div className="section__meta">{meta}</div> : null}
    </div>
  );
}

export function MatchCell({
  home,
  away,
  competition,
  matchId,
}: {
  home: string | null | undefined;
  away: string | null | undefined;
  competition?: string | null;
  matchId?: string | null;
}) {
  const homeLabel = home?.trim() || "TBD";
  const awayLabel = away?.trim() || "TBD";
  const meta = [competition?.trim(), matchId ? matchId.slice(-8) : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="match">
      <span className="match__teams">
        <span>{homeLabel}</span>
        <span>
          <span className="match__vs" aria-hidden="true">
            v&nbsp;
          </span>
          {awayLabel}
        </span>
      </span>
      {meta ? <span className="match__meta">{meta}</span> : null}
    </div>
  );
}

export function JsonDetails({
  label,
  value,
}: {
  label: string;
  value: unknown;
}) {
  if (value === null || value === undefined) return null;
  let rendered: string;
  try {
    rendered = JSON.stringify(value, null, 2);
  } catch {
    return null;
  }
  if (!rendered || rendered === "{}" || rendered === "[]") return null;
  return (
    <details className="json">
      <summary>{label}</summary>
      <pre>{rendered}</pre>
    </details>
  );
}

export function Metric({
  label,
  value,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: ReactNode;
  tone?: Tone;
  hint?: ReactNode;
}) {
  return (
    <div className="metric">
      <span className="metric__label">{label}</span>
      <span className={`metric__value metric__value--${tone}`}>{value}</span>
      {hint ? <span className="metric__hint">{hint}</span> : null}
    </div>
  );
}
