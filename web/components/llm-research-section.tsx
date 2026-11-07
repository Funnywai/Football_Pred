import type { EndpointResult } from "@/lib/api";
import type { LlmResearchRun } from "@/lib/llm-types";

import { LlmRunsTable } from "./llm-runs-table";
import { DataWarning, EmptyState, SectionHeader } from "./ui";

export function LlmResearchSection({
  runsResult,
}: {
  runsResult: EndpointResult<LlmResearchRun[]>;
}) {
  const runs = Array.isArray(runsResult.data) ? runsResult.data : [];

  return (
    <section
      id="llm-research"
      className="section"
      aria-labelledby="analyst-report-title"
    >
      <SectionHeader
        index="02"
        kicker="Research and recommendation"
        title="Analyst Report"
        meta={runsResult.error ? "report unavailable" : `${runs.length} runs`}
      />

      {runsResult.error ? (
        <DataWarning
          label="LLM research runs"
          endpoint="/llm/research-runs"
          error={runsResult.error}
        />
      ) : null}

      {runs.length > 0 ? (
        <LlmRunsTable runs={runs} />
      ) : runsResult.error ? null : (
        <EmptyState>
          No research run has been recorded yet. The next assistant job will
          create an evidence packet, role findings, a main-agent report and a
          risk decision.
        </EmptyState>
      )}
    </section>
  );
}
