import json

from sqlalchemy import create_engine

import packages.db.models  # noqa: F401
from packages.db.base import Base
from packages.db.session import build_session_factory, session_scope
from packages.ingest.dry_run import run_dry_run


def main() -> None:
    engine = create_engine("sqlite+pysqlite:///dry_run.db")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        result = run_dry_run(session)
    print(
        json.dumps(
            {
                "match_id": result.match_id,
                "bet_id": result.bet_id,
                "settlement_status": result.settlement_status,
                "payout": str(result.payout),
                "roi": str(result.roi),
                "clv": None if result.clv is None else str(result.clv),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
