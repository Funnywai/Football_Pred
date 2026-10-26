import type { LedgerBook } from "./types";

/** The API accepts exactly `production` and `shadow`; anything else means production. */
export function normalizeLedgerBook(value: unknown): LedgerBook {
  return value === "shadow" ? "shadow" : "production";
}
