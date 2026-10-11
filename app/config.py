import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/football"
    hkjc_graphql_url: str = "https://info.cld.hkjc.com/graphql/base/"
    hkjc_referer: str = "https://bet.hkjc.com/"
    hkjc_origin: str = "https://bet.hkjc.com"
    hkjc_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    football_data_base: str = "https://www.football-data.co.uk"
    sync_odds_interval: int = 600
    sync_settle_interval: int = 900
    league_whitelist: Annotated[list[str], NoDecode] = [
        "EPL",
        "LALIGA",
        "SERIEA",
        "BUNDESLIGA",
        "LIGUE1",
        "UCL",
    ]
    hkjc_throttle_seconds: float = 1.5
    odds_retention_days: int = 120
    enable_scheduler: bool = True

    @field_validator("league_whitelist", mode="before")
    @classmethod
    def _parse_whitelist(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [part.strip().upper() for part in text.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
