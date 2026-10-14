import type { Metadata } from "next";

import { SectionShell } from "@/components/sections/SectionShell";
import { TECHNICAL_SECTIONS } from "@/lib/sections";

export const metadata: Metadata = {
  title: "Technical · WorldCup Mission Control",
};

export default function TechnicalPage() {
  return (
    <main role="tabpanel" aria-labelledby="tab-technical" className="flex flex-col gap-6">
      <div>
        <h1 className="text-h1 font-semibold text-text-primary">Technical</h1>
        <p className="mt-1 text-body text-text-secondary">
          Logs, scheduler, ingestion, freshness, database size, model versions and environment.
        </p>
      </div>
      {TECHNICAL_SECTIONS.map((section) => (
        <SectionShell key={section.id} {...section} />
      ))}
    </main>
  );
}
