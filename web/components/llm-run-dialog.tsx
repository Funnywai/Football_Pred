"use client";

import { useEffect, useRef, useState } from "react";

import { asNumber, formatDateTime, formatKickoff, formatNumber } from "@/lib/format";
import type {
  LlmResearchFinding,
  LlmResearchRisk,
  LlmResearchRun,
} from "@/lib/llm-types";
import type { Numeric } from "@/lib/types";

import { StatusTag } from "./ui";

type DetailResult =
  | { requestKey: string; status: "error"; message: string }
  | { requestKey: string; status: "ready"; run: LlmResearchRun };

const ANALYSTS: ReadonlyArray<{ id: string; zh: string; en: string }> = [
  { id: "availability_agent", zh: "傷兵陣容", en: "Availability" },
  { id: "base_rate_agent", zh: "基礎數據", en: "Base rate" },
  { id: "environment_agent", zh: "環境", en: "Environment" },
  { id: "form_agent", zh: "狀態", en: "Form" },
  { id: "market_agent", zh: "市場", en: "Market" },
  { id: "news_agent", zh: "新聞", en: "News" },
  { id: "tactical_agent", zh: "戰術", en: "Tactical" },
];

const ANALYST_IDS = new Set(ANALYSTS.map((agent) => agent.id));

