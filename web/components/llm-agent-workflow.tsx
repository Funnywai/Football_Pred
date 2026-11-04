import { formatNumber, type Tone } from "@/lib/format";
import type { LlmAgent } from "@/lib/llm-types";

import { AGENT_GLYPHS, AgentSprite, type AgentGlyph } from "./llm-agent-sprite";
import { EmptyState, SectionHeader, StatusTag } from "./ui";

const SPECIALIST_IDS = [
  "market_agent",
  "form_agent",
  "tactical_agent",
  "availability_agent",
  "context_agent",
  "base_rate_agent",
] as const;

const RAIL_STAGES = [
  { index: "01", label: "Signal desk", detail: "specialists" },
  { index: "02", label: "Challenge + synthesis", detail: "red team → judge" },
  { index: "03", label: "Pool + risk gate", detail: "weights → guardrail" },
];

interface RunState {
  mode: "standby" | "recorded" | "unknown";
  tag: string;
  tone: Tone;
  headline: string;
  detail: string;
}

function runState(agentRuns: number | null | undefined): RunState {
  if (agentRuns === 0) {
    return {
      mode: "standby",
      tag: "standby",
      tone: "muted",
      headline: "STANDBY — awaiting next trigger",
      detail:
        "The floor is idle. Ambient sprite motion is a readiness signal only; no agent has executed in this snapshot, and per-agent run counts are not exposed by /llm/status.",
    };
  }
  if (typeof agentRuns === "number" && agentRuns > 0) {
    return {
      mode: "recorded",
      tag: "runs recorded",
      tone: "accent",
      headline: `${formatNumber(agentRuns)} agent runs recorded`,
      detail:
        "The snapshot records runs, but /llm/status does not break them down per agent, so no individual agent is marked active. The floor shows the declared order, not a per-agent live trace.",
    };
  }
  return {
    mode: "unknown",
    tag: "run count unknown",
    tone: "neutral",
    headline: "Run count unavailable",
    detail:
      "The snapshot does not report agent runs. The floor stays on standby and no individual agent is marked active.",
  };
}

function findAgent(agents: LlmAgent[], agentId: string): LlmAgent | null {
  return agents.find((agent) => agent.agent_id === agentId) ?? null;
}

function glyphFor(agent: LlmAgent | null): AgentGlyph {
  if (!agent?.agent_id) return "generic";
  return AGENT_GLYPHS[agent.agent_id] ?? "generic";
}

function agentName(agent: LlmAgent): string {
  return agent.name?.trim() || agent.agent_id || "Unnamed agent";
}

function agentScope(agent: LlmAgent): string {
  return agent.scope?.trim() || "No scope was supplied.";
}

function agentKind(agent: LlmAgent): string {
  return agent.kind?.trim() || "unclassified";
}

function agentPhase(agent: LlmAgent): string {
  return agent.phase?.trim() || "—";
}

function AgentDesk({
  agent,
  index,
}: {
  agent: LlmAgent;
  index: number;
}) {
  return (
    <div className="llm-desk">
      <AgentSprite glyph={glyphFor(agent)} index={index} />
      <div className="llm-desk__text">
        <h4 className="llm-desk__name">{agentName(agent)}</h4>
        <p className="llm-desk__scope">{agentScope(agent)}</p>
        <p className="llm-desk__meta">
          <span className="llm-desk__kind">{agentKind(agent)}</span>
          <span aria-hidden="true">·</span>
          <span>{agentPhase(agent)}</span>
        </p>
      </div>
    </div>
  );
}

function AgentUnit({
  agent,
  index,
}: {
  agent: LlmAgent;
  index: number;
}) {
  return (
    <div className="llm-unit">
      <AgentSprite glyph={glyphFor(agent)} index={index} />
      <div className="llm-unit__text">
        <h4 className="llm-unit__name">{agentName(agent)}</h4>
        <p className="llm-unit__scope">{agentScope(agent)}</p>
        <p className="llm-unit__meta">
          <span className="llm-desk__kind">{agentKind(agent)}</span>
          <span aria-hidden="true">·</span>
          <span>{agentPhase(agent)}</span>
        </p>
      </div>
    </div>
  );
}

function PoolUnit() {
  return (
    <div className="llm-unit llm-unit--pool">
      <span className="llm-pool" aria-hidden="true">
        <span className="llm-pool__bars">
          <i />
          <i />
          <i />
        </span>
        <span className="llm-pool__sigma">Σ</span>
      </span>
      <div className="llm-unit__text">
        <h4 className="llm-unit__name">Deterministic weighted pool</h4>
        <p className="llm-unit__scope">
          Combines agent votes with the declared weight ledger and sets the final
          H/D/A probabilities.
        </p>
        <p className="llm-unit__meta">
          <span className="llm-desk__kind">deterministic</span>
          <span aria-hidden="true">·</span>
          <span>not an LLM agent</span>
        </p>
      </div>
    </div>
  );
}

