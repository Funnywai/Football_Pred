import { formatDateTime, formatTime } from "@/lib/format";
import type { Health } from "@/lib/types";

import { HealthPill } from "./ui";

const NAV_ITEMS = [
  { href: "#overview", label: "Overview", index: "01" },
  { href: "#predictions", label: "Predictions", index: "02" },
  { href: "#paper-ledger", label: "Paper ledger", index: "03" },
  { href: "#technical", label: "Technical", index: "04" },
  { href: "/llm", label: "LLM Lab", index: "05" },
];

export function Masthead({
  health,
  generatedAt,
  degraded,
}: {
  health: Health | null | undefined;
  generatedAt: string | null | undefined;
  degraded: boolean;
}) {
  return (
    <header className="masthead">
      <div className="masthead__brand">
        <p className="masthead__kicker">Football market models · paper settlement</p>
        <h1 className="wordmark">
          TOUCHLINE<span className="wordmark__slash">/</span><span className="wordmark__lab">LAB</span>
        </h1>
        <p className="masthead__tagline">
          A read-only research terminal for model probabilities, bet decisions, and
          paper-ledger accounting.
        </p>
      </div>

      <div className="masthead__side">
        <span className="stamp">Paper only · no real money</span>

        <div className="masthead__status" role="group" aria-label="System health">
          <HealthPill label="API" state={health?.api} />
          <HealthPill label="DB" state={health?.database} />
          <HealthPill label="Redis" state={health?.redis} />
        </div>

        <p className="masthead__generated">
          <span className="masthead__generated-label">
            {degraded ? "Snapshot degraded" : "Snapshot generated"}
          </span>
          {generatedAt ? (
            <time dateTime={generatedAt}>{formatDateTime(generatedAt)}</time>
          ) : (
            <span>time unavailable</span>
          )}
          <span className="masthead__tz">HKT</span>
        </p>
      </div>
    </header>
  );
}

export function SiteNav({ generatedAt }: { generatedAt: string | null | undefined }) {
  return (
    <nav className="site-nav" aria-label="Dashboard sections">
      <ul className="site-nav__list">
        {NAV_ITEMS.map((item) => (
          <li key={item.href}>
            <a href={item.href} className="site-nav__link">
              <span className="site-nav__index" aria-hidden="true">
                {item.index}
              </span>
              {item.label}
            </a>
          </li>
        ))}
      </ul>
      <p className="site-nav__meta">
        <span className="site-nav__pulse" aria-hidden="true" />
        {generatedAt ? `server frame · ${formatTime(generatedAt)} HKT` : "server frame · snapshot unavailable"}
      </p>
    </nav>
  );
}
