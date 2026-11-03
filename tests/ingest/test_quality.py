from datetime import UTC, datetime, timedelta

import pytest

from packages.domain.enums import CoverageFlag
from packages.ingest.quality import QualityInput, evaluate_quality

NOW = datetime(2026, 8, 15, 13, 0, tzinfo=UTC)
FRESH_ODDS_AT = NOW - timedelta(minutes=2)


def _input(
    *,
    competition_code: str = "EPL",
    odds_fetched_at: datetime | None = FRESH_ODDS_AT,
    has_standard_lineup: bool = True,
    has_predicted_lineup: bool = True,
    has_xg: bool = True,
    news_item_count: int = 3,
    requires_lineup: bool = True,
    requires_xg: bool = True,
    degraded_sources: tuple[str, ...] = (),
) -> QualityInput:
    return QualityInput(
        competition_code=competition_code,
        kickoff_at=NOW + timedelta(hours=1),
        now=NOW,
        odds_fetched_at=odds_fetched_at,
        has_standard_lineup=has_standard_lineup,
        has_predicted_lineup=has_predicted_lineup,
        has_xg=has_xg,
        news_item_count=news_item_count,
        requires_lineup=requires_lineup,
        requires_xg=requires_xg,
        degraded_sources=degraded_sources,
    )


def test_complete_data_can_bet():
    report = evaluate_quality(_input())
    assert report.can_bet is True
    assert report.flags == ()


def test_ucl_without_xg_is_vetoed():
    report = evaluate_quality(
        _input(
            competition_code="UCL",
            has_xg=False,
            news_item_count=2,
        )
    )
    assert CoverageFlag.UCL_XG_MISSING in report.flags
    assert report.can_bet is False


def test_ucl_code_is_matched_case_insensitively():
    report = evaluate_quality(
        _input(competition_code=" ucl ", has_xg=False)
    )
    assert CoverageFlag.UCL_XG_MISSING in report.flags
    assert report.can_bet is False


def test_ucl_prediction_only_allows_missing_xg():
    report = evaluate_quality(
        _input(
            competition_code="UCL",
            has_xg=False,
            requires_xg=False,
        )
    )
    assert CoverageFlag.UCL_XG_MISSING in report.flags
    assert report.can_bet is True


def test_ucl_prediction_only_still_vetoes_stale_odds():
    report = evaluate_quality(
        _input(
            competition_code="UCL",
            has_xg=False,
            requires_xg=False,
            odds_fetched_at=NOW - timedelta(minutes=11),
        )
    )
    assert report.veto_reasons == ("odds_stale",)
    assert report.can_bet is False


def test_predicted_only_lineup_flags_but_does_not_veto():
    report = evaluate_quality(
        _input(
            has_standard_lineup=False,
            has_predicted_lineup=True,
            news_item_count=1,
        )
    )
    assert CoverageFlag.LINEUP_UNCONFIRMED in report.flags
    assert report.can_bet is True


def test_missing_lineup_is_vetoed():
    report = evaluate_quality(
        _input(
            has_standard_lineup=False,
            has_predicted_lineup=False,
            news_item_count=1,
        )
    )
    assert report.can_bet is False
    assert "lineup_missing" in report.veto_reasons


def test_stale_odds_are_vetoed_at_ten_minute_boundary():
    fresh = evaluate_quality(_input(odds_fetched_at=NOW - timedelta(minutes=9)))
    stale = evaluate_quality(_input(odds_fetched_at=NOW - timedelta(minutes=11)))
    assert CoverageFlag.ODDS_STALE not in fresh.flags
    assert CoverageFlag.ODDS_STALE in stale.flags
    assert stale.can_bet is False


def test_odds_exactly_ten_minutes_old_are_allowed():
    report = evaluate_quality(_input(odds_fetched_at=NOW - timedelta(minutes=10)))
    assert CoverageFlag.ODDS_STALE not in report.flags
    assert report.can_bet is True


def test_missing_odds_timestamp_is_stale_and_vetoed():
    report = evaluate_quality(_input(odds_fetched_at=None))
    assert CoverageFlag.ODDS_STALE in report.flags
    assert "odds_stale" in report.veto_reasons
    assert report.can_bet is False


def test_news_missing_alone_only_flags():
    report = evaluate_quality(_input(news_item_count=0))
    assert CoverageFlag.NEWS_MISSING in report.flags
    assert report.can_bet is True


def test_news_missing_and_degraded_source_flags():
    report = evaluate_quality(
        _input(
            news_item_count=0,
            degraded_sources=("fotmob",),
        )
    )
    assert CoverageFlag.NEWS_MISSING in report.flags
    assert CoverageFlag.SOURCE_DEGRADED in report.flags
    assert report.can_bet is False
    assert report.veto_reasons == ("source_degraded:fotmob",)


def test_negative_news_count_fails_closed():
    with pytest.raises(ValueError):
        evaluate_quality(_input(news_item_count=-1))


def test_blank_competition_code_fails_closed():
    with pytest.raises(ValueError):
        evaluate_quality(_input(competition_code="   "))


def test_lineup_requirement_can_be_disabled_without_flags_or_veto():
    report = evaluate_quality(
        _input(
            has_standard_lineup=False,
            has_predicted_lineup=False,
            news_item_count=1,
            requires_lineup=False,
        )
    )
    assert CoverageFlag.LINEUP_UNCONFIRMED not in report.flags
    assert report.veto_reasons == ()
    assert report.can_bet is True


def test_disabling_lineup_requirement_keeps_the_stale_odds_veto():
    report = evaluate_quality(
        _input(
            odds_fetched_at=NOW - timedelta(minutes=11),
            requires_lineup=False,
        )
    )
    assert CoverageFlag.ODDS_STALE in report.flags
    assert report.veto_reasons == ("odds_stale",)
    assert report.can_bet is False
