"use client";

import { useMemo, useState } from "react";

import {
  asNumber,
  formatKickoff,
  formatNumber,
  formatOdds,
  formatSignedRatioPercent,
  hktDateKey,
  probabilitiesToPercents,
} from "@/lib/format";
import { buildPredictionsTsv } from "@/lib/predictions-export";
import { DayNavigator } from "./day-navigator";
import type { EndpointResult } from "@/lib/api";
import type { Prediction } from "@/lib/types";

import { CopyTableButton } from "./copy-table-button";
import { DataWarning, EmptyState, MatchCell, Panel, SectionHeader, StatusTag } from "./ui";
import { TableFrame } from "./table-frame";

function ProbabilityCell({
  probabilities,
}: {
  probabilities: Prediction["probabilities"];
}) {
  const percents = probabilitiesToPercents(probabilities);
  const values = [percents.H, percents.D, percents.A];
  if (values.every((value) => value === null)) {
    return <span className="text-muted">—</span>;
  }
  const total = values.reduce<number>((sum, value) => sum + (value ?? 0), 0);
  const width = (value: number | null) => (total > 0 ? ((value ?? 0) / total) * 100 : 0);

  return (
    <div className="prob">
      <div className="prob__bar" aria-hidden="true">
        <span className="prob__seg prob__seg--h" style={{ width: `${width(percents.H)}%` }} />
        <span className="prob__seg prob__seg--d" style={{ width: `${width(percents.D)}%` }} />
        <span className="prob__seg prob__seg--a" style={{ width: `${width(percents.A)}%` }} />
      </div>
      <div className="prob__values">
        <span>
          <b>H</b> {percents.H === null ? "—" : `${formatNumber(percents.H, 1)}%`}
        </span>
        <span>
          <b>D</b> {percents.D === null ? "—" : `${formatNumber(percents.D, 1)}%`}
        </span>
        <span>
          <b>A</b> {percents.A === null ? "—" : `${formatNumber(percents.A, 1)}%`}
        </span>
      </div>
    </div>
  );
}

function ResultCell({ prediction }: { prediction: Prediction }) {
  const status = (prediction.status ?? "").toLowerCase();
  const finished = status === "finished";
  const live = status === "live";
  const home90 = asNumber(prediction.home_goals_90);
  const away90 = asNumber(prediction.away_goals_90);
  const home = home90 ?? asNumber(prediction.home_goals_final);
  const away = away90 ?? asNumber(prediction.away_goals_final);

  if ((!finished && !live) || home === null || away === null) {
    return <span className="text-muted">—</span>;
  }

  return (
    <span className="result">
      <span className="result__score">
        {home}–{away}
      </span>
      <abbr
        className="result__label"
        title={
          live
            ? "Live score"
            : home90 === null
              ? "After extra time"
              : "Full time"
        }
      >
        {live ? "LIVE" : home90 === null ? "AET" : "FT"}
      </abbr>
    </span>
  );
}

function Triplet({
  values,
  format,
  toneBySign = false,
}: {
  values: Array<string | number | null | undefined>;
  format: (value: string | number | null | undefined) => string;
  toneBySign?: boolean;
}) {
  const labels = ["H", "D", "A"];
  return (
    <div className="triplet">
      {values.map((value, index) => {
        const numeric = asNumber(value);
        const tone =
          toneBySign && numeric !== null
            ? numeric > 0
              ? "text-positive"
              : numeric < 0
                ? "text-negative"
                : "text-muted"
            : "";
        return (
          <span className="triplet__row" key={labels[index]}>
            <span className="triplet__label">{labels[index]}</span>
            <span className={`triplet__value ${tone}`}>{format(value)}</span>
          </span>
        );
      })}
    </div>
  );
}

