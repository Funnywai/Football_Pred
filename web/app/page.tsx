import { getDashboardData } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

import { CalibrationSection } from "@/components/calibration-section";
import { LedgerSection } from "@/components/ledger-section";
import { Masthead, SiteNav } from "@/components/masthead";
import { OverviewSection } from "@/components/overview-section";
import { PredictionsSection } from "@/components/predictions-section";
import { TechnicalSection } from "@/components/technical-section";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function DashboardPage() {
  const data = await getDashboardData();
  const overview = data.overview.data;
  const generatedAt = overview?.generated_at ?? null;
  const degraded = Object.values(data).some((result) => Boolean(result.error));

  return (
    <div className="shell">
      <Masthead
        health={
          overview?.health ??
          (data.overview.error ? { api: "down", database: "unknown", redis: "unknown" } : undefined)
        }
        generatedAt={generatedAt}
        degraded={degraded}
      />
      <SiteNav generatedAt={generatedAt} />

      <main id="main" className="main">
        <OverviewSection result={data.overview} />
        <PredictionsSection result={data.predictions} />
        <LedgerSection betsResult={data.bets} equityResult={data.equity} />
        <CalibrationSection result={data.calibration} />
        <TechnicalSection result={data.technical} />
      </main>

      <footer className="site-footer">
        <p>
          <span className="site-footer__mark">TOUCHLINE/LAB</span> — paper-only research
          terminal. No real wagers are placed.
        </p>
        <p className="site-footer__meta">
          Server-rendered · API read server-side only · all times HKT ·{" "}
          {generatedAt ? `snapshot ${formatDateTime(generatedAt)}` : "no snapshot time"}
        </p>
      </footer>
    </div>
  );
}
