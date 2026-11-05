"use client";

import { useMemo, useState } from "react";

import type { EndpointResult } from "@/lib/api";
import {
  formatKickoff,
  formatOdds,
  formatSignedRatioPercent,
  hktDateKey,
  probabilitiesToPercents,
} from "@/lib/format";
import type { LlmPrediction } from "@/lib/llm-types";

import { DayNavigator } from "./day-navigator";
import { TableFrame } from "./table-frame";
import {
  DataWarning,
  EmptyState,
  MatchCell,
  Panel,
  SectionHeader,
  StatusTag,
} from "./ui";

function ProbabilityTriplet({
  probabilities,
}: {
  probabilities: LlmPrediction["probabilities"];
}) {
  const values = probabilitiesToPercents(probabilities ?? {});
  return (
    <div className="triplet">
      {(["H", "D", "A"] as const).map((side) => (
        <span className="triplet__row" key={side}>
          <span className="triplet__label">{side}</span>
          <span className="triplet__value">
            {values[side] === null ? "—" : `${values[side].toFixed(1)}%`}
          </span>
        </span>
      ))}
    </div>
  );
}

function EvTriplet({ prediction }: { prediction: LlmPrediction }) {
  return (
    <div className="triplet">
      {(["H", "D", "A"] as const).map((side) => (
        <span className="triplet__row" key={side}>
          <span className="triplet__label">{side}</span>
          <span className="triplet__value">
            {formatSignedRatioPercent(prediction.ev?.[side])}
          </span>
        </span>
      ))}
    </div>
  );
}

export function LlmPredictionsSection({
  result,
}: {
  result: EndpointResult<LlmPrediction[]>;
}) {
  const predictions = useMemo(
    () => (Array.isArray(result.data) ? result.data : []),
    [result.data],
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
            .map((row) => hktDateKey(row.kickoff_at))
            .filter((key): key is string => Boolean(key)),
        ),
      ).sort((left, right) => right.localeCompare(left)),
    [sorted],
  );
  const [dayIndex, setDayIndex] = useState(0);
  const selectedDay = dayKeys[dayIndex] ?? null;
  const visible = sorted.filter((row) => hktDateKey(row.kickoff_at) === selectedDay);

  return (
    <section id="llm-predictions" className="section" aria-labelledby="llm-predictions-title">
      <SectionHeader
        index="04"
        kicker="LLM ensemble output"
        title="Predictions"
        meta={result.error ? "feed unavailable" : `${visible.length} / ${predictions.length} rows`}
      />

      {result.error ? (
        <DataWarning
          label="LLM predictions"
          endpoint="/llm/predictions"
          error={result.error}
        />
      ) : null}

      {predictions.length === 0 && !result.error ? (
        <EmptyState>No LLM predictions have been persisted yet.</EmptyState>
      ) : null}

      {predictions.length > 0 ? (
        <Panel
          title="Prediction feed"
          kicker="Newest day first"
          meta="LLM probabilities · odds · EV · paper decision"
          bodyClassName="panel__body--flush"
        >
          <div className="prediction-day-nav">
            <DayNavigator
              dayKey={selectedDay}
              dayIndex={dayIndex}
              dayCount={dayKeys.length}
              onFirst={() => setDayIndex(0)}
              onPrevious={() =>
                setDayIndex((current) => Math.min(dayKeys.length - 1, current + 1))
              }
              onNext={() => setDayIndex((current) => Math.max(0, current - 1))}
            />
          </div>
          <TableFrame label="LLM ensemble predictions" wide>
            <table className="table--llm-predictions">
              <caption className="sr-only">
                LLM ensemble predictions with probabilities, odds, expected value and
                paper-bet decision
              </caption>
              <thead>
                <tr>
                  <th scope="col">Match</th>
                  <th scope="col">Kickoff (HKT)</th>
                  <th scope="col">Model probability</th>
                  <th scope="col">Odds</th>
                  <th scope="col">EV</th>
                  <th scope="col">Model</th>
                  <th scope="col">Decision</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((prediction, index) => (
                  <tr key={`${prediction.match_id ?? "llm"}-${index}`}>
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
                      <ProbabilityTriplet probabilities={prediction.probabilities} />
                    </td>
                    <td>
                      <div className="triplet">
                        {(["H", "D", "A"] as const).map((side) => (
                          <span className="triplet__row" key={side}>
                            <span className="triplet__label">{side}</span>
                            <span className="triplet__value">
                              {formatOdds(prediction.odds?.[side])}
                            </span>
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>
                      <EvTriplet prediction={prediction} />
                    </td>
                    <td>
                      <span className="mono cell-model">
                        {prediction.model_version ?? "—"}
                      </span>
                    </td>
                    <td>
                      <StatusTag status={prediction.decision_status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableFrame>
        </Panel>
      ) : null}
    </section>
  );
}
