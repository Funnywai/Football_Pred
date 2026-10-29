import { normalizeAgentVariant } from "./agent-variant";

/**
 * `/ledger` was folded into `/agent`. Old bookmarks must keep working, so the page is
 * redirect-only: the A+B+C variant survives when the legacy URL selected the agent view
 * (`?view=agent&variant=abc`); every other view lands on the default A-only agent page.
 */
export function legacyLedgerHref(params: { view?: unknown; variant?: unknown }): string {
  if (params.view === "agent") {
    return agentVariantHref(params.variant);
  }
  return "/agent";
}

/** `/performance` is retired too; a `?variant=abc` bookmark still reaches the A+B+C book. */
export function legacyPerformanceHref(params: { variant?: unknown }): string {
  return agentVariantHref(params.variant);
}

function agentVariantHref(variant: unknown): string {
  return normalizeAgentVariant(variant) === "abc" ? "/agent?variant=abc" : "/agent";
}
