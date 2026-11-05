import type { EndpointResult } from "@/lib/api";
import type { LlmResearchRun } from "@/lib/llm-types";

import { TableFrame } from "./table-frame";
import { DataWarning, EmptyState, Panel, SectionHeader, StatusTag } from "./ui";

function List({ items, empty }: { items: string[] | null | undefined; empty: string }) {
  if (!items || items.length === 0) return <p className="panel__note">{empty}</p>;
  return (
    <ul className="llm-findings">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export function LlmResearchSection({
  runsResult,
  latestResult,
}: {
  runsResult: EndpointResult<LlmResearchRun[]>;
  latestResult: EndpointResult<LlmResearchRun> | null;
}) {
  const runs = Array.isArray(runsResult.data) ? runsResult.data : [];
  const latest = latestResult?.data ?? runs[0] ?? null;
  const findingRows = Array.isArray(latest?.findings) ? latest.findings : [];

  return (
    <section id="llm-research" className="section" aria-labelledby="llm-research-title">
      <SectionHeader
        index="02"
        kicker="Research and recommendation"
        title="Analyst Report"
        meta={runsResult.error ? "report unavailable" : `${runs.length} run${runs.length === 1 ? "" : "s"}`}
      />

      {runsResult.error ? (
        <DataWarning label="LLM research runs" endpoint="/llm/research-runs" error={runsResult.error} />
      ) : null}

      {!latest ? (
        <EmptyState>
          No research run has been recorded yet. The next assistant job will create
          an evidence packet, role findings, a main-agent report and a risk decision.
        </EmptyState>
      ) : (
        <>
          <Panel
            title="Main-agent report"
            kicker="Evidence → synthesis"
            meta={
              <span className="panel__meta-group">
                <StatusTag status={latest.status} />
                <span>{latest.model_version ?? "—"}</span>
              </span>
            }
          >
            <div className="llm-report">
              <div className="llm-report__summary">
                <span className="llm-report__label">Summary</span>
                <p>{latest.report?.summary?.trim() || "No summary recorded."}</p>
              </div>
              <div className="llm-report__grid">
                <div>
                  <span className="llm-report__label">Key findings</span>
                  <List items={latest.report?.key_findings} empty="No key findings recorded." />
                </div>
                <div>
                  <span className="llm-report__label">Risks</span>
                  <List items={latest.report?.risks} empty="No risks recorded." />
                </div>
                <div>
                  <span className="llm-report__label">Market view</span>
                  <p>{latest.report?.market_view?.trim() || "No market view recorded."}</p>
                </div>
                <div>
                  <span className="llm-report__label">Reasoning</span>
                  <p>{latest.report?.reasoning?.trim() || "No reasoning recorded."}</p>
                </div>
              </div>
            </div>
          </Panel>

          <div className="llm-split">
            <Panel title="Model output" kicker="Main-agent probabilities" meta={latest.stage ?? "—"}>
              <div className="triplet llm-report__probabilities">
                {(["H", "D", "A"] as const).map((side) => (
                  <span className="triplet__row" key={side}>
                    <span className="triplet__label">{side}</span>
                    <span className="triplet__value">
                      {latest.probabilities?.[side] !== null && latest.probabilities?.[side] !== undefined
                        ? `${(Number(latest.probabilities[side]) * 100).toFixed(1)}%`
                        : "—"}
                    </span>
                  </span>
                ))}
              </div>
              <dl className="llm-decision-facts">
                <div>
                  <dt>Recommended side</dt>
                  <dd>{latest.recommended_side ?? "—"}</dd>
                </div>
                <div>
                  <dt>Recommended stake</dt>
                  <dd>
                    {latest.recommended_stake_pct !== null && latest.recommended_stake_pct !== undefined
                      ? `${(Number(latest.recommended_stake_pct) * 100).toFixed(2)}% bankroll`
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd>
                    {latest.confidence !== null && latest.confidence !== undefined
                      ? `${(Number(latest.confidence) * 100).toFixed(1)}%`
                      : "—"}
                  </dd>
                </div>
              </dl>
            </Panel>

            <Panel
              title="Bet suggestion"
              kicker="Recommendation and safety decision"
              meta={<StatusTag status={latest.risk?.accepted ? "accepted" : "not placed"} tone={latest.risk?.accepted ? "positive" : "muted"} />}
            >
              <dl className="llm-decision-facts">
                <div>
                  <dt>Decision</dt>
                  <dd>{latest.risk?.accepted ? "Paper bet placed" : "No paper bet"}</dd>
                </div>
                <div>
                  <dt>Reason</dt>
                  <dd>{latest.risk?.reason ?? latest.error ?? "No risk decision recorded."}</dd>
                </div>
                <div>
                  <dt>Final stake</dt>
                  <dd>{latest.risk?.stake ?? "—"}</dd>
                </div>
                <div>
                  <dt>Paper bet</dt>
                  <dd className="mono">{latest.risk?.paper_bet_id ?? "—"}</dd>
                </div>
              </dl>
            </Panel>
          </div>

          <Panel
            title="Role findings"
            kicker="Evidence-backed research"
            meta={`${findingRows.length} analysts`}
            bodyClassName="panel__body--flush"
          >
            {findingRows.length === 0 ? (
              <EmptyState>No role findings were recorded for this run.</EmptyState>
            ) : (
              <TableFrame label="LLM role findings" wide>
                <table className="table--llm-findings">
                  <caption className="sr-only">Role-agent findings for the latest LLM research run</caption>
                  <thead>
                    <tr>
                      <th scope="col">Analyst</th>
                      <th scope="col">Direction</th>
                      <th scope="col">Confidence</th>
                      <th scope="col">Summary</th>
                      <th scope="col">Findings</th>
                      <th scope="col">Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {findingRows.map((finding, index) => (
                      <tr key={`${finding.agent_id ?? "agent"}-${index}`}>
                        <td className="mono">{finding.agent_id ?? "—"}</td>
                        <td>
                          <StatusTag status={finding.abstain ? "abstained" : finding.direction ?? "neutral"} />
                        </td>
                        <td className="num">
                          {finding.confidence !== null && finding.confidence !== undefined
                            ? `${(Number(finding.confidence) * 100).toFixed(0)}%`
                            : "—"}
                        </td>
                        <td>{finding.summary ?? "—"}</td>
                        <td>
                          <List items={finding.findings} empty="—" />
                        </td>
                        <td className="mono cell-muted">
                          {finding.evidence_refs?.length ? finding.evidence_refs.join(", ") : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableFrame>
            )}
          </Panel>
        </>
      )}
    </section>
  );
}
