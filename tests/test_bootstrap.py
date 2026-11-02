import json
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal

from packages.domain.enums import HkjcResultSemantics
from packages.shared.config import Settings
from packages.shared.logging import JsonFormatter
from packages.shared.time import ensure_utc, parse_iso_utc, utc_now


def test_settings_defaults_without_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("FP_"):
            monkeypatch.delenv(key)
    settings = Settings(_env_file=None)
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.redis_url.startswith("redis://")
    assert isinstance(settings.initial_bankroll, Decimal)
    assert settings.initial_bankroll == Decimal("10000.00")
    assert isinstance(settings.fee_rate, Decimal)
    assert settings.fee_rate == Decimal(0)
    assert settings.hkjc_result_semantics is HkjcResultSemantics.UNVERIFIED


def test_json_formatter_emits_structured_record():
    record = logging.LogRecord("test.logger", logging.INFO, __file__, 1, "hello", (), None)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"


def test_time_helpers_normalize_to_utc():
    parsed = parse_iso_utc("2026-08-15T14:00:00Z")
    assert parsed == datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
    assert ensure_utc(datetime(2026, 8, 15, 14, 0)) == datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
    assert utc_now().tzinfo is UTC
    assert parse_iso_utc(None) is None
    assert parse_iso_utc("2026-08-15T22:00:00+08:00") == datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
