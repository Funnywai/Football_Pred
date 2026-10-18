from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import League

LEAGUE_SEED: list[dict[str, str]] = [
    {
        "code": "EPL",
        "name_en": "English Premier League",
        "name_ch": "英格蘭超級聯賽",
        "country": "England",
        "hkjc_tourn_id": "50071337",
    },
    {
        "code": "LALIGA",
        "name_en": "Spanish La Liga",
        "name_ch": "西班牙甲組聯賽",
        "country": "Spain",
        "hkjc_tourn_id": "50072540",
    },
    {
        "code": "SERIEA",
        "name_en": "Italian Serie A",
        "name_ch": "意大利甲組聯賽",
        "country": "Italy",
        "hkjc_tourn_id": "50072541",
    },
    {
        "code": "BUNDESLIGA",
        "name_en": "German Bundesliga",
        "name_ch": "德國甲組聯賽",
        "country": "Germany",
        "hkjc_tourn_id": "50072572",
    },
    {
        "code": "LIGUE1",
        "name_en": "French Ligue 1",
        "name_ch": "法國甲組聯賽",
        "country": "France",
        "hkjc_tourn_id": "50072542",
    },
    {
        "code": "UCL",
        "name_en": "UEFA Champions League",
        "name_ch": "歐洲聯賽冠軍盃",
        "country": "Europe",
        "hkjc_tourn_id": "50070797",
    },
]


async def seed_leagues(session: AsyncSession) -> int:
    """Insert any missing whitelisted leagues and backfill their HKJC tournament ids.

    ``hkjc_tourn_id`` is the value HKJC returns for the tournament; ``FixtureSync``
    matches on it first, so seeding it is what lets HKJC fixtures through the league
    whitelist (their ``name_en`` values differ from ours). Returns rows inserted.
    """
    inserted = 0
    for row in LEAGUE_SEED:
        existing = (
            await session.execute(select(League).where(League.code == row["code"]))
        ).scalar_one_or_none()
        if existing is None:
            session.add(League(**row))
            inserted += 1
        elif existing.hkjc_tourn_id is None and row.get("hkjc_tourn_id"):
            existing.hkjc_tourn_id = row["hkjc_tourn_id"]
    await session.flush()
    return inserted
