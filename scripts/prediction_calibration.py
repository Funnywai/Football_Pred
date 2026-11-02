from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text

from packages.backtest.walk_forward import (
    HAD_OUTCOMES,
    calibration_bins,
    multiclass_brier,
    multiclass_log_loss,
)

D = Decimal


def _season_label(day: date) -> str:
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def _result(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


@dataclass
class _Group:
    model_version: str
    competition: str
    season: str
    matches: int = 0
    brier: Decimal = field(default_factory=Decimal)
    log_loss: Decimal = field(default_factory=Decimal)
    observations: list[tuple[dict[str, Decimal], str]] = field(default_factory=list)

    def add(
        self,
        probabilities: dict[str, Decimal],
        actual: str,
    ) -> None:
        self.matches += 1
        self.brier += multiclass_brier(probabilities, actual)
        self.log_loss += multiclass_log_loss(probabilities, actual)
        self.observations.append((probabilities, actual))

    def as_dict(self) -> dict[str, object]:
        count = D(self.matches) if self.matches else D(1)
        return {
            "model_version": self.model_version,
            "competition": self.competition,
            "season": self.season,
            "matches": self.matches,
            "brier": str(self.brier / count),
            "log_loss": str(self.log_loss / count),
            "calibration": {
                outcome: [
                    {
                        "bin": item.bin_index,
                        "count": item.count,
                        "predicted_mean": str(item.predicted_mean),
                        "observed_rate": str(item.observed_rate),
                    }
                    for item in bins
                ]
                for outcome, bins in calibration_bins(self.observations).items()
            },
        }


def run(engine: Any) -> dict[str, object]:
    query = text(
        """
        SELECT
            mp.match_id,
            mp.outcome,
            mp.probability,
            mp.model_version,
            mp.decision_at,
            m.kickoff_at,
            m.home_goals_90,
            m.away_goals_90,
            competition.code AS competition
        FROM model_predictions mp
        JOIN matches m ON m.id = mp.match_id
        JOIN competitions competition ON competition.id = m.competition_id
        WHERE mp.market = 'HAD'
          AND mp.line_key = '0.0'
          AND m.status = 'finished'
          AND m.home_goals_90 IS NOT NULL
          AND m.away_goals_90 IS NOT NULL
        ORDER BY mp.match_id, mp.decision_at
        """
    )
    with engine.connect() as connection:
        rows = connection.execute(query).mappings().all()

    by_match: dict[object, dict[str, object]] = defaultdict(dict)
    for row in rows:
        match_id = row["match_id"]
        previous = by_match[match_id].get(str(row["outcome"]))
        if previous is None or row["decision_at"] >= previous["decision_at"]:
            by_match[match_id][str(row["outcome"])] = row

    groups: dict[tuple[str, str, str], _Group] = {}
    for match_id, outcomes in by_match.items():
        # Keep the latest decision run only. The query is ordered by decision_at, so
        # the last observation for an outcome wins.
        latest_by_outcome: dict[str, dict[str, object]] = {}
        for outcome, row in outcomes.items():
            previous = latest_by_outcome.get(outcome)
            if previous is None or row["decision_at"] >= previous["decision_at"]:
                latest_by_outcome[outcome] = row
        if set(latest_by_outcome) != set(HAD_OUTCOMES):
            continue
        sample = next(iter(latest_by_outcome.values()))
        actual = _result(int(sample["home_goals_90"]), int(sample["away_goals_90"]))
        probabilities = {
            outcome: D(str(latest_by_outcome[outcome]["probability"]))
            for outcome in HAD_OUTCOMES
        }
        season = _season_label(sample["kickoff_at"].date())
        key = (
            str(sample["model_version"]),
            str(sample["competition"]),
            season,
        )
        group = groups.get(key)
        if group is None:
            group = _Group(
                model_version=str(sample["model_version"]),
                competition=str(sample["competition"]),
                season=season,
            )
            groups[key] = group
        group.add(probabilities, actual)

    return {
        "source": "model_predictions + finished matches (no bet required)",
        "matches": sum(group.matches for group in groups.values()),
        "groups": [group.as_dict() for group in sorted(groups.values(), key=lambda g: (g.competition, g.season))],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate all saved HAD predictions against finished match results."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("FP_DATABASE_URL"),
        help="SQLAlchemy URL (or FP_DATABASE_URL).",
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or FP_DATABASE_URL is required")
    engine = create_engine(args.database_url, pool_pre_ping=True, future=True)
    try:
        report = run(engine)
    finally:
        engine.dispose()
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
