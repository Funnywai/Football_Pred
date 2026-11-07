import type { Metadata } from "next";
import Link from "next/link";

import { LlmLedgerSection } from "@/components/llm-ledger-section";
import { LlmOverviewSection } from "@/components/llm-overview-section";
import { LlmResearchSection } from "@/components/llm-research-section";
import { formatDateTime } from "@/lib/format";
import { getLlmPageData } from "@/lib/llm-api";
import type { LlmStatus } from "@/lib/llm-types";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export const metadata: Metadata = {
  title: "LLM Research Lab — Touchline/Lab",
  description:
    "Separate paper lane for evidence-backed football research, role-analyst findings, main-agent reports and betting recommendations.",
};

const NAV_ITEMS = [
  { href: "#llm-overview", label: "Overview", index: "01" },
  { href: "#llm-research", label: "Analyst report", index: "02" },
  { href: "#llm-paper-ledger", label: "Paper ledger", index: "03" },
];

export default async function LlmLabPage() {
  const {
    status: result,
    bets: betsResult,
    equity: equityResult,
    researchRuns: researchRunsResult,
  } = await getLlmPageData();
  const data: LlmStatus | null = result.data;
  const generatedAt = data?.generated_at ?? null;

  return (
    <div className="shell llm-shell">
      <header className="llm-masthead">
        <div className="llm-masthead__brand">
          <p className="llm-masthead__kicker">
            Football research · separate paper lane
          </p>
          <h1 className="llm-wordmark">
            LLM<span className="llm-wordmark__slash">/</span>
            <span className="llm-wordmark__lab">LAB</span>
          </h1>
          <p className="llm-wordmark__sub">Evidence-backed betting assistant</p>
          <p className="llm-masthead__tagline">
            Seven research analysts inspect the frozen evidence, the main agent
            writes the betting report and recommendation, and a deterministic
            safety layer decides whether a paper bet can be placed.
          </p>
        </div>

        <div className="llm-masthead__side">
          <Link className="llm-back" href="/">
            ← Back to TOUCHLINE/LAB
          </Link>
          <span className="llm-stamp">Separate lane · paper only</span>
          <p className="llm-generated">
            <span className="llm-generated__label">
              {result.error ? "Snapshot degraded" : "Snapshot generated"}
            </span>
            {generatedAt ? (
              <time dateTime={generatedAt}>{formatDateTime(generatedAt)}</time>
            ) : (
              <span>time unavailable</span>
            )}
            <span className="llm-generated__tz">HKT</span>
          </p>
        </div>
      </header>

      <nav className="llm-nav" aria-label="LLM Lab sections">
        <ul className="llm-nav__list">
          {NAV_ITEMS.map((item) => (
            <li key={item.href}>
              <a href={item.href} className="llm-nav__link">
                <span className="llm-nav__index" aria-hidden="true">
                  {item.index}
                </span>
                {item.label}
              </a>
            </li>
          ))}
        </ul>
        <p className="llm-nav__meta">
          <span className="llm-nav__pulse" aria-hidden="true" />
          server frame · /llm/status
        </p>
      </nav>

      <main id="main" className="main llm-main">
        <LlmOverviewSection result={result} />
        <LlmResearchSection runsResult={researchRunsResult} />
        <LlmLedgerSection
          ledger={data?.ledger ?? null}
          betsResult={betsResult}
          equityResult={equityResult}
        />
      </main>

      <footer className="site-footer llm-footer">
        <p>
          <span className="site-footer__mark">LLM/LAB</span> — separate research
          lane. Paper only; no real wagers are placed.
        </p>
        <p className="site-footer__meta">
          Server-rendered · API read server-side only ·{" "}
          <Link className="llm-footer__link" href="/">
            deterministic dashboard
          </Link>{" "}
          · {generatedAt ? `snapshot ${formatDateTime(generatedAt)}` : "no snapshot time"}
        </p>
      </footer>
    </div>
  );
}
