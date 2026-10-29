import type { AgentVariant } from "./types";

/** Agent URLs use `?variant=abc`; anything else falls back to the A-only baseline. */
export function normalizeAgentVariant(value: unknown): AgentVariant {
  return value === "abc" ? "abc" : "a_only";
}

export function agentVariantAgent(variant: AgentVariant): "risk" | "decision" {
  return variant === "abc" ? "decision" : "risk";
}
