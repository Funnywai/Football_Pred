import Link from "next/link";

import type { LedgerBook } from "@/lib/types";

const BOOKS: ReadonlyArray<{ book: LedgerBook; label: string; href: string }> = [
  { book: "production", label: "Production", href: "/performance" },
  { book: "shadow", label: "Shadow · paper", href: "/performance?book=shadow" },
];

export interface LedgerBookToggleProps {
  book: LedgerBook;
}

// Same segmented-control anatomy as TabBar (DESIGN.md 10): a bordered track with a
// raised active indicator, real links, and the active book carried by aria-current.
export function LedgerBookToggle({ book }: LedgerBookToggleProps) {
  const activeIndex = book === "shadow" ? 1 : 0;

  return (
    <nav
      aria-label="Ledger book"
      className="relative grid grid-cols-2 rounded-md border border-border-default bg-surface-base p-1"
    >
      <span
        aria-hidden
        className="absolute inset-y-1 left-1 w-[calc(50%-var(--space-1))] rounded-sm bg-surface-raised transition-transform duration-200 ease-in-out motion-reduce:transition-none"
        style={{ transform: `translateX(${activeIndex * 100}%)` }}
      />
      {BOOKS.map((item) => {
        const active = item.book === book;
        return (
          <Link
            key={item.book}
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
