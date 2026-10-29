from ops_helpers import make_app, make_client, make_db, seed_data


async def test_ops_data_keys_and_model_params(tmp_path):
    db = await make_db(tmp_path)
    try:
        await seed_data(db)
        async with make_client(make_app(db)) as client:
            response = await client.get("/ops/data")
            assert response.status_code == 200
            body = response.json()
            assert set(body) == {
                "table_counts",
                "odds",
                "match_features",
                "results",
                "model_versions",
                "alembic_revision",
                "last_arrived",
            }
            assert set(body["table_counts"]) == {
                "leagues",
                "seasons",
                "teams",
                "matches",
                "odds_snapshots",
                "results",
                "predictions",
                "match_features",
                "model_versions",
                "ledger_bets",
                "shadow_ledger_bets",
                "agent_bets",
                "agent_decisions",
                "analyst_briefs",
                "ingestion_runs",
            }
            assert body["table_counts"]["odds_snapshots"] == 1
            assert body["odds"]["total"] == 1
            assert body["odds"]["last_captured_at"] == "2026-10-12T09:00:00+00:00"
            assert body["odds"]["by_source_type"] == [
                {
                    "source": "hkjc",
                    "odds_type": "HAD",
                    "inplay": False,
                    "count": 1,
                    "max_captured_at": "2026-10-12T09:00:00+00:00",
                }
            ]
            assert body["match_features"] == {
                "count": 1,
                "max_built_at": "2026-10-12T10:00:00+00:00",
            }
            assert body["results"] == {
                "total": 1,
                "confirmed": 1,
                "payout_confirmed": 1,
                "max_confirmed_at": "2026-10-12T13:00:00+00:00",
            }
            assert body["model_versions"][0]["params"] == {"num_trees": 42}
            assert body["model_versions"][0]["created_at"] == "2026-10-12T12:00:00+00:00"
            assert body["model_versions"][0]["promoted_at"] == "2026-10-12T12:05:00+00:00"
            assert body["alembic_revision"] is None
            assert body["last_arrived"] == {
                "odds_captured_at": "2026-10-12T09:00:00+00:00",
                "features_built_at": "2026-10-12T10:00:00+00:00",
                "results_confirmed_at": "2026-10-12T13:00:00+00:00",
                "model_created_at": "2026-10-12T12:00:00+00:00",
                "model_promoted_at": "2026-10-12T12:05:00+00:00",
            }
    finally:
        await db.dispose()


async def test_existing_routes_unaffected(tmp_path):
    db = await make_db(tmp_path)
    try:
        async with make_client(make_app(db)) as client:
            assert (await client.get("/health")).json() == {"status": "ok"}
            assert (await client.get("/matches")).json() == []
            assert (await client.get("/models")).json() == []
            assert (await client.get("/bets/summary")).status_code == 200
    finally:
        await db.dispose()
