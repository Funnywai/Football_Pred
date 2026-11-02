from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from packages.domain.enums import HkjcResultSemantics


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FP_", extra="ignore")

    database_url: str = "postgresql+psycopg://football:football@localhost:5432/football_pred"
    redis_url: str = "redis://localhost:6379/0"
    football_data_org_api_key: str | None = None
    initial_bankroll: Decimal = Decimal("10000.00")
    fee_rate: Decimal = Decimal(0)
    http_timeout_seconds: float = 20.0
    hkjc_graphql_url: str = "https://info.cld.hkjc.com/graphql/base/"
    hkjc_queries_dir: Path = Path("packages/adapters/hkjc_queries")
    hkjc_query_version: str = "captured-2026-11"
    hkjc_result_semantics: HkjcResultSemantics = HkjcResultSemantics.UNVERIFIED


@lru_cache
def get_settings() -> Settings:
    return Settings()
