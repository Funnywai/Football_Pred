import Link from "next/link";

import type { AgentVariant } from "@/lib/types";

const VARIANTS: ReadonlyArray<{ variant: AgentVariant; label: string; href: string }> = [
  { variant: "a_only", label: "A-only", href: "/ledger?view=agent" },
  { variant: "abc", label: "A+B+C", href: "/ledger?view=agent&variant=abc" },
];

export interface LedgerAgentVariantTabsProps {
  variant: AgentVariant;
}

export function LedgerAgentVariantTabs({ variant }: LedgerAgentVariantTabsProps) {
  const activeIndex = variant === "abc" ? 1 : 0;

  return (
    <nav
      aria-label="Agent paper book variant"
      className="relative grid grid-cols-2 rounded-md border border-border-default bg-surface-base p-1"
    >
      <span
        aria-hidden
        className="absolute inset-y-1 left-1 w-[calc(50%-var(--space-1))] rounded-sm bg-surface-raised transition-transform duration-200 ease-in-out motion-reduce:transition-none"
        style={{ transform: `translateX(${activeIndex * 100}%)` }}
      />
      {VARIANTS.map((item) => {
        const active = item.variant === variant;
        return (
          <Link
            key={item.variant}
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
