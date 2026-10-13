import json
from datetime import UTC, datetime

from ml_helpers import make_db, seed_context, seed_finished_match, seed_team
from sqlalchemy import select

from app.db.models import MatchFeature
from app.ml.predict import upsert_feature

KICKOFF = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)


async def test_upsert_feature_stores_nan_as_json_null(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home FC")
            away = await seed_team(session, "Away FC")
            match = await seed_finished_match(
                session,
                league,
                season,
                home,
                away,
                match_id_label="M-JSON",
                kickoff=KICKOFF,
                home_score=1,
                away_score=0,
            )
            await upsert_feature(
                session,
                match.id,
                {"elo_home": 1500.0, "market_home": float("nan"), "has_market_prior": 0.0},
            )
            await session.commit()
        async with db.session_factory() as session:
            stored = (await session.execute(select(MatchFeature))).scalar_one()
        assert stored.features["market_home"] is None
        assert stored.features["elo_home"] == 1500.0
        assert json.dumps(stored.features, allow_nan=False)
    finally:
        await db.dispose()


async def test_upsert_feature_rewrites_an_existing_row(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home FC")
            away = await seed_team(session, "Away FC")
            match = await seed_finished_match(
                session,
                league,
                season,
                home,
                away,
                match_id_label="M-JSON2",
                kickoff=KICKOFF,
                home_score=1,
                away_score=0,
            )
            await upsert_feature(session, match.id, {"elong_home": 1.0, "market_home": float("nan")})
            await upsert_feature(session, match.id, {"market_home": 0.42, "has_market_prior": 1.0})
            await session.commit()
        async with db.session_factory() as session:
            stored = (await session.execute(select(MatchFeature))).scalar_one()
        assert stored.features == {"market_home": 0.42, "has_market_prior": 1.0}
    finally:
        await db.dispose()
