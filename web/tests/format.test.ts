import { describe, expect, it } from "vitest";

import { formatDecimal } from "@/lib/format";

describe("formatDecimal", () => {
  it("renders a fixed number of decimals for calibration scores", () => {
    expect(formatDecimal(0.1923)).toBe("0.1923");
    expect(formatDecimal(0.5512)).toBe("0.5512");
  });

  it("pads and rounds to the requested precision", () => {
    expect(formatDecimal(0.5)).toBe("0.5000");
    expect(formatDecimal(0.123456, 3)).toBe("0.123");
  });
});
