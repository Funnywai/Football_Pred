import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { legacyLedgerHref } from "@/lib/legacy-redirect";

export const metadata: Metadata = {
  title: "Agent · Football_Pred Mission Control",
};

/**
 * `/ledger` was folded into `/agent`. This page is redirect-only so old bookmarks and
 * links keep working: a `?view=agent&variant=abc` URL carries the variant through, and
 * every other production/shadow/CLV view lands on the default A-only agent page.
 */
export default async function LedgerPage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string; variant?: string }>;
}) {
  const { view, variant } = await searchParams;
  redirect(legacyLedgerHref({ view, variant }));
}
