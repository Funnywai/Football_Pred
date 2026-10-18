"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";

import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";

const DELAY_MS = 3000;
const GAP_PX = 8;
const VIEWPORT_PAD_PX = 8;

export interface TermTipProps {
  term: GlossaryKey;
  children: ReactNode;
  className?: string;
}

interface TooltipPosition {
  top: number;
  left: number;
}

// A term is only explained after the pointer or focus rests on it for three seconds, so a
// quick scan of a dense table never fires a wall of popovers. The tooltip is portalled to
// document.body and positioned with fixed coordinates because the tables live inside
// overflow-x-auto containers that would otherwise clip it.
export function TermTip({ term, children, className }: TermTipProps) {
  const entry = GLOSSARY[term];
  const tooltipId = useId();
  const triggerRef = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<TooltipPosition | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const hide = useCallback(() => {
    clearTimer();
    setOpen(false);
    setPosition(null);
  }, [clearTimer]);

  const startTimer = useCallback(() => {
    clearTimer();
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      setOpen(true);
    }, DELAY_MS);
  }, [clearTimer]);

  // A pending timer must not outlive the component.
  useEffect(() => clearTimer, [clearTimer]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") hide();
    };
    const onScroll = () => hide();
    const onResize = () => hide();
    document.addEventListener("keydown", onKeyDown);
    // Capture catches scrolls inside the table's overflow container, not just the window.
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
    };
  }, [open, hide]);

  // Measure the rendered tooltip so it can flip above the trigger near the viewport edge.
  useEffect(() => {
    if (!open) return;
    const trigger = triggerRef.current;
    const tooltip = tooltipRef.current;
    if (trigger === null || tooltip === null) return;
    const rect = trigger.getBoundingClientRect();
    const width = tooltip.offsetWidth;
    const height = tooltip.offsetHeight;
    const halfWidth = width / 2;
    const minLeft = VIEWPORT_PAD_PX + halfWidth;
    const maxLeft = Math.max(minLeft, window.innerWidth - VIEWPORT_PAD_PX - halfWidth);
    const left = Math.min(Math.max(rect.left + rect.width / 2, minLeft), maxLeft);
    const belowTop = rect.bottom + GAP_PX;
    const fitsBelow = belowTop + height <= window.innerHeight - VIEWPORT_PAD_PX;
    const top = fitsBelow ? belowTop : Math.max(VIEWPORT_PAD_PX, rect.top - GAP_PX - height);
    setPosition({ top, left });
  }, [open]);

  const tooltip =
    open && typeof document !== "undefined"
      ? createPortal(
          <div
            ref={tooltipRef}
            id={tooltipId}
            role="tooltip"
            className="pointer-events-none fixed z-50 w-72 max-w-[calc(100vw-1rem)] rounded-md border border-border-default bg-surface-raised p-3 text-caption text-text-secondary shadow-[var(--shadow-dramatic-float)]"
            style={{
              top: position?.top ?? 0,
              left: position?.left ?? 0,
              transform: "translateX(-50%)",
              opacity: position === null ? 0 : 1,
            }}
          >
            <p className="font-semibold text-text-primary">{entry.label}</p>
            <p className="mt-1">{entry.what}</p>
            <dl className="mt-2 flex flex-col gap-1">
              <div className="flex gap-2">
                <dt className="shrink-0 text-accent-mint">好</dt>
                <dd>{entry.good}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="shrink-0 text-status-neg">壞</dt>
                <dd>{entry.bad}</dd>
              </div>
            </dl>
          </div>,
          document.body,
        )
      : null;

  return (
    <>
      <span
        ref={triggerRef}
        tabIndex={0}
        aria-describedby={open ? tooltipId : undefined}
        className={`cursor-help ${className ?? ""}`}
        onPointerEnter={startTimer}
        onPointerLeave={hide}
        onFocus={startTimer}
        onBlur={hide}
      >
        {children}
      </span>
      {tooltip}
    </>
  );
}
