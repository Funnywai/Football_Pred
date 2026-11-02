from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import cast

from packages.adapters.base import AdapterError
from packages.adapters.football_data_co_uk import (
    LEAGUE_FILE_CODES,
    FootballDataCoUkAdapter,
    HistoricalMatchRow,
)
from packages.backtest.experiments import (
    HOLDOUT_SEASON,
    TRAIN_SEASONS,
    VALIDATION_SEASON,
    BlockMetrics,
    ExperimentReport,
    load_historical_rows,
    run_experiments,
    run_feature_experiments,
)


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _metrics_payload(metrics: BlockMetrics) -> dict[str, object]:
    calibration = {
        outcome: [
            {
                "bin": calibration_bin.bin_index,
                "count": calibration_bin.count,
                "positives": calibration_bin.positives,
                "predicted_mean": str(calibration_bin.predicted_mean),
                "observed_rate": str(calibration_bin.observed_rate),
            }
            for calibration_bin in bins
        ]
        for outcome, bins in metrics.calibration.items()
    }
    return {
        "block": metrics.block,
        "matches": metrics.matches,
        "matches_with_market": metrics.matches_with_market,
        "brier_model": _decimal(metrics.brier_model),
        "brier_market": _decimal(metrics.brier_market),
        "log_loss_model": _decimal(metrics.log_loss_model),
        "log_loss_market": _decimal(metrics.log_loss_market),
        "bets_placed": metrics.bets_placed,
        "roi_model": _decimal(metrics.roi_model),
        "calibration": calibration,
    }


def _report_payload(report: ExperimentReport) -> dict[str, object]:
    return {
        "variant": report.variant,
        "params": dict(report.params),
        "train_matches": report.train_matches,
        "validation_matches": report.validation_matches,
        "holdout_matches": report.holdout_matches,
        "selected_params": dict(report.selected_params),
        "validation": _metrics_payload(report.validation),
        "holdout": _metrics_payload(report.holdout),
        "notes": report.notes,
    }


def _read_csv_dir(
    csv_dir: Path,
    competition: str,
    seasons: Sequence[int],
) -> list[HistoricalMatchRow]:
    file_code = LEAGUE_FILE_CODES.get(competition)
    if file_code is None:
        raise FileNotFoundError(f"no football-data.co.uk file mapping for {competition}")
    rows: list[HistoricalMatchRow] = []
    for season in seasons:
        candidates = [
            csv_dir / f"{file_code}_{season}.csv",
            csv_dir / f"{file_code}-{season}.csv",
        ]
        if len(seasons) == 1:
            candidates.append(csv_dir / f"{file_code}.csv")
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is None:
            raise FileNotFoundError(f"missing {file_code}_{season}.csv in {csv_dir}")
        rows.extend(
            FootballDataCoUkAdapter.parse_csv(
                path.read_text(encoding="utf-8-sig"), competition, season
            )
        )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Leakage-safe multi-season EPL HAD model experiments."
    )
    _ = parser.add_argument(
        "--seasons",
        type=int,
        nargs="+",
        default=[2021, 2022, 2023, 2024, 2025],
    )
    _ = parser.add_argument("--competition", default="EPL")
    _ = parser.add_argument("--min-train", type=int, default=50)
    _ = parser.add_argument(
        "--features",
        action="store_true",
        help="Also evaluate Elo and rest-adjusted variants.",
    )
    _ = parser.add_argument(
        "--csv-dir",
        type=Path,
        default=None,
        help="Directory with E0_<season>.csv files; skips the network fetch.",
    )
    args = parser.parse_args(argv)
    seasons = cast(list[int], args.seasons)
    competition = cast(str, args.competition)
    min_train = cast(int, args.min_train)
    csv_dir = cast(Path | None, args.csv_dir)
    features = cast(bool, args.features)

    if min_train < 0:
        parser.error("--min-train must be non-negative")

    try:
        if csv_dir is not None:
            rows = _read_csv_dir(csv_dir, competition, seasons)
            source = f"local csv dir {csv_dir}"
        else:
            rows = load_historical_rows(seasons, competition)
            source = "football-data.co.uk"
    except (AdapterError, OSError) as exc:
        print(f"model_experiments: unable to load rows: {exc}", file=sys.stderr)
        return 1

    reports = (
        run_feature_experiments(rows, min_train=min_train)
        if features
        else run_experiments(rows, min_train=min_train)
    )
    payload = {
        "source": source,
        "competition": competition,
        "seasons": seasons,
        "split": {
            "train": list(TRAIN_SEASONS),
            "validation": VALIDATION_SEASON,
            "holdout": HOLDOUT_SEASON,
        },
        "market_baseline": "B365/PS proportional de-vig (closing odds, not HKJC)",
        "min_train": min_train,
        "feature_variants": features,
        "rows_total": len(rows),
        "reports": [_report_payload(report) for report in reports],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
