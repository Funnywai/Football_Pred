import "server-only";

import {
  getAgentBets,
  getAgentDecisions,
  getAgentEquityCurve,
  getAgentSummary,
} from "./api";
import { agentVariantAgent } from "./agent-variant";
import { newestPageOffset, sortBetsNewestFirst, type BetsWindow } from "./bets-window";
import type {
  AgentDecision,
  AgentVariant,
  BetSummary,
  EquityPoint,
} from "./types";

export const AGENT_BETS_PAGE_SIZE = 50;
export const AGENT_DECISIONS_LIMIT = 100;

export interface AgentLedgerData {
  variant: AgentVariant;
  summary: BetSummary | null;
  equity: EquityPoint[] | null;
  bets: BetsWindow | null;
}

export interface AgentDecisionsData {
  variant: AgentVariant;
  decisions: AgentDecision[] | null;
}

/**
 * Fetch the agent paper book (summary, equity, bets) for Ledger > Agent. Every source
 * degrades to `null` so the page renders an explicit unavailable state instead of failing
 * the request or the production build. Decisions are deliberately not loaded here: they
 * live on `/agent`, so neither view pays for the other's fetch.
 * The bets window uses `/agent/summary.n_bets` to locate the newest page, exactly like the
 * ledger tables: the API returns bets oldest-first.
 */
export async function loadAgentLedgerData(
  variant: AgentVariant = "a_only",
): Promise<AgentLedgerData> {
  const [summary, equity] = await Promise.all([
    getAgentSummary(variant),
    getAgentEquityCurve(variant),
  ]);

  const bets = await loadAgentBetsWindow(
    summary.ok ? summary.data.n_bets : null,
    variant,
  );

  return {
    variant,
    summary: summary.ok ? summary.data : null,
    equity: equity.ok ? equity.data : null,
    bets,
  };
}

/** Fetch the decision audit only, filtered to the agent that produced the variant. */
export async function loadAgentDecisionsData(
  variant: AgentVariant = "a_only",
): Promise<AgentDecisionsData> {
  const decisions = await getAgentDecisions(
    AGENT_DECISIONS_LIMIT,
    agentVariantAgent(variant),
  );
  return {
    variant,
    decisions: decisions.ok ? decisions.data : null,
  };
}

async function loadAgentBetsWindow(
  nBets: number | null,
  variant: AgentVariant,
): Promise<BetsWindow | null> {
  const offset = nBets === null ? 0 : newestPageOffset(nBets, AGENT_BETS_PAGE_SIZE);
  const result = await getAgentBets(AGENT_BETS_PAGE_SIZE, offset, variant);
  if (!result.ok) return null;
  return {
    rows: sortBetsNewestFirst(result.data),
    total: nBets,
    newestFirst: nBets !== null,
  };
}
