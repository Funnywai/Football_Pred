import type { Metadata } from "next";

import { SectionShell } from "@/components/sections/SectionShell";
import { PERFORMANCE_SECTIONS } from "@/lib/sections";

export const metadata: Metadata = {
  title: "Performance · WorldCup Mission Control",
};

export default function PerformancePage() {
  return (
    <main
      role="tabpanel"
      aria-labelledby="tab-performance"
      className="flex flex-col gap-6"
    >
      <div>
        <h1 className="text-h1 font-semibold text-text-primary">Performance</h1>
        <p className="mt-1 text-body text-text-secondary">
          Every match, prediction, bet and outcome, plus money over time.
        </p>
      </div>
      {PERFORMANCE_SECTIONS.map((section) => (
        <SectionShell key={section.id} {...section} />
      ))}
    </main>
  );
}
