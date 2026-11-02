from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from packages.domain.enums import CoverageFlag
from packages.shared.time import ensure_utc

ODDS_STALE_AFTER = timedelta(minutes=10)


@dataclass(frozen=True)
class QualityInput:
    competition_code: str
    kickoff_at: datetime
    now: datetime
    odds_fetched_at: datetime | None
    has_standard_lineup: bool
    has_predicted_lineup: bool
    has_xg: bool
    news_item_count: int
    requires_lineup: bool = True
    degraded_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class QualityReport:
    flags: tuple[CoverageFlag, ...]
    veto_reasons: tuple[str, ...]

    @property
    def can_bet(self) -> bool:
        return not self.veto_reasons


def evaluate_quality(data: QualityInput) -> QualityReport:
    if not isinstance(data.competition_code, str) or not data.competition_code.strip():
        raise ValueError("competition_code must be a non-empty string")
    if data.news_item_count < 0:
        raise ValueError("news_item_count must be non-negative")

    now = ensure_utc(data.now)
    competition_code = data.competition_code.strip().upper()
    flags: list[CoverageFlag] = []
    veto_reasons: list[str] = []

    if competition_code == "UCL" and not data.has_xg:
        flags.append(CoverageFlag.UCL_XG_MISSING)
        veto_reasons.append("ucl_xg_missing")

    if data.requires_lineup and not data.has_standard_lineup:
        flags.append(CoverageFlag.LINEUP_UNCONFIRMED)
        if not data.has_predicted_lineup:
            veto_reasons.append("lineup_missing")

    odds_stale = (
        data.odds_fetched_at is None
        or now - ensure_utc(data.odds_fetched_at) > ODDS_STALE_AFTER
    )
    if odds_stale:
        flags.append(CoverageFlag.ODDS_STALE)
        veto_reasons.append("odds_stale")

    if data.news_item_count == 0:
        flags.append(CoverageFlag.NEWS_MISSING)

    if data.degraded_sources:
        flags.append(CoverageFlag.SOURCE_DEGRADED)
        veto_reasons.append("source_degraded:" + ",".join(sorted(data.degraded_sources)))

    return QualityReport(flags=tuple(flags), veto_reasons=tuple(veto_reasons))
