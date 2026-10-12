"""Sub-system C end-to-end: champion predictions → bets → settlement → summary."""

from datetime import UTC, datetime, timedelta

import pytest
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team
from sqlalchemy import select

from app.config import Settings
from app.db.models import LedgerBet, ModelVersion, Prediction
from app.ml.dataset import build_dataset
from app.ml.models import TARGET_1X2, save_artifact, train_1x2
from app.ml.predict import (
    load_champion,
    load_upcoming_matches,
    predict_match,
    upsert_predictions,
)
from app.ml.registry import maybe_promote, register_challenger
from app.services.ledger import equity_curve, ledger_update
from app.services.ledger import summary as ledger_summary

HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}
HDC = {"lines": [{"condition": "-0.5", "main": True, "combinations": [
    {"str": "H", "currentOdds": "2.0"}, {"str": "A", "currentOdds": "1.9"}]}]}


async def _value_prediction_keys(db) -> set[tuple[int, str, str]]:
    """Champion predictions with a Kelly fraction (the exact set placement must bet)."""
    async with db.session_factory() as session:
        champion = (
            await session.execute(select(ModelVersion).where(ModelVersion.status == "champion"))
        ).scalar_one()
        rows = (
            (
                await session.execute(
                    select(Prediction).where(
                        Prediction.model_version_id == champion.id,
                        Prediction.recommended_fraction > 0,
                    )
                )
            )
            .scalars()
            .all()
        )
        return {(row.match_id, row.target, row.outcome) for row in rows}


async def test_end_to_end_predict_place_settle(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        settings = Settings(
            _env_file=None,
            ml_min_train_rows=20,
            ml_history_from_year=2020,
            ml_value_edge_threshold=0.0,
            ml_artifact_dir=str(tmp_path / "artifacts"),
        )
        base = datetime.now(UTC) - timedelta(days=60)
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            teams = [await seed_team(session, f"T{i}") for i in range(6)]
            for index in range(60):
                await seed_finished_match(
                    session, league, season, teams[index % 6], teams[(index + 1) % 6],
                    match_id_label=f"M{index}", kickoff=base + timedelta(days=index),
                    home_score=index % 4, away_score=(index + 1) % 3,
                    had_payload=HAD, hdc_payload=HDC,
                )
            upcoming = await seed_finished_match(
                session, league, season, teams[0], teams[1],
                match_id_label="M_UP", kickoff=base + timedelta(days=90),
                home_score=0, away_score=0,
                had_payload=HAD, hdc_payload=HDC,
            )
            upcoming.status = "scheduled"
            await session.commit()

        async with db.session_factory() as session:
            dataset = await build_dataset(session, settings)
            model = train_1x2(dataset.train, dataset.calibration, dataset.eval)
            artifact = tmp_path / "champ.joblib"
            save_artifact(model, artifact)
            version = await register_challenger(
                session, TARGET_1X2, "lightgbm", {}, model.metrics, str(artifact)
            )
            await maybe_promote(session, version, 0.0)
            await session.commit()

        async with db.session_factory() as session:
            champion = await load_champion(session, TARGET_1X2)
            assert champion is not None
            now = base + timedelta(days=89)
            matches = await load_upcoming_matches(session, settings, now)
            assert len(matches) == 1
            rows = await predict_match(session, matches[0], champion, None, settings)
            written = await upsert_predictions(session, rows)
            await session.commit()
            assert written == 3

        expected = await _value_prediction_keys(db)

        # Run 1: settle(nothing pending) + place
        async with db.session_factory() as session:
            processed = await ledger_update(db.session_factory, settings)
        async with db.session_factory() as session:
            bets = (await session.execute(select(LedgerBet))).scalars().all()
            champion_id = await _champion_id(db)
            assert all(b.model_version_id == champion_id for b in bets)
            assert {(b.match_id, b.target, b.outcome) for b in bets} == expected
            assert processed == len(bets)
            for bet in bets:
                assert 10.0 <= bet.stake <= 0.05 * 1000.0
                assert bet.status == "pending"
                assert bet.kelly_multiplier == pytest.approx(0.5)
                assert bet.bankroll_at_place == pytest.approx(1000.0)
        # Run 2: the confirmed 0:0 result settles every pending bet (D wins; H/A
        # lose) and placement stays idempotent — settled N, placed 0.
        async with db.session_factory() as session:
            processed = await ledger_update(db.session_factory, settings)
        async with db.session_factory() as session:
            bets = (await session.execute(select(LedgerBet))).scalars().all()
            for bet in bets:
                assert bet.status == ("won" if bet.outcome == "D" else "lost")
                assert bet.result_source == "hkjc"
                assert bet.settled_at is not None
            assert processed == len(bets)  # settled everything, placed nothing
            values = await ledger_summary(session, settings)
            realized = sum(bet.profit if bet.profit is not None else 0.0 for bet in bets)
            assert values.realized_profit == pytest.approx(realized)
            assert values.bankroll == pytest.approx(1000.0 + realized)
            assert values.n_settled == len(bets)
            assert values.n_open == 0
            curve = [p.bankroll for p in await equity_curve(session, settings)]
            assert len(curve) == len(bets) + 2  # initial + one event per bet + current
            assert curve[0] == 1000.0
            assert curve[-1] == pytest.approx(1000.0 + realized)

        # Run 3: steady state — fully idempotent, nothing left to do.
        async with db.session_factory() as session:
            assert await ledger_update(db.session_factory, settings) == 0
    finally:
        await db.dispose()


async def _champion_id(db) -> int:
    async with db.session_factory() as session:
        return (
            (
                await session.execute(
                    select(ModelVersion).where(ModelVersion.status == "champion")
                )
            )
            .scalar_one()
            .id
        )
