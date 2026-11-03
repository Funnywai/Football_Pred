import type { Metadata } from "next";
import Link from "next/link";

import { TableFrame } from "@/components/table-frame";
import {
  DataWarning,
  EmptyState,
  Panel,
  SectionHeader,
  StatusTag,
} from "@/components/ui";
import { formatDateTime, formatNumber, humanize, type Tone } from "@/lib/format";
import { getLlmStatus } from "@/lib/llm-api";
import type {
  LlmAgent,
  LlmCounts,
  LlmPrompt,
  LlmSafety,
  LlmSeparation,
  LlmStatus,
  LlmWeight,
} from "@/lib/llm-types";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export const metadata: Metadata = {
  title: "LLM Ensemble Lab — Touchline/Lab",
  description:
    "Separate research lane for the LLM football forecasting ensemble: safety constraints, declared agents, initial weights and content-addressed prompts.",
};

const NAV_ITEMS = [
  { href: "#llm-separation", label: "Separation", index: "01" },
  { href: "#llm-status", label: "Safety & status", index: "02" },
  { href: "#llm-roster", label: "Agents", index: "03" },
  { href: "#llm-weights", label: "Weights", index: "04" },
  { href: "#llm-prompts", label: "Prompts", index: "05" },
  { href: "#llm-output", label: "Output", index: "06" },
  { href: "#llm-boundary", label: "Boundary", index: "07" },
];

const FALLBACK_SEPARATION: LlmSeparation[] = [
  {
    lane: "deterministic",
    label: "Football_Pred",
    detail: "Data ingestion, quality gates, poisson-v1, g1 paper ledger.",
  },
  {
    lane: "llm",
    label: "LLM Ensemble Lab",
    detail: "LLM agents, weighted aggregation, separate paper ledger.",
  },
];

interface SafetyRow {
  key: string;
  label: string;
  detail: string;
  expected: boolean;
  actual: boolean | null | undefined;
  state: string;
  tone: Tone;
}

function safetyRow(
  key: string,
  label: string,
  detail: string,
  actual: boolean | null | undefined,
  expected: boolean,
): SafetyRow {
  if (actual === null || actual === undefined) {
    return {
      key,
      label,
      detail,
      expected,
      actual,
      state: "unconfirmed",
      tone: "muted",
    };
  }

  if (actual === expected) {
    return {
      key,
      label,
      detail,
      expected,
      actual,
      state: expected ? "enforced" : "blocked",
      tone: "positive",
    };
  }

  return {
    key,
    label,
    detail,
    expected,
    actual,
    state: "violation",
    tone: "negative",
  };
}

function safetyRows(safety: LlmSafety | null | undefined): SafetyRow[] {
  return [
    safetyRow(
      "paper",
      "Paper only",
      "No real wagers are placed from this lane.",
      safety?.paper_only,
      true,
    ),
    safetyRow(
      "money",
      "No real money",
      "Real-money settlement stays disabled.",
      safety?.real_money,
      false,
    ),
    safetyRow(
      "writes",
      "No DB writes",
      "LLM agents cannot write to the database.",
      safety?.llm_may_write_database,
      false,
    ),
    safetyRow(
      "settle",
      "No settlement",
      "LLM agents cannot settle paper bets.",
      safety?.llm_may_settle,
      false,
    ),
  ];
}

function countOrDash(value: number | null | undefined): string {
  return typeof value === "number" ? formatNumber(value) : "—";
}

