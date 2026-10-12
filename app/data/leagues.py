from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import League

LEAGUE_SEED: list[dict[str, str]] = [
    {
        "code": "EPL",
        "name_en": "English Premier League",
        "name_ch": "英格蘭超級聯賽",
        "country": "England",
    },
    {
        "code": "LALIGA",
        "name_en": "Spanish La Liga",
        "name_ch": "西班牙甲組聯賽",
        "country": "Spain",
    },
    {
        "code": "SERIEA",
        "name_en": "Italian Serie A",
        "name_ch": "意大利甲組聯賽",
        "country": "Italy",
    },
    {
        "code": "BUNDESLIGA",
        "name_en": "German Bundesliga",
        "name_ch": "德國甲組聯賽",
        "country": "Germany",
    },
    {
        "code": "LIGUE1",
        "name_en": "French Ligue 1",
        "name_ch": "法國甲組聯賽",
        "country": "France",
    },
    {
        "code": "UCL",
        "name_en": "UEFA Champions League",
        "name_ch": "歐洲聯賽冠軍盃",
        "country": "Europe",
    },
]


async def seed_leagues(session: AsyncSession) -> int:
    """Insert any missing whitelisted leagues. Returns the number inserted."""
    inserted = 0
    for row in LEAGUE_SEED:
        existing = (
            await session.execute(select(League).where(League.code == row["code"]))
        ).scalar_one_or_none()
        if existing is None:
            session.add(League(**row))
            inserted += 1
    await session.flush()
    return inserted
