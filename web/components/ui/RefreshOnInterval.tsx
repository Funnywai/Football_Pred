"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

const REFRESH_MS = 60_000;

// Re-runs the SERVER render on a sane interval, paused while the tab is hidden. The
// browser never calls the API directly; router.refresh() re-fetches through the server.
export function RefreshOnInterval() {
  const router = useRouter();
  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [router]);
  return null;
}
