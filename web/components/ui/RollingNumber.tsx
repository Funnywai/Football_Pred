"use client";

import { useEffect, useRef, useState } from "react";

import {
  formatCount,
  formatHkd,
  formatOdds,
  formatPercent,
  formatSignedHkd,
  formatSignedPercent,
} from "@/lib/format";

export type NumberFormat = "hkd" | "signed-hkd" | "percent" | "signed-percent" | "count" | "odds";

function render(value: number, kind: NumberFormat): string {
  switch (kind) {
    case "hkd":
      return formatHkd(value);
    case "signed-hkd":
      return formatSignedHkd(value);
    case "percent":
      return formatPercent(value);
    case "signed-percent":
      return formatSignedPercent(value);
    case "count":
      return formatCount(value);
    case "odds":
      return formatOdds(value);
  }
}

const ROLL_MS = 400;

export interface RollingNumberProps {
  value: number;
  format: NumberFormat;
}

// Rolls from the previous value to the new one when the value changes (DESIGN.md 6.1).
// No animation on first render, and none under prefers-reduced-motion.
export function RollingNumber({ value, format }: RollingNumberProps) {
  const [display, setDisplay] = useState(value);
  const previous = useRef(value);

  useEffect(() => {
    const from = previous.current;
    previous.current = value;
    if (from === value) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const duration = reduce ? 0 : ROLL_MS;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = duration === 0 ? 1 : Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(from + (value - from) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);

  return <>{render(display, format)}</>;
}
