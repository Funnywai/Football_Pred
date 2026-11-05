from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine

from packages.db.session import build_session_factory
from packages.evaluation.report import build_evaluation_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the P0 evidence-chain report.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("FP_DATABASE_URL"),
        help="SQLAlchemy URL (or FP_DATABASE_URL).",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or FP_DATABASE_URL is required")
    engine = create_engine(args.database_url, pool_pre_ping=True, future=True)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            report = build_evaluation_report(session)
    finally:
        engine.dispose()
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
