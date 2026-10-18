import { Check, LineChart, X } from "lucide-react";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { Note } from "@/components/ui/Note";
import { StatusPill, type StatusVariant } from "@/components/ui/StatusPill";
import { TermTip } from "@/components/ui/TermTip";
import { champion1x2, clvMetrics, clvNotes } from "@/lib/clv";
import {
  formatCount,
  formatDateTime,
  formatDecimal,
  formatHkd,
  formatPercent,
  formatSignedPercent,
} from "@/lib/format";
import type { GlossaryKey } from "@/lib/glossary";
import type { ClvCriterion, ClvGate, ClvSummary, ModelVersion } from "@/lib/types";

// The KpiTile anatomy (DESIGN.md 5): overline label over an H1 tabular numeral.
function Metric({
  label,
  value,
  hint,
}: {
  label: ReactNode;
  value: string;
  hint?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 bg-surface-base px-4 py-4">
      <dt className="text-overline uppercase text-text-tertiary">{label}</dt>
      <dd className="flex flex-col gap-1">
        <span className="tnum text-h1 font-semibold text-text-primary">{value}</span>
        {hint === undefined ? null : (
          <span className="text-caption text-text-tertiary">{hint}</span>
        )}
      </dd>
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

function ciText(
  ci: [number, number] | null,
  format: (value: number) => string,
): string | null {
  if (ci === null) return null;
  return `95% CI ${format(ci[0])}–${format(ci[1])}`;
}

const GATE_VARIANT: Record<ClvGate["verdict"], StatusVariant> = {
  pass: "success",
  fail: "failed",
  collecting: "queued",
};

const CRITERION_TERM: Record<string, GlossaryKey> = {
  clv_n: "clv_n",
  clv_fraction: "clv_fraction",
  clv_wilson_lower: "clv_fraction",
  roi_real: "roi",
  roi_ci_lower: "roi",
  n_settled_bets: "settled",
  calibration_logloss: "logloss",
  calibration_brier: "brier",
};

function criterionValue(key: string, value: number | null): string {
  if (value === null) return "—";
  if (key === "clv_n" || key === "n_settled_bets") return formatCount(value);
  if (key === "roi_real" || key === "roi_ci_lower") return formatSignedPercent(value);
  if (key === "clv_fraction" || key === "clv_wilson_lower") return formatPercent(value);
  return formatDecimal(value);
}

function CriterionRow({ criterion }: { criterion: ClvCriterion }) {
  const term = CRITERION_TERM[criterion.key];
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption">
      <span className="min-w-0 flex-1 truncate text-text-secondary">
        {term === undefined ? criterion.key : <TermTip term={term}>{criterion.key}</TermTip>}
      </span>
      <span
        className={`inline-flex items-center gap-1 ${
          criterion.passed ? "text-accent-mint" : "text-status-neg"
        }`}
      >
        {criterion.passed ? (
          <Check className="size-3" aria-hidden />
        ) : (
          <X className="size-3" aria-hidden />
        )}
        {criterion.passed ? "pass" : "fail"}
      </span>
      <span className="tnum text-text-tertiary">
        actual {criterionValue(criterion.key, criterion.actual)}
      </span>
      <span className="tnum text-text-tertiary">
        required {criterionValue(criterion.key, criterion.required)}
      </span>
    </li>
  );
}

function GatePanel({ gate }: { gate: ClvGate }) {
  return (
    <section
      aria-label="Stop/go gate"
      className="flex flex-col gap-3 rounded-lg border border-border-default bg-surface-base px-4 py-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-h3 font-semibold text-text-primary">Stop/go gate</h3>
        <span aria-label={`gate verdict ${gate.verdict}`}>
          <StatusPill variant={GATE_VARIANT[gate.verdict]} label={gate.verdict} />
        </span>
      </div>
      <p className="text-caption text-text-tertiary">
        ready <span className="tnum text-text-secondary">{gate.ready ? "yes" : "no"}</span> ·{" "}
        <span className="tnum text-text-secondary">{formatCount(gate.days_remaining)}</span>{" "}
        day(s) remaining ·{" "}
        <span className="tnum text-text-secondary">{formatCount(gate.days_elapsed)}</span>{" "}
        elapsed
      </p>
      <ul className="flex flex-col gap-1">
        {gate.criteria.map((criterion) => (
          <CriterionRow key={criterion.key} criterion={criterion} />
        ))}
      </ul>
    </section>
  );
}

function LiveClvCard({ summary }: { summary: ClvSummary }) {
  const beatCi = ciText(summary.beat_ci95, (value) => formatPercent(value));
  const edgeCi = ciText(summary.mean_edge_ci95, (value) => formatSignedPercent(value));
  const roiCi = ciText(summary.roi_real_ci95, (value) => formatSignedPercent(value));
  const hkjcCount = summary.source_counts.hkjc ?? 0;
  const footballDataCount = summary.source_counts.football_data ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-body text-text-secondary">
        Live CLV (HKJC close) · n ={" "}
        <span className="tnum text-text-primary">{formatCount(summary.n)}</span> · fallback ={" "}
        <span className="tnum text-text-primary">{formatCount(summary.fallback)}</span>
      </p>

      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border-default bg-border-hairline md:grid-cols-5">
        <Metric
          label={<TermTip term="clv_n">CLV n</TermTip>}
          value={formatCount(summary.n)}
          hint="observations, not bets"
        />
        <Metric
          label={<TermTip term="clv_fraction">CLV beat</TermTip>}
          value={
            summary.beat_fraction === null ? "—" : formatPercent(summary.beat_fraction)
          }
          hint={beatCi ?? "95% CI unavailable"}
        />
        <Metric
          label={<TermTip term="clv_mean_edge">CLV mean edge</TermTip>}
          value={summary.mean_edge === null ? "—" : formatSignedPercent(summary.mean_edge)}
          hint={edgeCi ?? "95% CI unavailable"}
        />
        <Metric
          label={<TermTip term="brier">Brier</TermTip>}
          value={
            summary.calibration.model_brier === null
              ? "—"
              : formatDecimal(summary.calibration.model_brier)
          }
          hint={`market ${
            summary.calibration.market_brier === null
              ? "—"
              : formatDecimal(summary.calibration.market_brier)
          }`}
        />
        <Metric
          label={<TermTip term="logloss">Logloss</TermTip>}
          value={
            summary.calibration.model_logloss === null
              ? "—"
              : formatDecimal(summary.calibration.model_logloss)
          }
          hint={`market ${
            summary.calibration.market_logloss === null
              ? "—"
              : formatDecimal(summary.calibration.market_logloss)
          }`}
        />
      </dl>

      <div className="flex flex-col gap-1 text-caption text-text-tertiary">
        <p>
          Value bets: <TermTip term="clv_n">n</TermTip>{" "}
          <span className="tnum text-text-secondary">{formatCount(summary.value.n)}</span> ·{" "}
          <TermTip term="clv_fraction">beat</TermTip>{" "}
          <span className="tnum text-text-secondary">
            {summary.value.beat_fraction === null
              ? "—"
              : formatPercent(summary.value.beat_fraction)}
          </span>{" "}
          · <TermTip term="clv_mean_edge">mean edge</TermTip>{" "}
          <span className="tnum text-text-secondary">
            {summary.value.mean_edge === null
              ? "—"
              : formatSignedPercent(summary.value.mean_edge)}
          </span>
        </p>
        <p>
          Sources: HKJC <span className="tnum text-text-secondary">{formatCount(hkjcCount)}</span>{" "}
          · football-data fallback{" "}
          <span className="tnum text-text-secondary">{formatCount(footballDataCount)}</span>
        </p>
        <p>
          <TermTip term="roi">ROI</TermTip>{" "}
          <span className="tnum text-text-secondary">
            {summary.roi_real === null ? "—" : formatSignedPercent(summary.roi_real)}
          </span>
          {roiCi === null ? null : ` (${roiCi})`} ·{" "}
          <TermTip term="settled">settled bets</TermTip>{" "}
          <span className="tnum text-text-secondary">
            {formatCount(summary.n_settled_bets)}
          </span>{" "}
          · staked{" "}
          <span className="tnum text-text-secondary">{formatHkd(summary.settled_stakes)}</span>
        </p>
      </div>

      <GatePanel gate={summary.gate} />

      <Note>
        CLV here is the model probability against the closing de-vigged probability — not
        execution-versus-close, and not profit. The stop/go gate needs 200–500 observations
        and a positive ROI before it can pass.
      </Note>
    </div>
  );
}

