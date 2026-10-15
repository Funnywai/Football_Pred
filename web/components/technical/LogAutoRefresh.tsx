"use client";

import { Pause, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export const LOG_REFRESH_MS = 15_000;

// Re-runs the SERVER render on an interval, paused while the tab is hidden or the user
// pauses. The browser never calls the API directly; router.refresh() re-fetches through
// the server (same mechanics as RefreshOnInterval).
export function LogAutoRefresh() {
  const router = useRouter();
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, LOG_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [paused, router]);

  return (
    <div className="flex items-center gap-2">
      <span className="text-caption text-text-tertiary">
        auto-refresh 15s · {paused ? "paused" : "live"}
      </span>
      <button
        type="button"
        aria-pressed={paused}
        onClick={() => setPaused((value) => !value)}
        className="inline-flex items-center gap-1 rounded-md border border-border-default px-2 py-1 text-caption text-text-secondary transition-colors duration-150 ease-out hover:border-accent-signal/40 hover:text-text-primary"
      >
        {paused ? <Play className="size-3" aria-hidden /> : <Pause className="size-3" aria-hidden />}
        <span>{paused ? "resume" : "pause"}</span>
      </button>
    </div>
  );
}