export function LlmAgentWorkflow({
  agents,
  agentRuns,
}: {
  agents: LlmAgent[];
  agentRuns: number | null | undefined;
}) {
  const state = runState(agentRuns);
  const preferredSpecialists = SPECIALIST_IDS.map((agentId) =>
    findAgent(agents, agentId),
  ).filter((agent): agent is LlmAgent => agent !== null);
  const knownSpecialistIds = new Set<string>(SPECIALIST_IDS);
  const extraSpecialists = agents.filter(
    (agent) =>
      (agent.kind ?? "").toLowerCase() === "specialist" &&
      Boolean(agent.agent_id) &&
      !knownSpecialistIds.has(agent.agent_id ?? ""),
  );
  const specialists = [...preferredSpecialists, ...extraSpecialists];
  const redTeam = findAgent(agents, "red_team_agent");
  const judge = findAgent(agents, "judge_agent");
  const risk = findAgent(agents, "risk_agent");

  return (
    <section
      id="llm-workflow"
      className="section llm-workflow"
      data-run-state={state.mode}
      aria-labelledby="agent-workflow-title"
    >
      <SectionHeader
        index="02"
        kicker="Operations floor"
        title="Agent workflow"
        meta={
          agents.length > 0 ? `${agents.length} declared agents · ${state.tag}` : "roster unavailable"
        }
      />

      {agents.length === 0 ? (
        <EmptyState>
          No agent roster was returned. The workflow is shown only when the LLM lane
          exposes its declared roles; no placeholder agents are drawn.
        </EmptyState>
      ) : (
        <>
          <div className="llm-workflow-status">
            <div className="llm-workflow-status__state">
              <StatusTag status={state.tag} tone={state.tone} />
              <span className="llm-workflow-status__headline">{state.headline}</span>
            </div>
            <p className="llm-workflow-status__detail">{state.detail}</p>
          </div>

          <div className="llm-rail" aria-hidden="true">
            <span className="llm-rail__line" />
            <div className="llm-rail__nodes">
              {RAIL_STAGES.map((stage) => (
                <span className="llm-rail__node" key={stage.index}>
                  <span className="llm-rail__dot" />
                  <span className="llm-rail__id">{stage.index}</span>
                  <span className="llm-rail__label">
                    {stage.label}
                    <span className="llm-rail__detail">{stage.detail}</span>
                  </span>
                </span>
              ))}
            </div>
          </div>

          <div className="llm-floor">
            <div className="llm-stage llm-stage--signal">
              <header className="llm-stage__head">
                <p className="llm-stage__step">Stage 01</p>
                <h3 className="llm-stage__title">Signal desk</h3>
                <p className="llm-stage__caption">
                  {specialists.length} specialists · parallel evidence reads
                </p>
              </header>

              {specialists.length === 0 ? (
                <p className="llm-stage__empty">
                  No specialist desks were returned in the declared roster.
                </p>
              ) : (
                <div className="llm-desks">
                  {specialists.map((agent, index) => (
                    <AgentDesk agent={agent} index={index} key={agent.agent_id ?? index} />
                  ))}
                </div>
              )}
            </div>

            <div className="llm-stage llm-stage--challenge">
              <header className="llm-stage__head">
                <p className="llm-stage__step">Stage 02</p>
                <h3 className="llm-stage__title">Challenge + synthesis</h3>
                <p className="llm-stage__caption">advisory only · no final probabilities</p>
              </header>

              <div className="llm-stage__flow">
                {redTeam ? <AgentUnit agent={redTeam} index={6} /> : null}
                {judge ? <AgentUnit agent={judge} index={7} /> : null}
                {!redTeam && !judge ? (
                  <p className="llm-stage__empty">
                    No challenge or synthesis roles were returned in the declared
                    roster.
                  </p>
                ) : null}
              </div>
            </div>

            <div className="llm-stage llm-stage--gate">
              <header className="llm-stage__head">
                <p className="llm-stage__step">Stage 03</p>
                <h3 className="llm-stage__title">Pool + risk gate</h3>
                <p className="llm-stage__caption">final probabilities set here</p>
              </header>

              <div className="llm-stage__flow">
                <PoolUnit />
                {risk ? <AgentUnit agent={risk} index={8} /> : null}
                {!risk ? (
                  <p className="llm-stage__empty">
                    No risk-guardrail agent was returned in the declared roster.
                  </p>
                ) : null}
              </div>
            </div>
          </div>

          <p className="llm-note llm-floor__note">
            Fixed order: specialists → red team → judge → deterministic weighted pool →
            risk guardrail. The judge synthesizes disagreement and advice but does not
            set final probabilities; the deterministic pool does, before the risk
            guardrail can block a paper bet.
          </p>
        </>
      )}
    </section>
  );
}
