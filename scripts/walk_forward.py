from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from packages.adapters.base import AdapterError
from packages.adapters.football_data_co_uk import FootballDataCoUkAdapter
from packages.backtest.walk_forward import WalkForwardReport, run_walk_forward


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _report_payload(
    report: WalkForwardReport,
    *,
    competition: str,
    season: int,
    min_train: int,
    csv_path: Path | None,
    source_url: str | None,
) -> dict[str, object]:
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
        for outcome, bins in report.calibration.items()
    }
    return {
        "source": "football-data.co.uk",
        "source_url": source_url,
        "csv_path": None if csv_path is None else str(csv_path),
        "competition": competition,
        "season": season,
        "market_baseline": "B365/PS proportional de-vig (closing odds, not HKJC)",
        "min_train": min_train,
        "matches_total": report.matches_total,
        "matches_evaluated": report.matches_evaluated,
        "matches_skipped": report.matches_skipped,
        "matches_with_market": report.matches_with_market,
        "bets_placed": report.bets_placed,
        "brier_model": _decimal(report.brier_model),
        "brier_market": _decimal(report.brier_market),
        "log_loss_model": _decimal(report.log_loss_model),
        "log_loss_market": _decimal(report.log_loss_market),
        "roi_model": _decimal(report.roi_model),
        "model_version": report.model_version,
        "calibration": calibration,
    }


def _load_csv(args: argparse.Namespace) -> tuple[str, str | None]:
    if args.csv is not None:
        return args.csv.read_text(encoding="utf-8-sig"), None
    with FootballDataCoUkAdapter() as adapter:
        fetched = adapter.fetch_league_csv(args.competition, args.season)
    return fetched.raw_text, fetched.source_url


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="EPL HAD walk-forward validation against de-vigged market odds."
    )
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--competition", default="EPL")
    parser.add_argument("--min-train", type=int, default=50)
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Local football-data.co.uk CSV; skips the network fetch.",
    )
    args = parser.parse_args(argv)

    if args.min_train < 0:
        parser.error("--min-train must be non-negative")

    try:
        text, source_url = _load_csv(args)
    except (AdapterError, OSError) as exc:
        print(f"walk_forward: unable to load CSV: {exc}", file=sys.stderr)
        return 1

    try:
        rows = FootballDataCoUkAdapter.parse_csv(text, args.competition, args.season)
    except AdapterError as exc:
        print(f"walk_forward: invalid CSV: {exc}", file=sys.stderr)
        return 1

    report = run_walk_forward(rows, min_train=args.min_train)
    payload = _report_payload(
        report,
        competition=args.competition,
        season=args.season,
        min_train=args.min_train,
        csv_path=args.csv,
        source_url=source_url,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
