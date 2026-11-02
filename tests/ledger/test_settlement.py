from decimal import Decimal
from typing import cast

import pytest

from packages.domain.enums import BetStatus, MarketType, Side
from packages.domain.errors import SettlementInputError
from packages.ledger.settlement import (
    round_payout,
    settle_had,
    settle_hdc,
    settle_hil,
    settle_market,
    settle_void,
)

D = Decimal


def test_had_home_win():
    outcome = settle_had(Side.H, 2, 1, D("2.00"), D("10.00"))
    assert outcome.result_status is BetStatus.WON
    assert outcome.payout == D("20.00")


def test_had_draw_and_away():
    draw = settle_had(Side.D, 1, 1, D("3.40"), D("10.00"))
    away = settle_had(Side.A, 0, 1, D("3.80"), D("10.00"))
    assert draw.result_status is BetStatus.WON
    assert draw.payout == D("34.00")
    assert away.result_status is BetStatus.WON
    assert away.payout == D("38.00")


def test_had_losing_selection_returns_zero():
    outcome = settle_had(Side.H, 0, 2, D("2.00"), D("10.00"))
    assert outcome.result_status is BetStatus.LOST
    assert outcome.payout == D("0.00")


def test_hdc_single_line_win_and_push():
    win = settle_hdc(Side.H, 2, 1, "-0.5", D("1.95"), D("10.00"))
    push = settle_hdc(Side.H, 2, 1, "-1.0", D("1.95"), D("10.00"))
    assert win.result_status is BetStatus.WON
    assert push.result_status is BetStatus.PUSH
    assert push.payout == D("10.00")


def test_hdc_split_line_half_win_half_push():
    outcome = settle_hdc(Side.H, 1, 0, "0.0/-1.0", D("1.95"), D("10.00"))
    assert outcome.result_status is BetStatus.HALF_WON_HALF_PUSH
    assert outcome.payout_unrounded == D("14.75")
    assert outcome.payout == D("14.80")


def test_hdc_split_line_half_lose_half_push():
    outcome = settle_hdc(Side.H, 1, 1, "0.0/-1.0", D("1.95"), D("10.00"))
    assert outcome.result_status is BetStatus.HALF_LOST_HALF_PUSH
    assert outcome.payout == D("5.00")


def test_hdc_split_line_both_lose():
    away_wins = settle_hdc(Side.A, 0, 1, "0.0/-1.0", D("1.95"), D("10.00"))
    assert away_wins.result_status is BetStatus.WON
    home_loses = settle_hdc(Side.H, 0, 1, "0.0/-1.0", D("1.95"), D("10.00"))
    assert home_loses.result_status is BetStatus.LOST


def test_hil_single_line_push_and_win():
    push = settle_hil(Side.H, 2, 1, "3.0", D("1.90"), D("10.00"))
    over = settle_hil(Side.H, 2, 2, "3.5", D("1.90"), D("10.00"))
    under = settle_hil(Side.L, 1, 0, "2.5", D("1.90"), D("10.00"))
    assert push.result_status is BetStatus.PUSH
    assert over.result_status is BetStatus.WON
    assert under.result_status is BetStatus.WON


def test_hil_split_line_half_win_half_push():
    outcome = settle_hil(Side.H, 2, 1, "2.5/3.0", D("1.90"), D("10.00"))
    assert outcome.result_status is BetStatus.HALF_WON_HALF_PUSH
    assert outcome.payout_unrounded == D("14.50")
    assert outcome.payout == D("14.50")


def test_rounding_uses_half_up_to_ten_cents():
    assert round_payout(D("20.15")) == D("20.20")
    assert round_payout(D("20.14")) == D("20.10")
    assert round_payout(D("0")) == D("0.00")


def test_void_returns_stake_and_rounds():
    outcome = settle_void(D("10.04"))
    assert outcome.result_status is BetStatus.VOID
    assert outcome.payout == D("10.00")


def test_market_dispatcher_routes_had_hdc_and_hil():
    had = settle_market(MarketType.HAD, Side.H, 2, 1, "0.0", D("1.90"), D("10.00"))
    hdc = settle_market(MarketType.HDC, Side.H, 1, 0, "0.0/-1.0", D("1.95"), D("10.00"))
    hil = settle_market(MarketType.HIL, Side.H, 2, 1, "2.5/3.0", D("1.90"), D("10.00"))
    assert had.result_status is BetStatus.WON
    assert hdc.result_status is BetStatus.HALF_WON_HALF_PUSH
    assert hil.result_status is BetStatus.HALF_WON_HALF_PUSH


def test_market_dispatcher_rejects_string_equivalent_market():
    with pytest.raises(SettlementInputError):
        settle_market(cast(MarketType, "HAD"), Side.H, 2, 1, "0.0", D("1.90"), D("10.00"))


def test_market_dispatcher_rejects_unknown_market():
    with pytest.raises(SettlementInputError):
        settle_market(cast(MarketType, "BOGUS"), Side.H, 2, 1, "0.0", D("1.90"), D("10.00"))


def test_odds_of_exactly_one_point_zero_one_is_allowed():
    outcome = settle_had(Side.H, 2, 1, D("1.01"), D("10.00"))
    assert outcome.result_status is BetStatus.WON
    assert outcome.payout == D("10.10")


def test_hil_rejects_signed_condition():
    with pytest.raises(SettlementInputError):
        settle_hil(Side.H, 2, 1, "-0.5", D("1.90"), D("10.00"))
    with pytest.raises(SettlementInputError):
        settle_hil(Side.L, 2, 1, "2.5/-3.0", D("1.90"), D("10.00"))
    with pytest.raises(SettlementInputError):
        settle_hil(Side.H, 2, 1, "2.5/+3.0", D("1.90"), D("10.00"))


def test_hdc_away_split_half_lost_half_push():
    outcome = settle_hdc(Side.A, 1, 0, "0.0/-1.0", D("1.95"), D("10.00"))
    assert outcome.result_status is BetStatus.HALF_LOST_HALF_PUSH
    assert outcome.payout == D("5.00")


def test_hil_over_half_lost_half_push():
    outcome = settle_hil(Side.H, 1, 1, "2.0/2.5", D("1.90"), D("10.00"))
    assert outcome.result_status is BetStatus.HALF_LOST_HALF_PUSH
    assert outcome.payout == D("5.00")


def test_hdc_non_adjacent_split_with_win_and_lose_is_rejected():
    with pytest.raises(SettlementInputError):
        settle_hdc(Side.H, 0, 0, "0.5/-0.5", D("1.95"), D("10.00"))


def test_rejects_invalid_inputs():
    with pytest.raises(SettlementInputError):
        settle_had(Side.H, 1, 0, D("1.00"), D("10.00"))
    with pytest.raises(SettlementInputError):
        settle_had(Side.H, 1, 0, D("2.00"), D("0"))
    with pytest.raises(SettlementInputError):
        settle_hdc(Side.H, 1, 0, "bad", D("1.95"), D("10.00"))
