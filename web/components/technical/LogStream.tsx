import { AlertTriangle, Bug, Flame, Info, Minus, ScrollText, XCircle } from "lucide-react";
import Link from "next/link";
import type { ComponentType, ReactNode } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { Note } from "@/components/ui/Note";
import { formatDateTime } from "@/lib/format";
import { LOG_LEVELS, logLevelKind, type LogLevel, type LogLevelKind } from "@/lib/logs";
import type { OpsLogLine } from "@/lib/types";

import { LogAutoRefresh } from "./LogAutoRefresh";

interface LevelSpec {
  Icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  className: string;
}

// Colour is never the sole carrier of meaning: every level pairs its token with a glyph
// and the raw level text (DESIGN.md 2.2).
const LEVEL_SPEC: Record<LogLevelKind, LevelSpec> = {
  debug: { Icon: Bug, className: "text-text-tertiary" },
  info: { Icon: Info, className: "text-status-info" },
  warning: { Icon: AlertTriangle, className: "text-status-warn" },
  error: { Icon: XCircle, className: "text-status-neg" },
  critical: { Icon: Flame, className: "text-status-neg" },
  unknown: { Icon: Minus, className: "text-text-tertiary" },
};

export interface LogStreamProps {
  logs: OpsLogLine[] | null;
  level: LogLevel | null;
  limit: number;
}

export function LogStream({ logs, level, limit }: LogStreamProps) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <nav aria-label="Log level filter" className="flex flex-wrap items-center gap-1">
          <FilterLink href="/technical" active={level === null}>
            all
          </FilterLink>
          {LOG_LEVELS.map((candidate) => (
            <FilterLink
              key={candidate}
              href={`/technical?level=${candidate}`}
              active={level === candidate}
            >
              {candidate.toLowerCase()}
            </FilterLink>
          ))}
        </nav>
        <LogAutoRefresh />
      </div>
      <Note>
        tail of the newest {limit} buffered lines (API default limit {limit}, max 500; the
        buffer is per-process and lost on restart)
        {level === null ? " · no level filter" : ` · filter: ${level} and above`}
      </Note>
      {logs === null ? (
        <EmptyState
          icon={ScrollText}
          title="Log stream unavailable"
          detail="the API did not return /ops/logs"
        />
      ) : logs.length === 0 ? (
        <EmptyState
          icon={ScrollText}
          title={
            level === null
              ? "No log lines buffered yet"
              : `No lines at or above ${level} in the buffer`
          }
        />
      ) : (
        <ol className="max-h-96 overflow-y-auto rounded-md border border-border-hairline">
          {logs.map((line, index) => (
            <LogLine key={`${line.time}-${index}`} line={line} />
          ))}
        </ol>
      )}
    </div>
  );
}

function FilterLink({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "true" : undefined}
      className={`rounded-sm px-2 py-1 text-caption transition-colors duration-150 ease-out ${
        active
          ? "text-accent-signal underline decoration-accent-signal underline-offset-4"
          : "text-text-secondary hover:text-text-primary"
      }`}
    >
      {children}
    </Link>
  );
}

function LogLine({ line }: { line: OpsLogLine }) {
  const { Icon, className } = LEVEL_SPEC[logLevelKind(line.level)];
  return (
    <li className="border-b border-border-hairline px-3 py-1 font-mono text-data transition-colors duration-150 ease-out last:border-b-0 hover:bg-surface-raised">
      <span className="tnum mr-3 text-caption text-text-tertiary">
        {formatDateTime(line.time)}
      </span>
      <span
        className={`mr-3 inline-flex items-center gap-1 text-caption font-medium ${className}`}
      >
        <Icon className="size-3" aria-hidden />
        <span>{line.level}</span>
      </span>
      <span className="mr-3 text-caption text-text-tertiary">{line.logger}</span>
      <span className="break-words text-text-secondary">{line.message}</span>
    </li>
  );
}