export function PredictionsSection({
  result,
  v2Result,
}: {
  result: EndpointResult<Prediction[]>;
  v2Result: EndpointResult<Prediction[]>;
}) {
  const predictions = useMemo(
    () => (Array.isArray(result.data) ? result.data : []),
    [result.data],
  );
  const v2Rows = useMemo(
    () => (Array.isArray(v2Result.data) ? v2Result.data : []),
    [v2Result.data],
  );
  const v2ByMatch = new Map(
    v2Rows
      .filter((row) => Boolean(row.match_id))
      .map((row) => [row.match_id as string, row]),
  );
  const sorted = useMemo(
    () =>
      [...predictions].sort(
        (left, right) =>
          Date.parse(right.kickoff_at ?? "") - Date.parse(left.kickoff_at ?? ""),
      ),
    [predictions],
  );
  const dayKeys = useMemo(
    () =>
      Array.from(
        new Set(
          sorted
            .map((prediction) => hktDateKey(prediction.kickoff_at))
            .filter((key): key is string => Boolean(key)),
        ),
      ).sort((left, right) => right.localeCompare(left)),
    [sorted],
  );
  const [dayIndex, setDayIndex] = useState(0);
  const selectedDay = dayKeys[dayIndex] ?? null;
  const visiblePredictions = useMemo(
    () =>
      sorted.filter((prediction) => hktDateKey(prediction.kickoff_at) === selectedDay),
    [sorted, selectedDay],
  );
  const copyText =
    visiblePredictions.length > 0 ? buildPredictionsTsv(visiblePredictions) : "";
  const researchOnly = predictions.some(
    (prediction) => prediction.decision_status === "prediction_only",
  );

  return (
    <section id="predictions" className="section" aria-labelledby="predictions-title">
      <SectionHeader
        index="02"
        kicker="Model output"
        title="Predictions"
        meta={result.error ? "feed unavailable" : `${predictions.length} rows · H/D/A`}
      />

      {result.error ? (
        <DataWarning
          label="Predictions"
          endpoint="/dashboard/predictions?limit=50"
          error={result.error}
        />
      ) : null}

      {predictions.length === 0 && !result.error ? (
        <EmptyState>No predictions returned. Run the model pipeline to populate this feed.</EmptyState>
      ) : null}

      {predictions.length > 0 ? (
        <Panel
          title="Prediction feed"
          kicker="Newest day first"
          meta={
            <div className="panel__meta-group">
              <span>
                {visiblePredictions.length} / {predictions.length} rows · HKT day
              </span>
              {copyText ? <CopyTableButton text={copyText} label="Copy" /> : null}
            </div>
          }
          bodyClassName="panel__body--flush"
        >
          {researchOnly ? (
            <p className="prediction-caveat">
              EV is a research diagnostic (model probability × T-30m odds − 1),
              not a bet recommendation. Rows marked prediction only predate the
              all-competition paper policy and do not enter the ledger.
            </p>
          ) : null}
          <div className="prediction-day-nav">
            <DayNavigator
              dayKey={selectedDay}
              dayIndex={dayIndex}
              dayCount={dayKeys.length}
              onFirst={() => setDayIndex(0)}
              onPrevious={() => setDayIndex((current) => Math.min(dayKeys.length - 1, current + 1))}
              onNext={() => setDayIndex((current) => Math.max(0, current - 1))}
            />
          </div>
          <TableFrame label="Latest model predictions" wide>
            <table className="table--predictions">
              <caption className="sr-only">
                Latest model predictions with result, probabilities, odds, expected
                value and bet decision
              </caption>
              <thead>
                <tr>
                  <th scope="col">Match</th>
                  <th scope="col">Kickoff (HKT)</th>
                  <th scope="col">Result</th>
                  <th scope="col">Model probability</th>
                  <th scope="col">Odds</th>
                  <th scope="col">EV V1</th>
                  <th scope="col">Model V1</th>
                  <th scope="col">Decision V1</th>
                  <th scope="col" className="num">EV V2</th>
                  <th scope="col">Model V2</th>
                  <th scope="col">Decision V2</th>
                </tr>
              </thead>
              <tbody>
                {visiblePredictions.map((prediction, index) => {
                  const v2 = prediction.match_id
                    ? v2ByMatch.get(prediction.match_id)
                    : undefined;
                  return (
                  <tr key={`${prediction.match_id ?? "match"}-${index}`}>
                    <td>
                      <MatchCell
                        home={prediction.home_team}
                        away={prediction.away_team}
                        competition={prediction.competition}
                        matchId={prediction.match_id}
                      />
                    </td>
                    <td className="cell-time">
                      <time dateTime={prediction.kickoff_at ?? undefined}>
                        {formatKickoff(prediction.kickoff_at)}
                      </time>
                    </td>
                    <td>
                      <ResultCell prediction={prediction} />
                    </td>
                    <td>
                      <ProbabilityCell probabilities={prediction.probabilities} />
                    </td>
                    <td>
                      <Triplet
                        values={[prediction.odds?.H, prediction.odds?.D, prediction.odds?.A]}
                        format={formatOdds}
                      />
                    </td>
                    <td>
                      <Triplet
                        values={[prediction.ev?.H, prediction.ev?.D, prediction.ev?.A]}
                        format={formatSignedRatioPercent}
                        toneBySign
                      />
                    </td>
                    <td>
                      <span className="mono cell-model">{prediction.model_version ?? "—"}</span>
                    </td>
                    <td>
                      <StatusTag status={prediction.decision_status} />
                    </td>
                    <td>
                      <Triplet
                        values={[v2?.ev?.H, v2?.ev?.D, v2?.ev?.A]}
                        format={formatSignedRatioPercent}
                        toneBySign
                      />
                    </td>
                    <td>
                      <span className="mono cell-model">{v2?.model_version ?? "—"}</span>
                    </td>
                    <td>
                      {v2 ? <StatusTag status={v2.decision_status} /> : <span className="text-muted">—</span>}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </TableFrame>
        </Panel>
      ) : null}
    </section>
  );
}
