import Link from "next/link";

import type { LedgerView } from "@/lib/ledger-view";

const VIEWS: ReadonlyArray<{ view: LedgerView; label: string; href: string }> = [
  { view: "production", label: "Production", href: "/ledger?view=production" },
  { view: "shadow", label: "Shadow", href: "/ledger?view=shadow" },
  { view: "agent", label: "Agent", href: "/ledger?view=agent" },
  { view: "clv", label: "CLV & Calibration", href: "/ledger?view=clv" },
];

export interface LedgerViewTabsProps {
  view: LedgerView;
}

const ACTIVE_INDEX: Record<LedgerView, number> = {
  production: 0,
  shadow: 1,
  agent: 2,
  clv: 3,
};

export function LedgerViewTabs({ view }: LedgerViewTabsProps) {
  const activeIndex = ACTIVE_INDEX[view];

  return (
    <nav
      aria-label="Ledger view"
      className="relative grid grid-cols-4 rounded-md border border-border-default bg-surface-base p-1"
    >
      <span
        aria-hidden
        className="absolute inset-y-1 left-1 w-[calc((100%-2*var(--space-1))/4)] rounded-sm bg-surface-raised transition-transform duration-200 ease-in-out motion-reduce:transition-none"
        style={{ transform: `translateX(${activeIndex * 100}%)` }}
      />
      {VIEWS.map((item) => {
        const active = item.view === view;
        return (
          <Link
            key={item.view}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`relative z-10 rounded-sm px-3 py-2 text-center text-data transition-colors duration-150 ease-out ${
              active
                ? "text-accent-signal"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