export interface ClvCardProps {
  models: ModelVersion[] | null;
  summary: ClvSummary | null;
}

export function ClvCard({ models, summary }: ClvCardProps) {
  if (summary !== null) {
    return <LiveClvCard summary={summary} />;
  }

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
      <div className="flex flex-col gap-2">
        {clvNotes(metrics).map((note) => (
          <Note key={note}>{note}</Note>
        ))}
      </div>
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border-default bg-border-hairline md:grid-cols-5">
        <Metric
          label={<TermTip term="clv_mean_edge">CLV mean edge</TermTip>}
          value={metrics.clvMeanEdge === null ? "—" : formatSignedPercent(metrics.clvMeanEdge)}
        />
        <Metric
          label={<TermTip term="clv_fraction">CLV fraction</TermTip>}
          value={metrics.clvFraction === null ? "—" : formatPercent(metrics.clvFraction)}
        />
        <Metric
          label={<TermTip term="clv_n">CLV n</TermTip>}
          value={metrics.clvN === null ? "—" : formatCount(metrics.clvN)}
        />
        <Metric
          label={<TermTip term="brier">Brier</TermTip>}
          value={metrics.brier === null ? "—" : formatDecimal(metrics.brier)}
        />
        <Metric
          label={<TermTip term="logloss">Logloss</TermTip>}
          value={metrics.logloss === null ? "—" : formatDecimal(metrics.logloss)}
        />
      </dl>
      <ChampionLine model={champion} />
    </div>
  );
}
