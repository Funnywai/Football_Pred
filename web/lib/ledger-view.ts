import { normalizeAgentVariant } from "./agent-variant";
import { normalizeLedgerBook } from "./ledger";
import type { LedgerBook } from "./types";

export type LedgerView = "production" | "shadow" | "agent" | "clv";

const LEDGER_VIEWS: ReadonlyArray<LedgerView> = ["production", "shadow", "agent", "clv"];

function isLedgerView(value: unknown): value is LedgerView {
  return (
    typeof value === "string" && (LEDGER_VIEWS as ReadonlyArray<string>).includes(value)
  );
}

/**
 * `?view=` is canonical; `?book=shadow` stays supported as the legacy URL so existing
 * `/performance` links and bookmarks keep landing on the shadow book. A valid view always
 * wins over a conflicting book, and anything unknown is production.
 */
export function normalizeLedgerView(view: unknown, book: unknown): LedgerView {
  return isLedgerView(view) ? view : normalizeLedgerBook(book);
}

/** CLV is model-level and the agent book is separate, so only shadow changes the book. */
export function ledgerViewBook(view: LedgerView): LedgerBook {
  return view === "shadow" ? "shadow" : "production";
}

/**
 * Resolve a legacy `/performance?...` URL to its canonical `/ledger` destination. The old
 * page accepted `?view=production|shadow|clv`, `?book=shadow` and no query at all; every
 * one of them must keep working, and the agent book variant is carried through.
 */
export function legacyPerformanceHref(params: {
  view?: unknown;
  book?: unknown;
  variant?: unknown;
}): string {
  const view = normalizeLedgerView(params.view, params.book);
  const search = new URLSearchParams({ view });
  if (view === "agent" && params.variant !== undefined) {
    search.set("variant", normalizeAgentVariant(params.variant));
  }
  return `/ledger?${search.toString()}`;
}