function shortHash(hash: string | null | undefined): string {
  const trimmed = hash?.trim();
  if (!trimmed) return "—";
  return trimmed.length <= 12 ? trimmed : `${trimmed.slice(0, 12)}…`;
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

function executionLabel(agentRuns: number | null | undefined): string {
  if (agentRuns === 0) return "not executed";
  if (agentRuns === null || agentRuns === undefined) return "run count unknown";
  return "runs not exposed per agent";
}

export default async function LlmLabPage() {
  const result = await getLlmStatus();
  const data: LlmStatus | null = result.data;
  const counts: LlmCounts | null | undefined = data?.counts;
  const generatedAt = data?.generated_at ?? null;

  const agents = Array.isArray(data?.agents) ? data.agents : [];
  const weights = Array.isArray(data?.weights) ? data.weights : [];
  const prompts = Array.isArray(data?.prompts) ? data.prompts : [];
  const separation =
    Array.isArray(data?.separation) && data.separation.length > 0
      ? data.separation
      : FALLBACK_SEPARATION;

  const agentCount = counts?.agents ?? (agents.length > 0 ? agents.length : null);
  const promptCount = counts?.prompts ?? (prompts.length > 0 ? prompts.length : null);
  const predictions = counts?.predictions;
  const paperBets = counts?.paper_bets;
  const evidencePackets = counts?.evidence_packets;

  const runtime = data?.runtime;
  const safety = safetyRows(data?.safety);

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
            A read-only view of the LLM decision layer: declared agents, initial
            weights, content-addressed prompts and the boundary that keeps it
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
        {result.error ? (
          <DataWarning label="LLM status" endpoint="/llm/status" error={result.error} />
        ) : null}

        {!data ? (
          <EmptyState>
            {result.error
              ? "No LLM status snapshot could be loaded. Resolve the API connection shown above; this page will not invent roster, weight or prompt values."
              : "The LLM status endpoint returned no payload. The lane may still be starting up."}
          </EmptyState>
        ) : null}

        <section
          id="llm-separation"
          className="section"
          aria-labelledby="lane-separation-title"
        >
          <SectionHeader
            index="01"
            kicker="Two planes, one repository"
            title="Lane separation"
            meta={data ? "read-only boundary" : "snapshot unavailable"}
          />

          <div className="llm-lanes">
            {separation.map((lane, index) => {
              const isLlmLane = lane.lane === "llm";
              return (
                <article
                  key={`${lane.lane ?? "lane"}-${index}`}
                  className={`llm-lane${isLlmLane ? " llm-lane--focus" : ""}`}
                >
                  <div className="llm-lane__top">
                    <span className="llm-lane__index" aria-hidden="true">
                      L{index + 1}
                    </span>
                    <span className={`tag ${isLlmLane ? "tag--accent" : "tag--muted"}`}>
                      {humanize(lane.lane, "lane")}
                    </span>
                  </div>
                  <h3 className="llm-lane__title">{lane.label ?? "Unnamed lane"}</h3>
                  <p className="llm-lane__detail">
                    {lane.detail ?? "No lane detail was returned."}
                  </p>
                </article>
              );
            })}
          </div>

          <p className="llm-note">
            The deterministic plane owns ingestion, quality gates, model
            probabilities and the existing paper ledger. The LLM lane only reads
            deterministic snapshots; its prediction output is isolated from the
            deterministic decision path and its paper ledger has not been opened.
          </p>
        </section>

        <section
          id="llm-status"
          className="section"
          aria-labelledby="safety-and-status-title"
        >
          <SectionHeader
            index="02"
            kicker="Runtime and guardrails"
            title="Safety and status"
            meta={data ? `phase ${data.phase ?? "unknown"}` : "snapshot unavailable"}
          />

          <div className="llm-block">
            <h3 className="llm-subhead">
              Safety constraints
              <span>derived from /llm/status</span>
            </h3>
            <ul className="llm-safety" aria-label="LLM lane safety constraints">
              {safety.map((item) => (
                <li
                  key={item.key}
                  className={`llm-safety__item llm-safety__item--${item.tone}`}
                >
                  <span className="llm-safety__label">{item.label}</span>
                  <span className="llm-safety__detail">{item.detail}</span>
                  <span className="llm-safety__state">
                    <span className="llm-safety__dot" aria-hidden="true" />
                    {item.state}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="llm-block">
            <h3 className="llm-subhead">
              Runtime counts
              <span>{data ? "server snapshot" : "unverified"}</span>
            </h3>
            <dl className="llm-kpis" aria-label="LLM Lab runtime counts">
              <div className="llm-kpi">
                <dt>Phase</dt>
                <dd>{data?.phase?.trim() || "—"}</dd>
                <span className="llm-kpi__hint">runtime phase</span>
              </div>
              <div className="llm-kpi">
                <dt>Agents</dt>
                <dd>{countOrDash(agentCount)}</dd>
                <span className="llm-kpi__hint">declared roster</span>
              </div>
              <div className="llm-kpi">
                <dt>Prompts</dt>
                <dd>{countOrDash(promptCount)}</dd>
                <span className="llm-kpi__hint">content-addressed</span>
              </div>
              <div className="llm-kpi">
                <dt>Evidence</dt>
                <dd>{countOrDash(evidencePackets)}</dd>
                <span className="llm-kpi__hint">packets frozen</span>
              </div>
              <div className="llm-kpi">
                <dt>Predictions</dt>
                <dd>{countOrDash(predictions)}</dd>
                <span className="llm-kpi__hint">decision layer off</span>
              </div>
              <div className="llm-kpi">
                <dt>Paper bets</dt>
                <dd>{countOrDash(paperBets)}</dd>
                <span className="llm-kpi__hint">separate ledger</span>
              </div>
            </dl>

            <dl className="llm-runtime" aria-label="LLM runtime layers">
              <div>
                <dt>Decision layer</dt>
                <dd>
                  <StatusTag
                    status={runtime?.decision_layer ?? null}
                    tone={runtime?.decision_layer ? "muted" : undefined}
                  />
                </dd>
              </div>
              <div>
                <dt>Data plane</dt>
                <dd>
                  <StatusTag status={runtime?.data_plane ?? null} tone="neutral" />
                </dd>
              </div>
              <div>
                <dt>Paper ledger</dt>
                <dd>
                  <StatusTag
                    status={runtime?.paper_ledger ?? null}
                    tone={runtime?.paper_ledger ? "muted" : undefined}
                  />
                </dd>
              </div>
            </dl>
          </div>
        </section>

        <section
          id="llm-roster"
          className="section"
          aria-labelledby="agent-roster-title"
        >
          <SectionHeader
            index="03"
            kicker="Declared ensemble"
            title="Agent roster"
            meta={
              agents.length > 0
                ? `${agents.length} agents · ${executionLabel(counts?.agent_runs)}`
                : "roster unavailable"
            }
          />

          {agents.length === 0 ? (
            <EmptyState>
              No agent roster was returned. The LLM lane may not have loaded its
              declared roles yet; no placeholder agents are shown.
            </EmptyState>
          ) : (
            <>
              <ul className="llm-agents">
                {agents.map((agent, index) => (
                  <li className="llm-agent" key={agent.agent_id ?? `agent-${index}`}>
                    <div className="llm-agent__head">
                      <span className="llm-agent__index" aria-hidden="true">
                        A{String(index + 1).padStart(2, "0")}
                      </span>
                      <h3 className="llm-agent__name">
                        {agent.name?.trim() || agent.agent_id || "Unnamed agent"}
                      </h3>
                      <span className="llm-agent__kind">
                        <StatusTag status={agent.kind ?? null} tone="neutral" />
                      </span>
                    </div>
                    <p className="llm-agent__scope">
                      {agent.scope?.trim() || "No scope was supplied."}
                    </p>
                    <dl className="llm-agent__meta">
                      <div>
                        <dt>Phase</dt>
                        <dd>{agent.phase?.trim() || "—"}</dd>
                      </div>
                      <div>
                        <dt>Execution</dt>
                        <dd>{executionLabel(counts?.agent_runs)}</dd>
                      </div>
                    </dl>
                  </li>
                ))}
              </ul>
              <p className="llm-note">
                This roster is declarative. No agent is marked active: execution
                status is read from the API and the current phase has no runs.
              </p>
            </>
          )}
        </section>

        <section
          id="llm-weights"
          className="section"
          aria-labelledby="weight-ledger-title"
        >
          <SectionHeader
            index="04"
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
          id="llm-prompts"
          className="section"
          aria-labelledby="prompt-registry-title"
        >
          <SectionHeader
            index="05"
            kicker="Content-addressed"
            title="Prompt registry"
            meta={prompts.length > 0 ? `${prompts.length} prompts` : "no prompts"}
          />

          <Panel
            title="Registered prompts"
            kicker="Frozen text"
            meta="SHA-256 · bytes"
            bodyClassName={prompts.length > 0 ? "panel__body--flush" : ""}
          >
            {prompts.length === 0 ? (
              <EmptyState>
                No prompts were returned. The registry does not render inferred
                prompt names.
              </EmptyState>
            ) : (
              <>
                <p className="llm-table-note">
                  Prompts are versioned by the SHA-256 hash of their content. Any
                  text change produces a new hash, so a run can be traced back to
                  the exact prompt bytes.
                </p>
                <TableFrame label="LLM prompt registry">
                  <table className="table--llm-prompts">
                    <caption className="sr-only">
                      Registered prompts with content hash prefix and byte size
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Prompt</th>
                        <th scope="col">SHA-256 prefix</th>
                        <th scope="col" className="num">
                          Bytes
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {prompts.map((prompt: LlmPrompt, index) => {
                        const hash = prompt.sha256?.trim() || "";
                        return (
                          <tr key={`${prompt.name ?? "prompt"}-${index}`}>
                            <td>
                              <span className="llm-prompt__name">
                                {prompt.name?.trim() || "unnamed"}
                              </span>
                              <span className="llm-prompt__meta">
                                versioned by content
                              </span>
                            </td>
                            <td>
                              <code
                                className="llm-hash"
                                title={hash ? `SHA-256 ${hash}` : undefined}
                              >
                                {shortHash(hash)}
                              </code>
                            </td>
                            <td className="num">{formatNumber(prompt.bytes)}</td>
                          </tr>
                        );
                      })}
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
            index="06"
            kicker="Nothing produced yet"
            title="Output ledger"
            meta="prediction-only lane"
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
                  is enabled, the T-30m job will write frozen evidence, agent
                  runs and a deterministic ensemble prediction.
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
                  No paper bets yet. Phase 3 will apply deterministic risk gates
                  and open a separate LLM paper ledger; it is not connected and
                  cannot settle.
                </EmptyState>
              )}
            </Panel>
          </div>
        </section>

        <section
          id="llm-boundary"
          className="section"
          aria-labelledby="boundary-model-title"
        >
          <SectionHeader
            index="07"
            kicker="Ownership and limits"
            title="Boundary model"
            meta="deterministic owns the money path"
          />

          <ol className="llm-flow" aria-label="LLM decision flow">
            <li className="llm-flow__step">
              <span className="llm-flow__index" aria-hidden="true">
                01
              </span>
              <p className="llm-flow__title">Deterministic data plane</p>
              <p className="llm-flow__body">
                Ingestion, quality gates and point-in-time snapshots. The LLM lane
                may read this output but cannot write it.
              </p>
              <span className="llm-flow__lane">owned by Football_Pred</span>
            </li>
            <li className="llm-flow__step">
              <span className="llm-flow__index" aria-hidden="true">
                02
              </span>
              <p className="llm-flow__title">LLM agent ensemble</p>
              <p className="llm-flow__body">
                Specialists, red team and judge produce probabilities from frozen
                evidence packets and content-addressed prompts.
              </p>
              <span className="llm-flow__lane">advisory output only</span>
            </li>
            <li className="llm-flow__step">
              <span className="llm-flow__index" aria-hidden="true">
                03
              </span>
              <p className="llm-flow__title">Deterministic aggregation + risk</p>
              <p className="llm-flow__body">
                Weighted aggregation and hard risk gates stay in deterministic
                code. No agent can override a limit.
              </p>
              <span className="llm-flow__lane">owned by deterministic layer</span>
            </li>
            <li className="llm-flow__step">
              <span className="llm-flow__index" aria-hidden="true">
                04
              </span>
              <p className="llm-flow__title">Separate paper ledger</p>
              <p className="llm-flow__body">
                A separate <code>llm_paper</code> account records paper bets and
                settlement. It is not the existing g1 ledger.
              </p>
              <span className="llm-flow__lane">not opened yet</span>
            </li>
          </ol>

          <div className="llm-split">
            <Panel
              title="Read-only inputs"
              kicker="Allowed"
              meta="deterministic snapshots"
            >
              <ul className="llm-rules">
                <li>
                  Fixtures, results, odds and source metadata from the
                  deterministic plane.
                </li>
                <li>Frozen evidence packets captured before decision time.</li>
                <li>Content-addressed prompts and versioned agent weights.</li>
              </ul>
            </Panel>

            <Panel
              title="Forbidden actions"
              kicker="Blocked"
              meta="LLM lane"
            >
              <ul className="llm-rules llm-rules--blocked">
                <li>Writing to the deterministic database.</li>
                <li>Placing real-money wagers or settling the paper ledger.</li>
                <li>Overriding risk gates or the deterministic aggregation step.</li>
              </ul>
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
