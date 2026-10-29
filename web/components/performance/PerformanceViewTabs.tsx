import Link from "next/link";

import type { PerformanceView } from "@/lib/performance-view";

const VIEWS: ReadonlyArray<{ view: PerformanceView; label: string; href: string }> = [
  { view: "production", label: "Production", href: "/performance?view=production" },
  { view: "shadow", label: "Shadow", href: "/performance?view=shadow" },
  { view: "clv", label: "CLV & Calibration", href: "/performance?view=clv" },
];

export interface PerformanceViewTabsProps {
  view: PerformanceView;
}

const ACTIVE_INDEX: Record<PerformanceView, number> = {
  production: 0,
  shadow: 1,
  clv: 2,
};

export function PerformanceViewTabs({ view }: PerformanceViewTabsProps) {
  const activeIndex = ACTIVE_INDEX[view];

  return (
    <nav
      aria-label="Performance view"
      className="relative grid grid-cols-3 rounded-md border border-border-default bg-surface-base p-1"
    >
      <span
        aria-hidden
        className="absolute inset-y-1 left-1 w-[calc((100%-2*var(--space-1))/3)] rounded-sm bg-surface-raised transition-transform duration-200 ease-in-out motion-reduce:transition-none"
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
