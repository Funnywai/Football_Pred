import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

// The design contract is web/DESIGN.md; globals.css is its implementation. This test
// fails if any token drifts from the value DESIGN.md declares.
const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");

function token(name: string): string | undefined {
  const match = css.match(new RegExp(`--${name}:\\s*([^;]+);`));
  return match?.[1]?.trim();
}

const COLOR_TOKENS: Array<[string, string]> = [
  ["surface-void", "#050507"],
  ["surface-base", "#101010"],
  ["surface-raised", "#17171b"],
  ["border-default", "#3d3a39"],
  ["border-hairline", "#232326"],
  ["text-primary", "#f2f2f2"],
  ["text-secondary", "#b8b3b0"],
  ["text-tertiary", "#8b949e"],
  ["accent-signal", "#00d992"],
  ["accent-mint", "#2fd6a1"],
  ["status-neg", "#fb565b"],
  ["status-warn", "#ffba00"],
  ["status-info", "#4cb3d4"],
];

const SPACING_TOKENS: Array<[string, string]> = [
  ["space-1", "4px"],
  ["space-2", "8px"],
  ["space-3", "12px"],
  ["space-4", "16px"],
  ["space-5", "20px"],
  ["space-6", "24px"],
  ["space-8", "32px"],
  ["space-10", "40px"],
  ["space-12", "48px"],
  ["space-16", "64px"],
];

const TYPE_TOKENS: Array<[string, string]> = [
  ["text-display", "1.75rem"],
  ["text-h1", "1.25rem"],
  ["text-h2", "1rem"],
  ["text-h3", "0.875rem"],
  ["text-body", "0.875rem"],
  ["text-data", "0.8125rem"],
  ["text-caption", "0.75rem"],
  ["text-overline", "0.6875rem"],
];

describe("DESIGN.md colour tokens", () => {
  it.each(COLOR_TOKENS)("--%s is %s", (name, value) => {
    expect(token(name)).toBe(value);
  });
});

describe("DESIGN.md spacing tokens", () => {
  it.each(SPACING_TOKENS)("--%s is %s", (name, value) => {
    expect(token(name)).toBe(value);
  });
});

describe("DESIGN.md type scale", () => {
  it.each(TYPE_TOKENS)("--%s is %s", (name, value) => {
    expect(token(name)).toBe(value);
  });
});

describe("DESIGN.md depth, radius and motion tokens", () => {
  it("declares the two named shadow levels", () => {
    expect(token("shadow-ambient-glow")).toContain("rgba(92, 88, 85, 0.2)");
    expect(token("shadow-dramatic-float")).toContain("rgba(0, 0, 0, 0.7)");
  });

  it("declares the radius scale", () => {
    expect(token("radius-sm")).toBe("4px");
    expect(token("radius-md")).toBe("6px");
    expect(token("radius-lg")).toBe("8px");
    expect(token("radius-pill")).toBe("9999px");
  });

  it("declares the motion timing table", () => {
    expect(token("motion-micro")).toBe("150ms");
    expect(token("motion-standard")).toBe("300ms");
    expect(token("motion-emphasis")).toBe("600ms");
  });

  it("respects prefers-reduced-motion", () => {
    expect(css).toContain("prefers-reduced-motion: reduce");
  });

  it("uses no pure black or pure white", () => {
    expect(css).not.toMatch(/#000000\b/i);
    expect(css).not.toMatch(/#ffffff\b/i);
  });
});
