"use client";

import { useEffect, useState } from "react";

type CopyState = "idle" | "copied" | "error";

function fallbackCopy(text: string): void {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "0";
  textarea.style.left = "0";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textarea);
  if (!copied) throw new Error("Clipboard copy failed");
}

export function CopyTableButton({
  text,
  label = "Copy",
  title = "Copy the full prediction table as tab-separated values",
  copiedMessage = "Prediction table copied to clipboard",
}: {
  text: string;
  label?: string;
  title?: string;
  copiedMessage?: string;
}) {
  const [state, setState] = useState<CopyState>("idle");

  useEffect(() => {
    if (state === "idle") return;
    const timer = window.setTimeout(() => setState("idle"), 2200);
    return () => window.clearTimeout(timer);
  }, [state]);

  async function copy(): Promise<void> {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        fallbackCopy(text);
      }
      setState("copied");
    } catch {
      try {
        fallbackCopy(text);
        setState("copied");
      } catch {
        setState("error");
      }
    }
  }

  const visibleLabel =
    state === "copied" ? "Copied" : state === "error" ? "Retry" : label;

  return (
    <button
      type="button"
      className={`panel-copy panel-copy--${state}`}
      onClick={copy}
      title={title}
      aria-label={title}
    >
      <svg
        className="panel-copy__icon"
        viewBox="0 0 16 16"
        aria-hidden="true"
        focusable="false"
      >
        <rect x="5.25" y="4.25" width="8.5" height="9.5" rx="1" />
        <path d="M10.75 4.25V3.5a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h.5" />
      </svg>
      <span>{visibleLabel}</span>
      <span className="sr-only" aria-live="polite">
        {state === "copied"
          ? copiedMessage
          : state === "error"
            ? "Copy failed; try again"
            : ""}
      </span>
    </button>
  );
}
