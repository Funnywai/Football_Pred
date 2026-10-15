import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LogAutoRefresh } from "@/components/technical/LogAutoRefresh";
import { LogStream } from "@/components/technical/LogStream";
import { LOG_LEVELS, logLevelKind, normalizeLogLevel } from "@/lib/logs";
import type { OpsLogLine } from "@/lib/types";

const { refreshMock } = vi.hoisted(() => ({ refreshMock: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

function line(overrides: Partial<OpsLogLine>): OpsLogLine {
  return {
    time: "2026-10-15T11:58:00Z",
    level: "INFO",
    logger: "app.services.odds",
    message: "synced 5 snapshots",
    ...overrides,
  };
}

describe("normalizeLogLevel", () => {
  it("accepts the five API levels case-insensitively", () => {
    expect(normalizeLogLevel("info")).toBe("INFO");
    expect(normalizeLogLevel("WARNING")).toBe("WARNING");
    expect(normalizeLogLevel("critical")).toBe("CRITICAL");
  });

  it("rejects unknown values and non-strings", () => {
    expect(normalizeLogLevel("bogus")).toBeNull();
    expect(normalizeLogLevel(undefined)).toBeNull();
    expect(normalizeLogLevel(["INFO"])).toBeNull();
    expect(normalizeLogLevel(42)).toBeNull();
  });

  it("exposes exactly the levels the API accepts", () => {
    expect(LOG_LEVELS).toEqual(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]);
  });
});

describe("logLevelKind", () => {
  it("maps the five levels and falls back to unknown", () => {
    expect(logLevelKind("DEBUG")).toBe("debug");
    expect(logLevelKind("INFO")).toBe("info");
    expect(logLevelKind("WARNING")).toBe("warning");
    expect(logLevelKind("ERROR")).toBe("error");
    expect(logLevelKind("CRITICAL")).toBe("critical");
    expect(logLevelKind("NOTSET")).toBe("unknown");
  });
});

describe("LogStream", () => {
  it("renders each line with its level label and the tail window", () => {
    render(
      <LogStream
        logs={[line({}), line({ level: "WARNING", message: "slow sync" })]}
        level={null}
        limit={100}
      />,
    );
    expect(screen.getByText("INFO")).toBeInTheDocument();
    expect(screen.getByText("WARNING")).toBeInTheDocument();
    expect(screen.getByText(/tail of the newest 100 buffered lines/)).toBeInTheDocument();
    expect(screen.getByText(/no level filter/)).toBeInTheDocument();
  });

  it("states the active filter and marks it with aria-current", () => {
    render(<LogStream logs={[line({})]} level="WARNING" limit={100} />);
    expect(screen.getByText(/filter: WARNING and above/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "warning" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("link", { name: "all" })).not.toHaveAttribute("aria-current");
  });

  it("renders an explicit unavailable state when /ops/logs failed", () => {
    render(<LogStream logs={null} level={null} limit={100} />);
    expect(screen.getByText("Log stream unavailable")).toBeInTheDocument();
  });

  it("says the filter matched nothing instead of implying the buffer is empty", () => {
    render(<LogStream logs={[]} level="ERROR" limit={100} />);
    expect(screen.getByText("No lines at or above ERROR in the buffer")).toBeInTheDocument();
  });
});

describe("LogAutoRefresh", () => {
  afterEach(() => {
    vi.useRealTimers();
    refreshMock.mockClear();
  });

  it("refreshes on the interval while live", async () => {
    vi.useFakeTimers();
    render(<LogAutoRefresh />);
    expect(screen.getByText(/auto-refresh 15s · live/)).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(15_000);
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });

  it("pauses and resumes without fetching anything itself", async () => {
    vi.useFakeTimers();
    render(<LogAutoRefresh />);
    fireEvent.click(screen.getByRole("button", { name: /pause/ }));
    expect(screen.getByText(/auto-refresh 15s · paused/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /resume/ })).toHaveAttribute("aria-pressed", "true");
    await vi.advanceTimersByTimeAsync(30_000);
    expect(refreshMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /resume/ }));
    await vi.advanceTimersByTimeAsync(15_000);
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });
});
