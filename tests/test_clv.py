"""Live CLV tracking and paper-validation stop/go gate tests."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team
from sqlalchemy import func, select

from app.api.main import create_app
from app.config import Settings
from app.db.models import (
    ClvRecord,
    League,
    LedgerBet,
    ModelVersion,
    Prediction,
    Result,
    Season,
    ShadowLedgerBet,
    Team,
)
from app.services.clv import summary, update_clv

KICKOFF = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

HAD = {
    "lines": [
        {
            "combinations": [
                {"str": "H", "currentOdds": "2.1"},
                {"str": "D", "currentOdds": "3.4"},
                {"str": "A", "currentOdds": "3.8"},
            ]
        }
    ]
}
FOOTBALL_DATA = {"odds": {"PS": {"close": [2.1, 3.4, 3.8]}}}

MODEL = {"H": 0.5, "D": 0.3, "A": 0.2}
CLOSING = {"H": 0.4, "D": 0.35, "A": 0.25}
PASS_MODEL = {"H": 0.55, "D": 0.30, "A": 0.15}
PASS_CLOSING = {"H": 0.50, "D": 0.28, "A": 0.22}


async def _seed_world(
    tmp_path,
    *,
    n_matches: int = 1,
    snapshot_source: str = "hkjc",
    had_payload: dict | None = HAD,
    kickoff: datetime = KICKOFF,
) -> tuple:
    db = await make_db(tmp_path)
    async with db.session_factory() as session:
        league, season = await seed_context(session)
        home = await seed_team(session, "Home")
        away = await seed_team(session, "Away")
        version = ModelVersion(
            target="1x2",
            algorithm="lightgbm",
            params={},
            metrics={},
            artifact_path="/tmp/m.joblib",
            status="champion",
        )
        session.add(version)
        await session.flush()
        match_ids: list[int] = []
        for index in range(n_matches):
            match = await seed_finished_match(
                session,
                league,
                season,
                home,
                away,
                match_id_label=f"M{index}",
                kickoff=kickoff + timedelta(days=index),
                home_score=2,
                away_score=1,
                had_payload=had_payload,
                snapshot_source=snapshot_source,
            )
            match_ids.append(match.id)
        await session.commit()
        return (
            db,
            version.id,
            match_ids,
            league.id,
            season.id,
            home.id,
            away.id,
        )


async def _add_match(
    db,
    *,
    league_id: int,
    season_id: int,
    home_id: int,
    away_id: int,
    label: str,
    source: str = "hkjc",
    payload: dict | None = HAD,
    kickoff: datetime = KICKOFF,
) -> int:
    async with db.session_factory() as session:
        league = await session.get_one(League, league_id)
        season = await session.get_one(Season, season_id)
        home = await session.get_one(Team, home_id)
        away = await session.get_one(Team, away_id)
        match = await seed_finished_match(
            session,
            league,
            season,
            home,
            away,
            match_id_label=label,
            kickoff=kickoff,
            home_score=2,
            away_score=1,
            had_payload=payload,
            snapshot_source=source,
        )
        await session.commit()
        return match.id


async def _add_predictions(
    db,
    match_ids: list[int],
    version_id: int,
    *,
    probs: dict[str, float] | None = None,
    recommended_fraction: float = 0.1,
) -> None:
    probabilities = probs or MODEL
    async with db.session_factory() as session:
        for match_id in match_ids:
            for outcome, prob in probabilities.items():
                session.add(
                    Prediction(
                        match_id=match_id,
                        target="1x2",
                        outcome=outcome,
                        model_version_id=version_id,
                        prob=prob,
                        fair_odds=1.0 / prob,
                        recommended_fraction=recommended_fraction,
                    )
                )
        await session.commit()


async def _add_clv_match(
    db,
    *,
    match_id: int,
    version_id: int,
    model_probs: dict[str, float],
    closing_probs: dict[str, float],
    label: str | None,
    source: str = "hkjc",
    is_value: bool = True,
    outcomes: tuple[str, ...] = ("H", "D", "A"),
) -> None:
    async with db.session_factory() as session:
        for outcome in outcomes:
            prediction = Prediction(
                match_id=match_id,
                target="1x2",
                outcome=outcome,
                model_version_id=version_id,
                prob=model_probs[outcome],
                fair_odds=1.0 / model_probs[outcome],
                recommended_fraction=0.1 if is_value else 0.0,
            )
            session.add(prediction)
            await session.flush()
            session.add(
                ClvRecord(
                    prediction_id=prediction.id,
                    match_id=match_id,
                    model_version_id=version_id,
                    target="1x2",
                    outcome=outcome,
                    model_prob=model_probs[outcome],
                    closing_prob=closing_probs[outcome],
                    closing_odds=1.0 / closing_probs[outcome],
                    edge=model_probs[outcome] - closing_probs[outcome],
                    beat=model_probs[outcome] >= closing_probs[outcome],
                    is_value=is_value,
                    label=label,
                    source=source,
                )
            )
        await session.commit()


async def _add_bet(
    db,
    match_id: int,
    version_id: int,
    *,
    status: str = "won",
    stake: float = 10.0,
    profit: float | None = 5.0,
) -> None:
    async with db.session_factory() as session:
        session.add(
            LedgerBet(
                match_id=match_id,
                target="1x2",
                outcome="H",
                model_version_id=version_id,
                odds=2.0,
                stake=stake,
                bankroll_at_place=1000.0,
                kelly_multiplier=0.5,
                status=status,
                profit=profit,
            )
        )
        await session.commit()


async def _add_shadow_bet(
    db,
    match_id: int,
    version_id: int,
    *,
    status: str = "won",
    stake: float = 20.0,
    profit: float | None = -20.0,
) -> None:
    async with db.session_factory() as session:
        session.add(
            ShadowLedgerBet(
                match_id=match_id,
                target="1x2",
                outcome="H",
                model_version_id=version_id,
                odds=2.0,
                stake=stake,
                bankroll_at_place=1000.0,
                kelly_multiplier=0.5,
                status=status,
                profit=profit,
            )
        )
        await session.commit()


async def test_update_clv_inserts_one_record_per_prediction(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path)
    try:
        await _add_predictions(db, match_ids, version_id)
        async with db.session_factory() as session:
            assert await update_clv(session, Settings(_env_file=None)) == 3
            await session.commit()
        async with db.session_factory() as session:
            records = (
                (await session.execute(select(ClvRecord).order_by(ClvRecord.outcome)))
                .scalars()
                .all()
            )
        assert len(records) == 3
        by_outcome = {record.outcome: record for record in records}
        assert by_outcome["H"].source == "hkjc"
        assert by_outcome["H"].label == "H"
        assert by_outcome["H"].is_value is True
        assert by_outcome["H"].beat is True
        assert by_outcome["H"].edge == pytest.approx(0.5 - 0.46077, abs=1e-4)
        assert by_outcome["A"].beat is False
    finally:
        await db.dispose()


async def test_update_clv_is_idempotent(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path)
    try:
        await _add_predictions(db, match_ids, version_id)
        settings = Settings(_env_file=None)
        async with db.session_factory() as session:
            assert await update_clv(session, settings) == 3
            await session.commit()
        async with db.session_factory() as session:
            assert await update_clv(session, settings) == 0
            await session.commit()
        async with db.session_factory() as session:
            count = (
                await session.execute(select(func.count()).select_from(ClvRecord))
            ).scalar_one()
        assert count == 3
    finally:
        await db.dispose()


async def test_update_clv_backfills_label_after_result_confirmed(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path)
    try:
        await _add_predictions(db, match_ids, version_id)
        async with db.session_factory() as session:
            result = (
                await session.execute(select(Result).where(Result.match_id == match_ids[0]))
            ).scalar_one()
            result.confirmed = False
            await session.commit()

        settings = Settings(_env_file=None)
        async with db.session_factory() as session:
            assert await update_clv(session, settings) == 3
            await session.commit()
        async with db.session_factory() as session:
            labels = (
                (await session.execute(select(ClvRecord.label))).scalars().all()
            )
        assert labels == [None, None, None]

        async with db.session_factory() as session:
            result = (
                await session.execute(select(Result).where(Result.match_id == match_ids[0]))
            ).scalar_one()
            result.confirmed = True
            await session.commit()

        async with db.session_factory() as session:
            assert await update_clv(session, settings) == 3
            await session.commit()
        async with db.session_factory() as session:
            records = (await session.execute(select(ClvRecord))).scalars().all()
        assert len(records) == 3
        assert {record.label for record in records} == {"H"}
    finally:
        await db.dispose()


async def test_summary_calibration_uses_confirmed_result_when_label_missing(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path)
    try:
        await _add_clv_match(
            db,
            match_id=match_ids[0],
            version_id=version_id,
            model_probs=MODEL,
            closing_probs=CLOSING,
            label=None,
        )
        async with db.session_factory() as session:
            result = await summary(session, Settings(_env_file=None))
        assert result["calibration"]["n_matches"] == 1
        assert result["calibration"]["model_brier"] is not None
        assert result["calibration"]["market_brier"] is not None
    finally:
        await db.dispose()


async def test_update_clv_skips_predictions_without_closing_price(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path, had_payload=None)
    try:
        await _add_predictions(db, match_ids, version_id)
        async with db.session_factory() as session:
            assert await update_clv(session, Settings(_env_file=None)) == 0
            await session.commit()
        async with db.session_factory() as session:
            count = (
                await session.execute(select(func.count()).select_from(ClvRecord))
            ).scalar_one()
        assert count == 0
    finally:
        await db.dispose()


async def test_update_clv_tags_football_data_fallback(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(
        tmp_path, snapshot_source="football_data", had_payload=FOOTBALL_DATA
    )
    try:
        await _add_predictions(db, match_ids, version_id)
        async with db.session_factory() as session:
            assert await update_clv(session, Settings(_env_file=None)) == 3
            await session.commit()
        async with db.session_factory() as session:
            sources = {
                record.source
                for record in (await session.execute(select(ClvRecord))).scalars()
            }
        assert sources == {"football_data"}
    finally:
        await db.dispose()


async def test_summary_aggregates(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path, n_matches=2)
    try:
        for match_id in match_ids:
            await _add_clv_match(
                db,
                match_id=match_id,
                version_id=version_id,
                model_probs=MODEL,
                closing_probs=CLOSING,
                label="H",
            )
        async with db.session_factory() as session:
            result = await summary(session, Settings(_env_file=None))
        assert result["n"] == 6
        assert result["mean_edge"] == pytest.approx(0.0)
        assert result["beat_fraction"] == pytest.approx(1 / 3)
        assert result["by_outcome"]["H"]["n"] == 2
        assert result["by_outcome"]["H"]["mean_edge"] == pytest.approx(0.1)
        assert result["by_outcome"]["H"]["beat_fraction"] == pytest.approx(1.0)
        assert result["by_outcome"]["D"]["beat_fraction"] == pytest.approx(0.0)
        assert result["by_model"][0]["model_version_id"] == version_id
        assert result["by_model"][0]["status"] == "champion"
        assert result["by_model"][0]["n"] == 6
        assert result["value"]["n"] == 6
        assert result["source_counts"] == {"hkjc": 6, "football_data": 0}
        assert result["fallback"] == 0
    finally:
        await db.dispose()


async def test_summary_source_counts_and_fallback(tmp_path) -> None:
    db, version_id, match_ids, league_id, season_id, home_id, away_id = await _seed_world(
        tmp_path
    )
    try:
        await _add_clv_match(
            db,
            match_id=match_ids[0],
            version_id=version_id,
            model_probs=MODEL,
            closing_probs=CLOSING,
            label="H",
            source="hkjc",
        )
        fallback_match = await _add_match(
            db,
            league_id=league_id,
            season_id=season_id,
            home_id=home_id,
            away_id=away_id,
            label="FD",
            source="football_data",
            payload=FOOTBALL_DATA,
            kickoff=KICKOFF + timedelta(days=1),
        )
        await _add_clv_match(
            db,
            match_id=fallback_match,
            version_id=version_id,
            model_probs=MODEL,
            closing_probs=CLOSING,
            label="H",
            source="football_data",
        )
        async with db.session_factory() as session:
            hkjc = await summary(session, Settings(_env_file=None), source="hkjc")
            all_sources = await summary(session, Settings(_env_file=None), source="all")
        assert hkjc["n"] == 3
        assert hkjc["fallback"] == 3
        assert hkjc["source_counts"] == {"hkjc": 3, "football_data": 3}
        assert all_sources["n"] == 6
    finally:
        await db.dispose()


async def test_summary_value_only_subset(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path, n_matches=2)
    try:
        await _add_clv_match(
            db,
            match_id=match_ids[0],
            version_id=version_id,
            model_probs=MODEL,
            closing_probs=CLOSING,
            label="H",
            is_value=True,
        )
        await _add_clv_match(
            db,
            match_id=match_ids[1],
            version_id=version_id,
            model_probs=MODEL,
            closing_probs=CLOSING,
            label="H",
            is_value=False,
        )
        async with db.session_factory() as session:
            all_records = await summary(session, Settings(_env_file=None))
            value_records = await summary(
                session, Settings(_env_file=None), value_only=True
            )
        assert all_records["n"] == 6
        assert all_records["value"]["n"] == 3
        assert value_records["n"] == 3
    finally:
        await db.dispose()


async def test_summary_gate_collecting_when_n_below_min(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path)
    try:
        await _add_clv_match(
            db,
            match_id=match_ids[0],
            version_id=version_id,
            model_probs=MODEL,
            closing_probs=CLOSING,
            label="H",
        )
        async with db.session_factory() as session:
            result = await summary(session, Settings(_env_file=None))
        assert result["gate"]["verdict"] == "collecting"
        assert result["gate"]["ready"] is False
        assert result["gate"]["days_remaining"] > 0
    finally:
        await db.dispose()


async def test_summary_gate_fails_when_fraction_below_threshold(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path, n_matches=3)
    try:
        for match_id in match_ids:
            await _add_clv_match(
                db,
                match_id=match_id,
                version_id=version_id,
                model_probs=MODEL,
                closing_probs=CLOSING,
                label="H",
            )
        settings = Settings(
            _env_file=None,
            clv_gate_min_n=5,
            clv_gate_days=0,
            clv_gate_start_date="2020-01-01",
        )
        async with db.session_factory() as session:
            result = await summary(session, settings)
        assert result["gate"]["verdict"] == "fail"
        criteria = {criterion["key"]: criterion for criterion in result["gate"]["criteria"]}
        assert criteria["clv_n"]["passed"] is True
        assert criteria["clv_fraction"]["passed"] is False
    finally:
        await db.dispose()


async def test_summary_gate_passes_when_all_criteria_pass(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path, n_matches=20)
    try:
        for match_id in match_ids:
            await _add_clv_match(
                db,
                match_id=match_id,
                version_id=version_id,
                model_probs=PASS_MODEL,
                closing_probs=PASS_CLOSING,
                label="H",
            )
        await _add_bet(db, match_ids[0], version_id, profit=5.0)
        await _add_bet(db, match_ids[1], version_id, profit=3.0)
        settings = Settings(
            _env_file=None,
            clv_gate_min_n=10,
            clv_gate_min_fraction=0.52,
            clv_gate_min_bets=1,
            clv_gate_min_roi=0.0,
            clv_gate_days=0,
            clv_gate_start_date="2020-01-01",
        )
        async with db.session_factory() as session:
            result = await summary(session, settings)
        assert result["gate"]["ready"] is True
        assert result["gate"]["verdict"] == "pass"
        assert result["gate"]["days_remaining"] == 0
        assert result["roi_real"] == pytest.approx(0.4)
        assert result["n_settled_bets"] == 2
    finally:
        await db.dispose()


async def test_summary_calibration_nulls_with_insufficient_matches(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path)
    try:
        await _add_clv_match(
            db,
            match_id=match_ids[0],
            version_id=version_id,
            model_probs=MODEL,
            closing_probs=CLOSING,
            label="H",
            outcomes=("H", "D"),
        )
        async with db.session_factory() as session:
            result = await summary(session, Settings(_env_file=None))
        assert result["calibration"] == {
            "model_brier": None,
            "model_logloss": None,
            "market_brier": None,
            "market_logloss": None,
            "n_matches": 0,
        }
    finally:
        await db.dispose()


async def test_summary_roi_uses_settled_bets_only(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path, n_matches=2)
    try:
        await _add_bet(db, match_ids[0], version_id, status="won", profit=5.0)
        await _add_bet(db, match_ids[1], version_id, status="pending", profit=None)
        async with db.session_factory() as session:
            result = await summary(session, Settings(_env_file=None))
        assert result["n_settled_bets"] == 1
        assert result["settled_stakes"] == pytest.approx(10.0)
        assert result["roi_real"] == pytest.approx(0.5)
        assert result["roi_real_ci95"] is None
    finally:
        await db.dispose()


async def test_summary_roi_comes_from_the_requested_book(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path, n_matches=2)
    try:
        await _add_clv_match(
            db,
            match_id=match_ids[0],
            version_id=version_id,
            model_probs=MODEL,
            closing_probs=CLOSING,
            label="H",
        )
        await _add_bet(db, match_ids[0], version_id, status="won", stake=10.0, profit=5.0)
        await _add_shadow_bet(
            db, match_ids[1], version_id, status="lost", stake=20.0, profit=-20.0
        )
        async with db.session_factory() as session:
            production = await summary(session, Settings(_env_file=None))
            shadow = await summary(session, Settings(_env_file=None), book="shadow")
        assert production["book"] == "production"
        assert production["roi_real"] == pytest.approx(0.5)
        assert production["n_settled_bets"] == 1
        assert production["settled_stakes"] == pytest.approx(10.0)
        assert shadow["book"] == "shadow"
        assert shadow["roi_real"] == pytest.approx(-1.0)
        assert shadow["n_settled_bets"] == 1
        assert shadow["settled_stakes"] == pytest.approx(20.0)
        # CLV metrics and calibration stay model-level, not book-scoped.
        assert shadow["n"] == production["n"] == 3
        assert shadow["calibration"] == production["calibration"]
    finally:
        await db.dispose()


async def test_clv_summary_api(tmp_path) -> None:
    db, version_id, match_ids, *_ = await _seed_world(tmp_path)
    try:
        await _add_clv_match(
            db,
            match_id=match_ids[0],
            version_id=version_id,
            model_probs=MODEL,
            closing_probs=CLOSING,
            label="H",
        )
        app = create_app(Settings(_env_file=None), db=db)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/clv/summary")
            assert response.status_code == 200
            body = response.json()
            assert body["source"] == "hkjc"
            assert body["book"] == "production"
            assert body["n"] == 3
            assert body["by_outcome"]["H"]["n"] == 1
            assert body["gate"]["verdict"] == "collecting"
            shadow = await client.get("/clv/summary", params={"book": "shadow"})
            assert shadow.status_code == 200
            assert shadow.json()["book"] == "shadow"
            invalid = await client.get("/clv/summary", params={"source": "nope"})
            assert invalid.status_code == 422
            invalid_book = await client.get("/clv/summary", params={"book": "nope"})
            assert invalid_book.status_code == 422
    finally:
        await db.dispose()
