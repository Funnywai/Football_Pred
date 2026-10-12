from datetime import UTC, datetime, timedelta

import pandas as pd
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team

from app.config import Settings
from app.db.models import OddsSnapshot
from app.ml.dataset import build_dataset, load_market_priors, load_training_rows, temporal_split

HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}
HAD_LATE = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.5"}, {"str": "D", "currentOdds": "3.2"},
    {"str": "A", "currentOdds": "3.0"}]}]}
HAD_POST = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "9.9"}, {"str": "D", "currentOdds": "9.9"},
    {"str": "A", "currentOdds": "9.9"}]}]}
HDC = {"lines": [{"condition": "-0.5", "main": True, "combinations": [
    {"str": "H", "currentOdds": "2.0"}, {"str": "A", "currentOdds": "1.9"}]}]}
FD = {"odds": {"PS": {"open": [2.1, 3.5, 3.9], "close": [2.15, 3.4, 4.0]}}}


def _settings() -> Settings:
    return Settings(_env_file=None, ml_history_from_year=2020)


def test_temporal_split_is_chronological() -> None:
    df = pd.DataFrame(
        {
            "kickoff_time": pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC"),
            "match_id": range(100),
        }
    )
    train, calibration, evaluation = temporal_split(df)
    assert len(train) == 70 and len(calibration) == 10 and len(evaluation) == 20
    assert train["kickoff_time"].max() < calibration["kickoff_time"].min()
    assert calibration["kickoff_time"].max() < evaluation["kickoff_time"].min()


async def test_load_training_rows_and_market_priors(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        t = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            await seed_finished_match(
                session, league, season, home, away,
                match_id_label="M1", kickoff=t, home_score=2, away_score=1,
                had_payload=HAD, hdc_payload=HDC,
            )
            await session.commit()
        async with db.session_factory() as session:
            rows = await load_training_rows(session, _settings())
            assert len(rows) == 1 and rows[0].home_score == 2
            priors = await load_market_priors(session, rows)
            prior = priors[rows[0].match_id]
            assert prior.had_probs is not None
            assert abs(sum(prior.had_probs.values()) - 1.0) < 1e-9
            assert prior.hdc_line == -0.5
            assert prior.source == "hkjc"
    finally:
        await db.dispose()


async def test_latest_hkjc_snapshot_is_last_pre_kickoff(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        t = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            match = await seed_finished_match(
                session, league, season, home, away,
                match_id_label="M1", kickoff=t, home_score=2, away_score=1,
            )
            for offset_hours, payload in ((-48, HAD), (-1, HAD_LATE), (1, HAD_POST)):
                captured = t + timedelta(hours=offset_hours)
                session.add(
                    OddsSnapshot(
                        match_id=match.id,
                        captured_at=captured,
                        snapshot_bucket=captured,
                        source="hkjc",
                        inplay=False,
                        odds_type="HAD",
                        payload=payload,
                    )
                )
            await session.commit()
        async with db.session_factory() as session:
            rows = await load_training_rows(session, _settings())
            priors = await load_market_priors(session, rows)
            assert priors[rows[0].match_id].had_odds == {"H": 2.5, "D": 3.2, "A": 3.0}
    finally:
        await db.dispose()


async def test_market_prior_falls_back_to_football_data(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        t = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            # football-data snapshot captured exactly at kickoff (closing line)
            await seed_finished_match(
                session, league, season, home, away,
                match_id_label="M1", kickoff=t, home_score=1, away_score=0,
                had_payload=FD, snapshot_source="football_data", snapshot_at_offset_hours=0,
            )
            await session.commit()
        async with db.session_factory() as session:
            rows = await load_training_rows(session, _settings())
            priors = await load_market_priors(session, rows)
            assert priors[rows[0].match_id].source == "football_data"
    finally:
        await db.dispose()


async def test_prior_lead_excludes_fresh_snapshots(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        t = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            await seed_finished_match(
                session, league, season, home, away,
                match_id_label="M1", kickoff=t, home_score=2, away_score=1,
                had_payload=HAD, hdc_payload=HDC, snapshot_at_offset_hours=-1,
            )
            await session.commit()
        async with db.session_factory() as session:
            rows = await load_training_rows(session, _settings())
            match_id = rows[0].match_id
            fresh = await load_market_priors(session, rows, 48)
            assert fresh[match_id].had_probs is None      # -1h snapshot is too fresh
            legacy = await load_market_priors(session, rows, 0)
            assert legacy[match_id].had_probs is not None  # lead 0 keeps legacy behaviour
    finally:
        await db.dispose()


async def test_prior_lead_includes_older_snapshots(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        t = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            await seed_finished_match(
                session, league, season, home, away,
                match_id_label="M1", kickoff=t, home_score=2, away_score=1,
                had_payload=HAD, hdc_payload=HDC, snapshot_at_offset_hours=-49,
            )
            await session.commit()
        async with db.session_factory() as session:
            rows = await load_training_rows(session, _settings())
            priors = await load_market_priors(session, rows, 48)
            assert priors[rows[0].match_id].had_probs is not None
            assert priors[rows[0].match_id].hdc_line == -0.5
    finally:
        await db.dispose()


async def test_build_dataset(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            teams = [await seed_team(session, f"T{i}") for i in range(6)]
            base = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
            for index in range(40):
                await seed_finished_match(
                    session, league, season, teams[index % 6], teams[(index + 1) % 6],
                    match_id_label=f"M{index}", kickoff=base + timedelta(days=index),
                    home_score=index % 4, away_score=(index + 1) % 3,
                    had_payload=HAD, hdc_payload=HDC,
                )
            await session.commit()
        async with db.session_factory() as session:
            dataset = await build_dataset(session, _settings())
            assert len(dataset.train) + len(dataset.calibration) + len(dataset.eval) == 40
            assert "label_1x2" in dataset.train.columns
    finally:
        await db.dispose()
