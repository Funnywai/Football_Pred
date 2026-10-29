import { normalizeLedgerBook } from "./ledger";
import type { LedgerBook } from "./types";

export type PerformanceView = "production" | "shadow" | "clv";

/**
 * `?view=` is canonical; `?book=shadow` stays supported as the legacy URL so existing
 * links and bookmarks keep landing on the shadow view. Anything unknown is production.
 */
export function normalizePerformanceView(
  view: unknown,
  book: unknown,
): PerformanceView {
  if (view === "production" || view === "shadow" || view === "clv") return view;
  return normalizeLedgerBook(book);
}

/** CLV is model-level, so its ledger-backed metrics always read the production book. */
export function performanceViewBook(view: PerformanceView): LedgerBook {
  return view === "shadow" ? "shadow" : "production";
}
