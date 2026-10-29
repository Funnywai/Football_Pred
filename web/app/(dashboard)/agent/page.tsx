import { Bot } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { AgentVariantTabs } from "@/components/agent/AgentVariantTabs";
import { AgentDecisionsTable } from "@/components/tables/AgentDecisionsTable";
import { Panel } from "@/components/ui/Panel";
import { RefreshOnInterval } from "@/components/ui/RefreshOnInterval";
import { AGENT_DECISIONS_LIMIT, loadAgentDecisionsData } from "@/lib/agent-data";
import { agentVariantAgent, normalizeAgentVariant } from "@/lib/agent-variant";

export const metadata: Metadata = {
  title: "Agent · Football_Pred Mission Control",
};

function Source({ children }: { children: ReactNode }) {
  return (
    <span className="text-caption text-text-tertiary">
      source <span className="tnum text-text-secondary">{children}</span>
    </span>
  );
}

export default async function AgentPage({
  searchParams,
}: {
  searchParams?: Promise<{ variant?: string }>;
}) {
  const params: { variant?: string } = searchParams ? await searchParams : {};
  const variant = normalizeAgentVariant(params.variant);
  const agentFilter = agentVariantAgent(variant);
  const data = await loadAgentDecisionsData(variant);

  return (
    <div role="tabpanel" aria-labelledby="tab-agent" className="flex flex-col gap-6">
      <RefreshOnInterval />
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-h1 font-semibold text-text-primary">Agent</h1>
          <p className="mt-1 text-body text-text-secondary">
            {variant === "abc"
              ? "A + B + C decision audit — the gates behind the paper book."
              : "The deterministic risk agent's decision audit — the gates behind the paper book."}
          </p>
        </div>
        <AgentVariantTabs variant={variant} />
      </div>

      <p className="flex items-start gap-2 rounded-lg border border-status-warn bg-surface-base px-4 py-3 text-body text-text-secondary">
        <Bot className="mt-0.5 size-4 shrink-0 text-status-warn" aria-hidden />
        <span>
          Agent decisions are paper only. Production bankroll and the shadow ledger are
          unchanged.
        </span>
      </p>

      <p className="text-body text-text-secondary">
        The {variant === "abc" ? "A+B+C" : "A-only"} paper book — KPIs, equity curve and
        bets — lives in the Ledger.{" "}
        <Link
          href={`/ledger?view=agent&variant=${variant}`}
          className="text-accent-signal underline decoration-accent-signal underline-offset-4"
        >
          Open the {variant === "abc" ? "A+B+C" : "A-only"} paper book
        </Link>
        .
      </p>

      <Panel
        id="agent-decisions"
        title="Agent decisions"
        action={
          <Source>
            {`/agent/decisions?agent=${agentFilter}&limit=${AGENT_DECISIONS_LIMIT}`}
          </Source>
        }
      >
        <AgentDecisionsTable
          decisions={data.decisions}
          limit={AGENT_DECISIONS_LIMIT}
        />
      </Panel>
    </div>
  );
}
