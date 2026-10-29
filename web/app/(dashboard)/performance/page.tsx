import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { legacyPerformanceHref } from "@/lib/ledger-view";

export const metadata: Metadata = {
  title: "Ledger · Football_Pred Mission Control",
};

/**
 * `/performance` was renamed to `/ledger`. This page is redirect-only so old bookmarks and
 * links keep working: `?view=...` maps through unchanged, `?book=shadow` becomes the shadow
 * view, and an absent query lands on production.
 */
export default async function PerformancePage({
  searchParams,
}: {
  searchParams: Promise<{ book?: string; view?: string; variant?: string }>;
}) {
  const { book, view, variant } = await searchParams;
  redirect(legacyPerformanceHref({ view, book, variant }));
}
