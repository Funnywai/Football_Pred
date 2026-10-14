"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef, type KeyboardEvent } from "react";

const TABS = [
  { href: "/performance", label: "Performance" },
  { href: "/technical", label: "Technical" },
] as const;

export function TabBar() {
  const pathname = usePathname();
  const refs = useRef<Array<HTMLAnchorElement | null>>([]);

  const found = TABS.findIndex((tab) => pathname.startsWith(tab.href));
  const activeIndex = found === -1 ? 0 : found;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const delta = event.key === "ArrowRight" ? 1 : -1;
    const next = (activeIndex + delta + TABS.length) % TABS.length;
    refs.current[next]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label="Dashboard sections"
      onKeyDown={onKeyDown}
      className="relative grid grid-cols-2 rounded-md border border-border-default bg-surface-base p-1"
    >
      <span
        aria-hidden
        className="absolute inset-y-1 left-1 w-[calc(50%-var(--space-1))] rounded-sm bg-surface-raised transition-transform duration-200 ease-in-out motion-reduce:transition-none"
        style={{ transform: `translateX(${activeIndex * 100}%)` }}
      />
      {TABS.map((tab, index) => {
        const selected = index === activeIndex;
        return (
          <Link
            key={tab.href}
            ref={(node) => {
              refs.current[index] = node;
            }}
            href={tab.href}
            id={`tab-${tab.href.slice(1)}`}
            role="tab"
            aria-selected={selected}
            className={`relative z-10 rounded-sm px-3 py-2 text-center text-data transition-colors duration-150 ease-out ${
              selected ? "text-accent-signal" : "text-text-secondary hover:text-text-primary"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
