import { Info, LineChart } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { champion1x2, clvMetrics, clvNotes } from "@/lib/clv";
import {
  formatCount,
  formatDateTime,
  formatDecimal,
  formatPercent,
  formatSignedPercent,
} from "@/lib/format";
import type { ModelVersion } from "@/lib/types";

// The KpiTile anatomy (DESIGN.md 5): overline label over an H1 tabular numeral.
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-2 bg-surface-base px-4 py-4">
      <dt className="text-overline uppercase text-text-tertiary">{label}</dt>
      <dd className="tnum text-h1 font-semibold text-text-primary">{value}</dd>
    </div>
  );
}

function ChampionLine({ model }: { model: ModelVersion }) {
  return (
    <p className="text-caption text-text-tertiary">
      champion <span className="tnum text-text-secondary">#{model.id}</span> · target{" "}
      <span className="tnum text-text-secondary">{model.target}</span> · algorithm{" "}
      <span className="tnum text-text-secondary">{model.algorithm}</span> · promoted{" "}
      <span className="tnum text-text-secondary">{formatDateTime(model.promoted_at)}</span>
    </p>
  );
}

export interface ClvCardProps {
  models: ModelVersion[] | null;
}

export function ClvCard({ models }: ClvCardProps) {
  if (models === null) {
    return (
      <EmptyState
        icon={LineChart}
        title="CLV unavailable"
        detail="the API did not return /models"
      />
    );
  }

  const champion = champion1x2(models);
  if (champion === null) {
    return (
      <EmptyState
        icon={LineChart}
        title="No champion 1x2 version"
        detail="the model registry has no champion for the 1x2 target"
      />
    );
  }

  const metrics = clvMetrics(champion);
  if (metrics === null) {
    return (
      <div className="flex flex-col gap-4">
        <ChampionLine model={champion} />
        <EmptyState
          icon={LineChart}
          title="No metrics reported"
          detail="the champion 1x2 version has no metrics yet"
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border-default bg-border-hairline md:grid-cols-5">
        <Metric
          label="CLV mean edge"
          value={metrics.clvMeanEdge === null ? "—" : formatSignedPercent(metrics.clvMeanEdge)}
        />
        <Metric
          label="CLV fraction"
          value={metrics.clvFraction === null ? "—" : formatPercent(metrics.clvFraction)}
        />
        <Metric
          label="CLV n"
          value={metrics.clvN === null ? "—" : formatCount(metrics.clvN)}
        />
        <Metric label="Brier" value={metrics.brier === null ? "—" : formatDecimal(metrics.brier)} />
        <Metric
          label="Logloss"
          value={metrics.logloss === null ? "—" : formatDecimal(metrics.logloss)}
        />
      </dl>
      <ChampionLine model={champion} />
      <ul className="flex flex-col gap-2">
        {clvNotes(metrics).map((note) => (
          <li key={note} className="flex items-start gap-2 text-body text-text-secondary">
            <Info className="mt-0.5 size-3 shrink-0 text-text-tertiary" aria-hidden />
            <span>{note}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
