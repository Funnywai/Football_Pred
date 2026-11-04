import type { Metadata } from "next";
import Link from "next/link";

import { LlmAgentWorkflow } from "@/components/llm-agent-workflow";
import { LlmOverviewSection } from "@/components/llm-overview-section";
import { TableFrame } from "@/components/table-frame";
import {
  EmptyState,
  Panel,
  SectionHeader,
  StatusTag,
} from "@/components/ui";
import { formatDateTime, formatNumber } from "@/lib/format";
import { getLlmStatus } from "@/lib/llm-api";
import type {
  LlmAgent,
  LlmCounts,
  LlmStatus,
  LlmWeight,
} from "@/lib/llm-types";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export const metadata: Metadata = {
  title: "LLM Ensemble Lab — Touchline/Lab",
  description:
    "Separate research lane for the LLM football forecasting ensemble: lane overview, next fixtures, animated agent workflow, initial weights, prediction output and paper ledger.",
};

const NAV_ITEMS = [
  { href: "#llm-overview", label: "Overview", index: "01" },
  { href: "#llm-workflow", label: "Agent workflow", index: "02" },
  { href: "#llm-weights", label: "Weights", index: "03" },
  { href: "#llm-output", label: "Output", index: "04" },
];

function countOrDash(value: number | null | undefined): string {
  return typeof value === "number" ? formatNumber(value) : "—";
}

function weightValue(weight: LlmWeight): string {
  if (typeof weight.weight === "string" && weight.weight.trim()) {
    return weight.weight.trim();
  }
  if (typeof weight.weight === "number" && Number.isFinite(weight.weight)) {
    return weight.weight.toFixed(4);
  }
  return "—";
}

function agentName(agents: LlmAgent[], agentId: string | null | undefined): string {
  if (!agentId) return "unknown agent";
  const match = agents.find((agent) => agent.agent_id === agentId);
  return match?.name?.trim() || agentId;
}

