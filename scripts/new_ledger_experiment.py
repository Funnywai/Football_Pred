"""Open a new paper-ledger experiment without deleting prior bets.

Usage:
    uv run python scripts/new_ledger_experiment.py \
        --label poisson-v2-g2 \
        --model-version poisson-v2 \
        --strategy-version g2
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal

from packages.db.session import build_engine, build_session_factory, session_scope
from packages.ledger.experiments import active_experiment, create_next_experiment
from packages.shared.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a new paper-ledger experiment")
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--lane",
        default="deterministic",
        choices=("deterministic", "llm", "challenger"),
    )
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--strategy-version", required=True)
    parser.add_argument("--initial-bankroll", type=Decimal, default=None)
    args = parser.parse_args()

    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with session_scope(factory) as session:
            previous = active_experiment(session, args.lane)
            experiment = create_next_experiment(
                session,
                label=args.label,
                model_version=args.model_version,
                strategy_version=args.strategy_version,
                initial_bankroll=(
                    args.initial_bankroll
                    if args.initial_bankroll is not None
                    else settings.initial_bankroll
                ),
                lane=args.lane,
            )
            print(
                json.dumps(
                    {
                        "previous_experiment_id": (
                            str(previous.id) if previous is not None else None
                        ),
                        "experiment_id": str(experiment.id),
                        "label": experiment.label,
                        "lane": experiment.lane,
                        "model_version": experiment.model_version,
                        "strategy_version": experiment.strategy_version,
                        "account_id": experiment.account_id,
                        "initial_bankroll": str(experiment.initial_bankroll),
                    },
                    indent=2,
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
