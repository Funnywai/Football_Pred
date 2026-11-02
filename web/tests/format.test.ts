import { describe, expect, it } from "vitest";

import { extractCalibrationBins, toAxisPercent } from "../lib/calibration";
import {
  asNumber,
  formatMoney,
  formatPercent,
  formatSignedPercent,
  probabilitiesToPercents,
  toPercentPoints,
} from "../lib/format";

describe("number coercion", () => {
  it("parses Decimal strings and rejects junk", () => {
    expect(asNumber("12.50")).toBe(12.5);
    expect(asNumber("")).toBeNull();
    expect(asNumber("not-a-number")).toBeNull();
    expect(asNumber(null)).toBeNull();
  });
});

describe("rate formatting", () => {
  it("treats fractions as ratios and percentage points as-is", () => {
    expect(toPercentPoints("-0.0423")).toBeCloseTo(-4.23);
    expect(toPercentPoints(12.5)).toBe(12.5);
  });

  it("formats signed percentages with a true minus sign", () => {
    expect(formatSignedPercent("-0.0423", 2)).toBe("−4.23%");
    expect(formatSignedPercent("0.1", 1)).toBe("+10.0%");
    expect(formatSignedPercent(null)).toBe("—");
  });

  it("formats percent and money with fallbacks", () => {
    expect(formatPercent(0.1234, 1)).toBe("12.3%");
    expect(formatPercent(null)).toBe("—");
    expect(formatMoney("1234.5", "HKD")).toContain("1,234.50");
    expect(formatMoney(undefined)).toBe("—");
  });
});

describe("probability scaling", () => {
  it("normalises fractional probabilities to percentage points", () => {
    const percents = probabilitiesToPercents({ H: "0.42", D: "0.28", A: "0.3" });
    expect(percents.H).toBeCloseTo(42);
    expect(percents.D).toBeCloseTo(28);
    expect(percents.A).toBeCloseTo(30);
  });

  it("keeps already-percentage values untouched", () => {
    const percents = probabilitiesToPercents({ H: 42, D: 28, A: 30 });
    expect(percents.H).toBe(42);
  });
});

describe("calibration bin parsing", () => {
  it("reads arrays of bins", () => {
    const bins = extractCalibrationBins([
      { bin: "0.1-0.2", predicted: 0.15, observed: 0.18, count: 40 },
      { label: "0.8-0.9", predicted: 0.85, observed: 0.8, n: 12 },
    ]);
    expect(bins).toHaveLength(2);
    expect(bins[0]?.label).toBe("0.1-0.2");
    expect(bins[1]?.count).toBe(12);
  });

  it("reads bucket-keyed objects", () => {
    const bins = extractCalibrationBins({
      "0.2": { predicted: 0.2, observed: 0.24, count: 10 },
      "0.4": { predicted: 0.4, observed: 0.37, count: 20 },
    });
    expect(bins).toHaveLength(2);
    expect(toAxisPercent(bins[0]?.predicted ?? null)).toBeCloseTo(20);
  });

  it("returns an empty list for unknown payloads", () => {
    expect(extractCalibrationBins(null)).toEqual([]);
    expect(extractCalibrationBins("nope")).toEqual([]);
    expect(extractCalibrationBins([{ unrelated: true }])).toEqual([]);
  });
});