function percentLabel(value: number | null, digits: number): string {
  return value === null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

function probabilityLabel(value: Numeric): string {
  const parsed = asNumber(value);
  return parsed === null ? "—" : `${(parsed * 100).toFixed(1)}%`;
}

function List({
  items,
  className = "llm-dialog__list",
}: {
  items: string[] | null | undefined;
  className?: string;
}) {
  if (!items || items.length === 0) {
    return <p className="llm-dialog__prose">—</p>;
  }
  return (
    <ul className={className}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function DecisionSummary({ run }: { run: LlmResearchRun }) {
  const stake = run.abstain ? null : asNumber(run.recommended_stake_pct);
  const confidence = asNumber(run.confidence);
  const side = run.abstain ? "abstain" : run.recommended_side?.trim() || "—";
  const probabilities = run.probabilities;
  const sides = ["H", "D", "A"] as const;
  const hasProbabilities = sides.some(
    (outcome) => asNumber(probabilities?.[outcome]) !== null,
  );
  return (
    <dl className="llm-dialog__grid">
      <div className="llm-dialog__fact">
        <dt className="llm-dialog__fact-label">推薦</dt>
        <dd className="llm-dialog__fact-value">{side}</dd>
      </div>
      <div className="llm-dialog__fact">
        <dt className="llm-dialog__fact-label">注碼</dt>
        <dd className="llm-dialog__fact-value">{percentLabel(stake, 2)}</dd>
      </div>
      <div className="llm-dialog__fact">
        <dt className="llm-dialog__fact-label">信心</dt>
        <dd className="llm-dialog__fact-value">{percentLabel(confidence, 1)}</dd>
      </div>
      <div className="llm-dialog__fact">
        <dt className="llm-dialog__fact-label">H · D · A</dt>
        <dd className="llm-dialog__fact-value llm-dialog__probabilities">
          {hasProbabilities ? (
            sides.map((outcome) => (
              <span key={outcome}>
                {outcome} {probabilityLabel(probabilities?.[outcome])}
              </span>
            ))
          ) : (
            <span>—</span>
          )}
        </dd>
      </div>
    </dl>
  );
}

function DetailReport({ run }: { run: LlmResearchRun }) {
  const report = run.report;
  if (!report) {
    const error = run.error?.trim() || null;
    if (error && error.toLowerCase().includes("active role findings")) {
      return (
        <p className="llm-dialog__notice">本次 run 在角色分析階段中止：{error}</p>
      );
    }
    return (
      <p className="llm-dialog__notice">
        本次 run 沒有 main-agent 報告：{error ?? "未產生報告"}
      </p>
    );
  }
  return (
    <div>
      <p className="llm-dialog__subtitle">摘要</p>
      <p className="llm-dialog__prose">{report.summary?.trim() || "—"}</p>
      <p className="llm-dialog__subtitle">關鍵發現</p>
      <List items={report.key_findings} />
      <p className="llm-dialog__subtitle">市場觀點</p>
      <p className="llm-dialog__prose">{report.market_view?.trim() || "—"}</p>
      <p className="llm-dialog__subtitle">風險</p>
      <List items={report.risks} />
      <p className="llm-dialog__subtitle">推理</p>
      <p className="llm-dialog__prose">{report.reasoning?.trim() || "—"}</p>
    </div>
  );
}

function AnalystName({
  finding,
  agent,
}: {
  finding: LlmResearchFinding | null;
  agent: { id: string; zh: string; en: string } | null;
}) {
  if (!agent) {
    return (
      <div className="llm-analyst">
        <span className="llm-analyst__name mono">{finding?.agent_id ?? "unknown"}</span>
        <span className="llm-analyst__id">未識別的分析師</span>
      </div>
    );
  }
  return (
    <div className="llm-analyst">
      <span className="llm-analyst__name">
        {agent.zh} · {agent.en}
      </span>
      <span className="llm-analyst__id mono">{agent.id}</span>
    </div>
  );
}

function AnalystDetail({ finding }: { finding: LlmResearchFinding | null }) {
  if (!finding) {
    return <p className="llm-analyst__summary cell-muted">本次 run 未提供此分析師的發現。</p>;
  }
  if (finding.abstain) {
    return (
      <p className="llm-analyst__abstain">
        {finding.error?.trim() || finding.summary?.trim() || "已棄權"}
      </p>
    );
  }
  return (
    <>
      <p className="llm-analyst__summary">{finding.summary?.trim() || "—"}</p>
      {finding.findings?.length ? (
        <ul className="llm-analyst__findings">
          {finding.findings.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
      {finding.uncertainties?.length ? (
        <>
          <p className="llm-analyst__label">不確定性</p>
          <ul className="llm-analyst__findings">
            {finding.uncertainties.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}
      {finding.evidence_refs?.length ? (
        <code className="llm-analyst__evidence">
          {finding.evidence_refs.join(", ")}
        </code>
      ) : null}
    </>
  );
}

function AnalystTable({ run }: { run: LlmResearchRun }) {
  const findings = Array.isArray(run.findings) ? run.findings : [];
  const byId = new Map<string, LlmResearchFinding>();
  for (const finding of findings) {
    if (finding.agent_id) byId.set(finding.agent_id, finding);
  }
  const extraFindings = findings
    .filter((finding) => !finding.agent_id || !ANALYST_IDS.has(finding.agent_id))
    .slice()
    .sort((left, right) =>
      (left.agent_id ?? "").localeCompare(right.agent_id ?? ""),
    );

  const rows: Array<{
    key: string;
    agent: { id: string; zh: string; en: string } | null;
    finding: LlmResearchFinding | null;
  }> = [
    ...ANALYSTS.map((agent) => ({
      key: agent.id,
      agent,
      finding: byId.get(agent.id) ?? null,
    })),
    ...extraFindings.map((finding, index) => ({
      key: finding.agent_id ?? `extra-${index}`,
      agent: null,
      finding,
    })),
  ];

  return (
    <table className="llm-analyst-table">
      <caption className="sr-only">
        Research analyst decisions for this run
      </caption>
      <thead>
        <tr>
          <th scope="col">分析師</th>
          <th scope="col">立場</th>
          <th scope="col">信心</th>
          <th scope="col">摘要與發現</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ key, agent, finding }) => {
          const confidence = asNumber(finding?.confidence);
          return (
            <tr key={key}>
              <td data-label="分析師">
                <AnalystName finding={finding} agent={agent} />
              </td>
              <td data-label="立場">
                {finding?.abstain ? (
                  <StatusTag status="abstained" tone="negative" />
                ) : finding?.direction ? (
                  <StatusTag status={finding.direction} />
                ) : (
                  <span className="cell-muted">—</span>
                )}
              </td>
              <td data-label="信心" className="num">
                {confidence === null ? "—" : `${(confidence * 100).toFixed(0)}%`}
              </td>
              <td data-label="摘要與發現">
                <AnalystDetail finding={finding} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function RiskDecision({ risk }: { risk: LlmResearchRisk | null }) {
  if (!risk) {
    return (
      <p className="llm-dialog__notice">
        未進入風控（分析階段中止或 main agent 棄權）
      </p>
    );
  }
  const facts: Array<{ label: string; value: string }> = [];
  if (risk.reason?.trim()) facts.push({ label: "原因", value: risk.reason.trim() });
  if (risk.selection?.trim()) {
    facts.push({ label: "選擇", value: risk.selection.trim() });
  }
  const stake = asNumber(risk.stake);
  if (stake !== null) facts.push({ label: "注碼", value: formatNumber(stake, 2) });
  const odds = asNumber(risk.odds);
  if (odds !== null) facts.push({ label: "賠率", value: formatNumber(odds, 2) });
  if (risk.paper_bet_id?.trim()) {
    facts.push({ label: "紙上注單", value: risk.paper_bet_id.trim() });
  }
  const bankroll = asNumber(risk.bankroll);
  if (bankroll !== null) {
    facts.push({ label: "資金", value: formatNumber(bankroll, 2) });
  }
  return (
    <>
      <p
        className={
          risk.accepted
            ? "llm-dialog__outcome text-positive"
            : "llm-dialog__outcome text-negative"
        }
      >
        {risk.accepted ? "已建立 paper bet" : "風控拒絕"}
      </p>
      {facts.length > 0 ? (
        <dl className="llm-dialog__grid">
          {facts.map((fact) => (
            <div className="llm-dialog__fact" key={fact.label}>
              <dt className="llm-dialog__fact-label">{fact.label}</dt>
              <dd className="llm-dialog__fact-value">{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </>
  );
}

export function LlmRunDialog({
  run,
  openToken,
  onCloseAction,
}: {
  run: LlmResearchRun | null;
  openToken: number;
  onCloseAction: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [detail, setDetail] = useState<DetailResult | null>(null);
  const runId = run?.run_id ?? null;
  const requestKey = runId ? `${runId}:${openToken}:${attempt}` : null;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (run && !dialog.open) {
      dialog.showModal();
    } else if (!run && dialog.open) {
      dialog.close();
    }
  }, [run]);

  const handleClose = () => {
    setDetail(null);
    setAttempt(0);
    onCloseAction();
  };

  useEffect(() => {
    if (!runId || !requestKey) return;
    const controller = new AbortController();

    const load = async () => {
      try {
        const response = await fetch(
          `/api/llm/research-runs/${encodeURIComponent(runId)}`,
          { signal: controller.signal, headers: { accept: "application/json" } },
        );
        if (controller.signal.aborted) return;
        if (!response.ok) {
          let message = `HTTP ${response.status}`;
          try {
            const payload: unknown = await response.json();
            if (
              payload &&
              typeof payload === "object" &&
              "error" in payload &&
              typeof payload.error === "string"
            ) {
              message = payload.error;
            }
          } catch {
            /* keep the HTTP status message */
          }
          setDetail({ requestKey, status: "error", message });
          return;
        }
        const payload = (await response.json()) as LlmResearchRun;
        if (controller.signal.aborted) return;
        setDetail({ requestKey, status: "ready", run: payload });
      } catch (error) {
        if (controller.signal.aborted) return;
        setDetail({
          requestKey,
          status: "error",
          message: error instanceof Error ? error.message : "Unknown error",
        });
      }
    };

    void load();
    return () => controller.abort();
  }, [requestKey, runId]);

  const isLoading = requestKey !== null && detail?.requestKey !== requestKey;
  const errorMessage =
    requestKey !== null &&
    detail?.requestKey === requestKey &&
    detail.status === "error"
      ? detail.message
      : null;
  const loadedRun =
    requestKey !== null &&
    detail?.requestKey === requestKey &&
    detail.status === "ready"
      ? detail.run
      : null;

  const headerRun = loadedRun ?? run;
  const stage = headerRun?.stage?.trim() || "—";
  const home = headerRun?.home_team?.trim() || "TBD";
  const away = headerRun?.away_team?.trim() || "TBD";
  const contextParts = [
    headerRun?.competition?.trim(),
    headerRun?.kickoff_at
      ? `${formatKickoff(headerRun.kickoff_at)} HKT`
      : null,
  ].filter((value): value is string => Boolean(value));

  return (
    <dialog
      ref={dialogRef}
      className="llm-dialog"
      aria-labelledby="llm-run-dialog-title"
      onClose={handleClose}
      onClick={(event) => {
        if (event.target === dialogRef.current) dialogRef.current?.close();
      }}
    >
      {run ? (
        <>
          <header className="llm-dialog__head">
            <div className="llm-dialog__head-main">
              <p className="llm-dialog__kicker">ANALYST REPORT · {stage}</p>
              <h2 className="llm-dialog__title" id="llm-run-dialog-title">
                {home} vs {away}
                {contextParts.length > 0 ? (
                  <span className="llm-dialog__context">
                    {contextParts.join(" · ")}
                  </span>
                ) : null}
              </h2>
            </div>
            <div className="llm-dialog__head-side">
              <StatusTag status={headerRun?.status} />
              <button
                type="button"
                className="llm-dialog__close"
                aria-label="關閉"
                onClick={() => dialogRef.current?.close()}
              >
                ×
              </button>
            </div>
          </header>

          <div className="llm-dialog__body" aria-busy={isLoading}>
            {isLoading ? (
              <p className="llm-dialog__notice">載入中…</p>
            ) : errorMessage !== null ? (
              <div className="alert llm-dialog__alert" role="status">
                <span className="alert__tag">degraded</span>
                <div>
                  <p className="alert__title">無法載入 run 詳情</p>
                  <p className="alert__body">
                    <code>/api/llm/research-runs/{runId}</code> — {errorMessage}
                  </p>
                  <button
                    type="button"
                    className="button llm-dialog__retry"
                    onClick={() => setAttempt((current) => current + 1)}
                  >
                    重試
                  </button>
                </div>
              </div>
            ) : loadedRun ? (
              <>
                <section className="llm-dialog__section">
                  <h3 className="llm-dialog__section-title">決策摘要</h3>
                  <DecisionSummary run={loadedRun} />
                </section>

                <section className="llm-dialog__section">
                  <h3 className="llm-dialog__section-title">詳細報告</h3>
                  <DetailReport run={loadedRun} />
                </section>

                <section className="llm-dialog__section">
                  <h3 className="llm-dialog__section-title">分析師決策</h3>
                  <AnalystTable run={loadedRun} />
                </section>

                <section className="llm-dialog__section">
                  <h3 className="llm-dialog__section-title">風控決定</h3>
                  <RiskDecision risk={loadedRun.risk ?? null} />
                </section>

                <footer className="llm-dialog__meta">
                  <span>run · {loadedRun.run_id ?? "—"}</span>
                  <span>model · {loadedRun.model_version ?? "—"}</span>
                  <span>prompt · {loadedRun.prompt_version ?? "—"}</span>
                  <span>provider · {loadedRun.provider ?? "—"}</span>
                  <span>created · {formatDateTime(loadedRun.created_at)}</span>
                </footer>
              </>
            ) : null}
          </div>
        </>
      ) : null}
    </dialog>
  );
}