export default async function LlmLabPage() {
  const result = await getLlmStatus();
  const data: LlmStatus | null = result.data;
  const counts: LlmCounts | null | undefined = data?.counts;
  const generatedAt = data?.generated_at ?? null;

  const agents = Array.isArray(data?.agents) ? data.agents : [];
  const weights = Array.isArray(data?.weights) ? data.weights : [];
  const predictions = counts?.predictions;
  const paperBets = counts?.paper_bets;

  return (
    <div className="shell llm-shell">
      <header className="llm-masthead">
        <div className="llm-masthead__brand">
          <p className="llm-masthead__kicker">
            Football prediction research · separate lane
          </p>
          <h1 className="llm-wordmark">
            LLM<span className="llm-wordmark__slash">/</span>
            <span className="llm-wordmark__lab">LAB</span>
          </h1>
          <p className="llm-wordmark__sub">Ensemble research instrumentation</p>
          <p className="llm-masthead__tagline">
            A read-only operations floor for the LLM decision layer: lane overview,
            declared agent workflow, initial weights and prediction output, kept
            separate from the deterministic football system.
          </p>
        </div>

        <div className="llm-masthead__side">
          <Link className="llm-back" href="/">
            ← Back to TOUCHLINE/LAB
          </Link>
          <span className="llm-stamp">Separate lane · paper only</span>
          <p className="llm-generated">
            <span className="llm-generated__label">
              {result.error ? "Snapshot degraded" : "Snapshot generated"}
            </span>
            {generatedAt ? (
              <time dateTime={generatedAt}>{formatDateTime(generatedAt)}</time>
            ) : (
              <span>time unavailable</span>
            )}
            <span className="llm-generated__tz">HKT</span>
          </p>
        </div>
      </header>

      <nav className="llm-nav" aria-label="LLM Lab sections">
        <ul className="llm-nav__list">
          {NAV_ITEMS.map((item) => (
            <li key={item.href}>
              <a href={item.href} className="llm-nav__link">
                <span className="llm-nav__index" aria-hidden="true">
                  {item.index}
                </span>
                {item.label}
              </a>
            </li>
          ))}
        </ul>
        <p className="llm-nav__meta">
          <span className="llm-nav__pulse" aria-hidden="true" />
          server frame · /llm/status
        </p>
      </nav>

      <main id="main" className="main llm-main">
        <LlmOverviewSection result={result} />

        <LlmAgentWorkflow agents={agents} agentRuns={counts?.agent_runs} />

        <section
          id="llm-weights"
          className="section"
          aria-labelledby="weight-ledger-title"
        >
          <SectionHeader
            index="03"
            kicker="Initial prior"
            title="Weight ledger"
            meta={weights.length > 0 ? `${weights.length} rows` : "no weights"}
          />

          <Panel
            title="Agent weights"
            kicker="Not trained"
            meta={weights.length > 0 ? "initial prior" : "no rows"}
            bodyClassName={weights.length > 0 ? "panel__body--flush" : ""}
          >
            {weights.length === 0 ? (
              <EmptyState>
                No weight rows were returned. Weights are not inferred from the
                agent roster.
              </EmptyState>
            ) : (
              <>
                <p className="llm-table-note">
                  These are initial equal weights, not learned weights. Every row
                  reports zero samples and a <code>not trained</code> status until
                  settled results exist.
                </p>
                <TableFrame label="LLM agent weight ledger">
                  <table className="table--llm-weights">
                    <caption className="sr-only">
                      Initial agent weights with sample counts and training status
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Agent</th>
                        <th scope="col" className="num">
                          Weight
                        </th>
                        <th scope="col" className="num">
                          Samples
                        </th>
                        <th scope="col">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {weights.map((weight, index) => (
                        <tr key={`${weight.agent_id ?? "weight"}-${index}`}>
                          <td>
                            <span className="llm-weight">
                              <span className="llm-weight__name">
                                {agentName(agents, weight.agent_id)}
                              </span>
                              <span className="llm-weight__id">
                                {weight.agent_id ?? "—"}
                              </span>
                            </span>
                          </td>
                          <td className="num">{weightValue(weight)}</td>
                          <td className="num">{formatNumber(weight.sample_count)}</td>
                          <td>
                            <StatusTag
                              status={weight.status ?? null}
                              tone={weight.status === "not_trained" ? "muted" : undefined}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableFrame>
              </>
            )}
          </Panel>
        </section>

        <section
          id="llm-output"
          className="section"
          aria-labelledby="output-ledger-title"
        >
          <SectionHeader
            index="04"
            kicker="Separate paper lane"
            title="Output ledger"
            meta="separate paper lane"
          />

          <div className="llm-split">
            <Panel
              title="Predictions"
              kicker="Decision layer"
              meta={`${countOrDash(predictions)} rows`}
            >
              {typeof predictions === "number" && predictions > 0 ? (
                <p className="panel__note">
                  {formatNumber(predictions)} predictions are recorded. Row-level
                  predictions are not exposed by <code>/llm/status</code> yet, so
                  none are listed here.
                </p>
              ) : (
                <EmptyState>
                  No LLM predictions have been persisted yet. Once the provider
                  is enabled, the T-28m pre-kickoff job will write frozen evidence,
                  agent runs, a deterministic ensemble prediction and the EV/Kelly
                  paper-bet decision.
                </EmptyState>
              )}
            </Panel>

            <Panel
              title="Paper bets"
              kicker="Separate ledger"
              meta={`${countOrDash(paperBets)} rows`}
            >
              {typeof paperBets === "number" && paperBets > 0 ? (
                <p className="panel__note">
                  {formatNumber(paperBets)} paper bets are recorded. Row-level bets
                  are not exposed by <code>/llm/status</code> yet, so none are
                  listed here.
                </p>
              ) : (
                <EmptyState>
                  No LLM paper bets have been placed yet. This experiment has an
                  independent bankroll and applies the deterministic EV/Kelly,
                  odds-freshness and risk gates after each ensemble prediction.
                </EmptyState>
              )}
            </Panel>
          </div>
        </section>
      </main>

      <footer className="site-footer llm-footer">
        <p>
          <span className="site-footer__mark">LLM/LAB</span> — separate research
          lane. Paper only; no real wagers are placed.
        </p>
        <p className="site-footer__meta">
          Server-rendered · API read server-side only ·{" "}
          <Link className="llm-footer__link" href="/">
            deterministic dashboard
          </Link>{" "}
          · {generatedAt ? `snapshot ${formatDateTime(generatedAt)}` : "no snapshot time"}
        </p>
      </footer>
    </div>
  );
}
