import type { BetsWindow } from "@/lib/bets-window";

import { BetsTable } from "./BetsTable";

export interface AgentBetsTableProps {
  bets: BetsWindow | null;
}

export function AgentBetsTable({ bets }: AgentBetsTableProps) {
  return <BetsTable bets={bets} copy="agent" />;
}
