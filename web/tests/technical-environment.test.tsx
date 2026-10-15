import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EnvironmentPanel } from "@/components/technical/EnvironmentPanel";
import { environmentRows } from "@/lib/environment";
import type { OpsStatus } from "@/lib/types";

const STATUS: OpsStatus = {
  app_version: "0.1.0",
  git_sha: "abc1234",
  alembic_revision: "0003_ledger_bets",
  uptime_seconds: 1234,
  db_ok: true,
  scheduler_enabled: true,
};

// A hostile status object: extra fields that must never reach the DOM. The panel
// whitelists the five fields it renders; nothing else is read.
const HOSTILE = {
  ...STATUS,
  database_url: "postgresql+asyncpg://football:supersecret@postgres:5432/football",
  api_token: "tok_live_1234567890",
  secret_key: "hunter2",
};

describe("environmentRows", () => {
  it("returns exactly the five whitelisted fields", () => {
    expect(environmentRows(STATUS).map((row) => row.id)).toEqual([
      "app_version",
      "git_sha",
      "alembic_revision",
      "db_ok",
      "scheduler_enabled",
    ]);
  });

  it("cannot leak a field outside the whitelist", () => {
    const serialized = JSON.stringify(environmentRows(HOSTILE));
    expect(serialized).not.toContain("supersecret");
    expect(serialized).not.toContain("tok_live");
    expect(serialized).not.toContain("hunter2");
    expect(serialized).not.toContain("postgresql");
  });

  it("labels the connectivity and scheduler states", () => {
    const rows = environmentRows({ ...STATUS, db_ok: false, scheduler_enabled: false });
    expect(rows.find((row) => row.id === "db_ok")?.value).toBe("unreachable");
    expect(rows.find((row) => row.id === "scheduler_enabled")?.value).toBe("disabled");
  });
});

describe("EnvironmentPanel", () => {
  it("renders the five fields with labelled connectivity states", () => {
    render(<EnvironmentPanel status={STATUS} />);
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
    expect(screen.getByText("abc1234")).toBeInTheDocument();
    expect(screen.getByText("0003_ledger_bets")).toBeInTheDocument();
    expect(screen.getByText("connected")).toBeInTheDocument();
    expect(screen.getByText("enabled")).toBeInTheDocument();
  });

  it("never renders a value outside the whitelist", () => {
    render(<EnvironmentPanel status={HOSTILE} />);
    expect(screen.queryByText(/supersecret/)).not.toBeInTheDocument();
    expect(screen.queryByText(/tok_live/)).not.toBeInTheDocument();
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument();
    expect(screen.queryByText(/postgresql/)).not.toBeInTheDocument();
  });

  it("renders an explicit unavailable state when /ops/status failed", () => {
    render(<EnvironmentPanel status={null} />);
    expect(screen.getByText("Environment unavailable")).toBeInTheDocument();
  });
});
