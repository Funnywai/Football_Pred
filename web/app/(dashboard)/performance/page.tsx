import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { legacyPerformanceHref } from "@/lib/legacy-redirect";

export const metadata: Metadata = {
  title: "Agent · Football_Pred Mission Control",
};

/**
 * `/performance` was folded into `/agent`. This page is redirect-only so old bookmarks and
 * links keep working: a `?variant=abc` URL carries the variant through, and anything else
 * lands on the default A-only agent page.
 */
export default async function PerformancePage({
  searchParams,
}: {
  searchParams: Promise<{ variant?: string }>;
}) {
  const { variant } = await searchParams;
  redirect(legacyPerformanceHref({ variant }));
}
