import json
import logging
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app import log_buffer


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Local-dev default only (password-less local Postgres). Set DATABASE_URL in `.env` for anything real.
    database_url: str = "postgresql+asyncpg://postgres@localhost:5432/football"
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
    log_level: str = "INFO"

    # ML prediction engine (sub-system B)
    ml_enable: bool = False
    ml_1x2_model: str = "lightgbm"
    ml_handicap_model: str = "lightgbm"
    ml_value_edge_threshold: float = 0.02
    ml_blend_weight: float = 0.20
    ml_exec_edge_buffer: float = 0.03
    ml_exec_overround: float = 1.13
    ml_gate_min_real_bets: int = 50
    ml_retrain_interval: int = 604800
    ml_predict_lookahead_hours: int = 48
    ml_min_train_rows: int = 500
    ml_artifact_dir: str = "artifacts/ml"
    ml_champion_margin: float = 0.0
    ml_history_from_year: int = 2010
    ml_prior_lead_hours: int = 48

    # Paper ledger (sub-system C)
    ledger_enable: bool = True
    shadow_ledger_enable: bool = True
    ledger_update_interval: int = 3600
    ledger_initial_bankroll: float = 1000.0
    ledger_kelly_multiplier: float = 0.5
    ledger_max_stake_fraction: float = 0.05
    ledger_min_stake: float = 10.0

    # Live CLV tracking + paper-validation stop/go gate (sub-system C follow-up)
    clv_enable: bool = True
    clv_update_interval: int = 3600
    clv_gate_min_n: int = 200
    clv_gate_min_fraction: float = 0.52
    clv_gate_min_bets: int = 500
    clv_gate_min_roi: float = 0.0
    clv_gate_days: int = 90
    clv_gate_start_date: str | None = None

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


def configure_logging(level: str = "INFO") -> None:
    """Send the app's own logs to stderr so `docker compose logs app` can see them.

    Without this the root logger stays at WARNING and every ``logger.info`` (job
    skips, dropped tournaments, promotion decisions) is silently discarded.
    """
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger().setLevel(level.upper())
    log_buffer.install(level)
