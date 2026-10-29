import { Bot } from "lucide-react";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AgentVariantTabs } from "@/components/agent/AgentVariantTabs";
import { EquityCurve } from "@/components/charts/EquityCurve";
import { KpiStrip } from "@/components/kpi/KpiStrip";
import { AgentBetsTable } from "@/components/tables/AgentBetsTable";
import { AgentDecisionsTable } from "@/components/tables/AgentDecisionsTable";
import { Panel } from "@/components/ui/Panel";
import { RefreshOnInterval } from "@/components/ui/RefreshOnInterval";
import {
  AGENT_DECISIONS_LIMIT,
  loadAgentData,
} from "@/lib/agent-data";
import { normalizeAgentVariant } from "@/lib/agent-variant";

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
  const variantQuery = `variant=${variant}`;
  const agentFilter = variant === "abc" ? "decision" : "risk";
  const data = await loadAgentData(variant);

  return (
    <div role="tabpanel" aria-labelledby="tab-agent" className="flex flex-col gap-6">
      <RefreshOnInterval />
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-h1 font-semibold text-text-primary">Agent</h1>
          <p className="mt-1 text-body text-text-secondary">
            {variant === "abc"
              ? "A + B + C paper decisions and paper bets."
              : "The deterministic risk agent's paper decisions and paper bets."}
          </p>
        </div>
        <AgentVariantTabs variant={variant} />
      </div>

      <p className="flex items-start gap-2 rounded-lg border border-status-warn bg-surface-base px-4 py-3 text-body text-text-secondary">
        <Bot className="mt-0.5 size-4 shrink-0 text-status-warn" aria-hidden />
        <span>
          Agent paper book — paper only. Production bankroll and the shadow ledger are
          unchanged.
        </span>
      </p>

      <Panel
        id="agent-kpi-strip"
        title="Agent KPI strip"
        action={
          <Source>{`/agent/summary?${variantQuery} + /agent/bets?${variantQuery}`}</Source>
        }
      >
        <KpiStrip
          summary={data.summary}
          bets={data.bets}
          source={`/agent/summary?${variantQuery}`}
        />
      </Panel>

      <Panel
        id="agent-equity-curve"
        title="Agent equity / money curve"
        action={<Source>{`/agent/equity-curve?${variantQuery}`}</Source>}
      >
        <EquityCurve
          points={data.equity}
          source={`/agent/equity-curve?${variantQuery}`}
        />
      </Panel>

      <Panel
        id="agent-decisions"
        title="Agent decisions"
        action={<Source>{`/agent/decisions?agent=${agentFilter}&limit=${AGENT_DECISIONS_LIMIT}`}</Source>}
      >
        <AgentDecisionsTable
          decisions={data.decisions}
          limit={AGENT_DECISIONS_LIMIT}
        />
      </Panel>

      <Panel
        id="agent-bets"
        title="Agent paper bets"
        action={<Source>{`/agent/bets?${variantQuery}`}</Source>}
      >
        <AgentBetsTable bets={data.bets} />
      </Panel>
    </div>
  );
}
