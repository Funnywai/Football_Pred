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
    paper_competitions: str = "EPL,LALIGA,BUNDESLIGA,SERIEA,LIGUE1,UCL"
    fee_rate: Decimal = Decimal(0)
    http_timeout_seconds: float = 20.0
    hkjc_graphql_url: str = "https://info.cld.hkjc.com/graphql/base/"
    hkjc_queries_dir: Path = Path("packages/adapters/hkjc_queries")
    hkjc_query_version: str = "captured-2026-11"
    hkjc_result_semantics: HkjcResultSemantics = HkjcResultSemantics.UNVERIFIED
    llm_enabled: bool = False
    llm_mode: str = "assistant"
    llm_provider: str = "openai_compatible"
    llm_model: str = "deepseek-v4.1-flash"
    llm_base_url: str = "https://opencode.ai/zen/go/v1"
    llm_api_key: str | None = None
    llm_temperature: float = 0.0
    llm_max_tokens: int = 16000
    llm_timeout_seconds: float = 180.0
    llm_competitions: str = "EPL,LALIGA,BUNDESLIGA,SERIEA,LIGUE1,UCL"
    llm_session_id: str = ""
    news_feed_urls: str = (
        "https://feeds.bbci.co.uk/sport/football/rss.xml,"
        "https://www.theguardian.com/football/rss,"
        "https://www.skysports.com/rss/12040,"
        "https://www.espn.com/espn/rss/soccer/news"
    )
    max_total_exposure_fraction: Decimal = Decimal("0.20")


@lru_cache
def get_settings() -> Settings:
    return Settings()
