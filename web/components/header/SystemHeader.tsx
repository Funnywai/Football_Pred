import { ArrowDown, ArrowUp, Database, GitCommitHorizontal, Target } from "lucide-react";

import { formatHkd, formatSignedHkd } from "@/lib/format";
import type { HeaderData } from "@/lib/header-model";

import { HeartbeatDot } from "./HeartbeatDot";
import { PipelineIndicator } from "./PipelineIndicator";

export interface SystemHeaderProps {
  data: HeaderData;
}

export function SystemHeader({ data }: SystemHeaderProps) {
  return (
    <header className="sticky top-0 z-50 border-b border-border-default bg-surface-void/95 backdrop-blur">
      <div className="mx-auto flex max-w-[var(--content-max)] flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 lg:px-6">
        <div className="flex items-center gap-2">
          <span className="size-2 rounded-pill bg-accent-signal" aria-hidden />
          <span className="text-overline uppercase text-text-secondary">Mission Control</span>
        </div>

        <MoneyGroup money={data.money} />

        <div className="hidden flex-1 lg:block" />

        <HeartbeatDot
          status={data.heartbeat.status}
          label={data.heartbeat.label}
          detail={data.heartbeat.detail}
        />
        <FreshnessIndicator freshness={data.freshness} />
        <PipelineIndicator thinking={data.thinking} />
        <BuildIdentity build={data.build} />
      </div>
    </header>
  );
}

function MoneyGroup({ money }: { money: HeaderData["money"] }) {
  if (money === null) {
    return (
      <div className="flex items-baseline gap-2">
        <span className="text-overline uppercase text-text-tertiary">bankroll</span>
        <span className="text-data text-status-neg">unavailable</span>
      </div>
    );
  }

  const positive = money.realizedProfit >= 0;
  return (
    <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
      <div className="flex items-baseline gap-2">
        <span className="text-overline uppercase text-text-tertiary">bankroll</span>
        <span className="tnum text-display font-semibold text-text-primary">
          {formatHkd(money.bankroll)}
        </span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-overline uppercase text-text-tertiary">realised</span>
        <span
          className={`tnum inline-flex items-center gap-1 text-data ${
            positive ? "text-accent-mint" : "text-status-neg"
          }`}
        >
          {positive ? (
            <ArrowUp className="size-3" aria-hidden />
          ) : (
            <ArrowDown className="size-3" aria-hidden />
          )}
          {formatSignedHkd(money.realizedProfit)}
        </span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-overline uppercase text-text-tertiary">open</span>
        <span className="tnum text-data text-text-secondary">{formatHkd(money.openStakes)}</span>
      </div>
    </div>
  );
}

function FreshnessIndicator({ freshness }: { freshness: HeaderData["freshness"] }) {
  const color =
    freshness.status === "healthy"
      ? "text-accent-mint"
      : freshness.status === "degraded"
        ? "text-status-warn"
        : "text-status-neg";
  return (
    <div
      role="status"
      aria-label={`Data freshness: ${freshness.label}. ${freshness.detail}`}
      className="flex items-center gap-2"
    >
      <Database className={`size-3.5 ${color}`} aria-hidden />
      <span className="text-caption text-text-secondary">
        data <span className={color}>{freshness.label}</span>
      </span>
      <span className="text-caption text-text-tertiary">{freshness.detail}</span>
    </div>
  );
}

function BuildIdentity({ build }: { build: HeaderData["build"] }) {
  if (build === null) {
    return (
      <div className="flex items-center gap-2 text-caption text-text-tertiary">
        <GitCommitHorizontal className="size-3.5" aria-hidden />
        <span>build unavailable</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-3">
      <span className="inline-flex items-center gap-1 text-caption text-text-secondary">
        <GitCommitHorizontal className="size-3.5 text-text-tertiary" aria-hidden />
        <span className="tnum">{build.gitSha}</span>
      </span>
      <span className="inline-flex items-center gap-1 text-caption text-text-secondary">
        <Target className="size-3.5 text-text-tertiary" aria-hidden />
        {build.championTarget === null ? (
          <span className="text-text-tertiary">no champion</span>
        ) : (
          <span className="tnum">
            {build.championTarget} · {build.championStatus}
          </span>
        )}
      </span>
    </div>
  );
}
