from ml_helpers import make_db

from app.ml.registry import (
    STATUS_RETIRED,
    gate_passes,
    get_champion,
    maybe_promote,
    register_challenger,
    rollback,
)


def test_gate_passes() -> None:
    assert gate_passes({"brier": 0.18, "clv_mean_edge": None}, {"brier": 0.20}, 0.0)
    assert not gate_passes({"brier": 0.20}, {"brier": 0.20}, 0.0)  # not better
    assert not gate_passes({"brier": 0.19}, {"brier": 0.20}, 0.05)  # not better by margin
    assert not gate_passes(
        {"brier": 0.18, "clv_mean_edge": 0.01},
        {"brier": 0.20, "clv_mean_edge": 0.02},
        0.0,
    )  # CLV worse


async def test_promote_and_rollback(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            first = await register_challenger(
                session, "1x2", "lightgbm", {}, {"brier": 0.20}, "/a.joblib"
            )
            assert await maybe_promote(session, first, 0.0)  # first becomes champion
            champion = await get_champion(session, "1x2")
            assert champion is not None and champion.id == first.id

            better = await register_challenger(
                session, "1x2", "lightgbm", {}, {"brier": 0.15}, "/b.joblib"
            )
            assert await maybe_promote(session, better, 0.0)
            champion = await get_champion(session, "1x2")
            assert champion is not None and champion.id == better.id

            previous = await rollback(session, "1x2")
            assert previous is not None and previous.id == first.id
            champion = await get_champion(session, "1x2")
            assert champion is not None and champion.id == first.id
            assert better.status == STATUS_RETIRED
    finally:
        await db.dispose()


async def test_maybe_promote_uses_fresh_champion_metrics(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            # champion whose STORED brier looks unbeatable
            first = await register_challenger(
                session, "1x2", "lightgbm", {}, {"brier": 0.10}, "/a.joblib"
            )
            assert await maybe_promote(session, first, 0.0)
            worse = await register_challenger(
                session, "1x2", "lightgbm", {}, {"brier": 0.30}, "/b.joblib"
            )
            # stored metrics would reject (0.30 > 0.10); the FRESH window says 0.40 -> promote
            assert await maybe_promote(session, worse, 0.0, champion_metrics={"brier": 0.40})
            champion = await get_champion(session, "1x2")
            assert champion is not None and champion.id == worse.id
            # and with None the stored metrics still govern (legacy behaviour)
            newer = await register_challenger(
                session, "1x2", "lightgbm", {}, {"brier": 0.35}, "/c.joblib"
            )
            assert not await maybe_promote(session, newer, 0.0)
    finally:
        await db.dispose()
