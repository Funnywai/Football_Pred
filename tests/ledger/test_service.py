import os
import threading
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from packages.db.base import Base
from packages.db.models import (
    BankrollAccount,
    BankrollReservation,
    Competition,
    Match,
    PaperBet,
    Settlement,
    Team,
)
from packages.domain.enums import (
    BetStatus,
    MarketType,
    ReservationStatus,
    SettlementSource,
    Side,
)
from packages.domain.errors import (
    AlreadySettledError,
    InsufficientBankrollError,
    SettlementInputError,
    UnsupportedMarket,
)
from packages.ledger.service import INITIAL_BANKROLL, LedgerService, PlaceBetRequest

D = Decimal
KICKOFF = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)


def _match(session) -> Match:
    match = Match(
        competition_id=uuid.uuid4(),
        season="2025/26",
        kickoff_at=KICKOFF,
        home_team_id=uuid.uuid4(),
        away_team_id=uuid.uuid4(),
        status="scheduled",
        source_match_ids={"hkjc": "HK-1001"},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    return match


def _request(
    match_id,
    *,
    analysis_run_key: str = "analysis-1",
    decision_slot_key: str = "slot-1",
    bet_intent_key: str = "bet-1",
    stake="100.00",
    market: MarketType = MarketType.HAD,
    selection: Side = Side.H,
    odds="2.00",
) -> PlaceBetRequest:
    return PlaceBetRequest(
        match_id=match_id,
        market=market,
        line_key="0.0",
        selection=selection,
        odds_decimal=D(odds),
        stake=D(stake),
        analysis_run_key=analysis_run_key,
        decision_slot_key=decision_slot_key,
        bet_intent_key=bet_intent_key,
        decision_at=KICKOFF,
    )


def _settle(
    ledger: LedgerService,
    bet_id,
    *,
    home_goals_90: int = 2,
    away_goals_90: int = 1,
    payout_confirmed: bool = True,
    refunded_markets: frozenset[MarketType] | None = None,
    closing_odds: Decimal | None = None,
    final_probability: Decimal | None = None,
    closing_odds_snapshot_id: uuid.UUID | None = None,
):
    return ledger.settle_paper_bet(
        bet_id,
        home_goals_90=home_goals_90,
        away_goals_90=away_goals_90,
        refunded_markets=(
            refunded_markets if refunded_markets is not None else frozenset()
        ),
        payout_confirmed=payout_confirmed,
        hk_result_ref="HK-1001",
        closing_odds=closing_odds,
        final_probability=final_probability,
        closing_odds_snapshot_id=closing_odds_snapshot_id,
    )


def test_initial_bankroll_default_is_ten_thousand():
    assert INITIAL_BANKROLL == D("10000.00")


def test_duplicate_bet_intent_returns_same_bet(session):
    match = _match(session)
    ledger = LedgerService(session)
    first = ledger.place_bet(_request(match.id, bet_intent_key="bet-1"))
    second = ledger.place_bet(_request(match.id, bet_intent_key="bet-1"))
    assert first.id == second.id
    assert session.query(PaperBet).count() == 1
    assert session.query(BankrollReservation).count() == 1
    account = session.query(BankrollAccount).one()
    assert account.reserved_stake == D("100.00")


def test_duplicate_bet_intent_with_different_payload_returns_original(session):
    match = _match(session)
    ledger = LedgerService(session)
    first = ledger.place_bet(_request(match.id, bet_intent_key="bet-1", stake="100.00"))
    second = ledger.place_bet(
        _request(match.id, bet_intent_key="bet-1", stake="5.00", odds="3.00")
    )
    assert first.id == second.id
    assert second.stake == D("100.00")
    assert session.query(PaperBet).count() == 1


def test_same_decision_slot_with_different_analysis_does_not_duplicate(session):
    match = _match(session)
    ledger = LedgerService(session)
    first = ledger.place_bet(
        _request(match.id, analysis_run_key="analysis-1", bet_intent_key="bet-1")
    )
    second = ledger.place_bet(
        _request(match.id, analysis_run_key="analysis-2", bet_intent_key="bet-1")
    )
    assert first.id == second.id
    assert session.query(PaperBet).count() == 1


def test_same_decision_slot_with_flipped_selection_returns_original_bet(session):
    match = _match(session)
    ledger = LedgerService(session)
    first = ledger.place_bet(
        _request(
            match.id,
            decision_slot_key="slot-1",
            bet_intent_key="bet-1",
            selection=Side.H,
        )
    )
    second = ledger.place_bet(
        _request(
            match.id,
            decision_slot_key="slot-1",
            bet_intent_key="bet-2",
            selection=Side.A,
        )
    )
    assert first.id == second.id
    assert second.selection is Side.H
    assert session.query(PaperBet).count() == 1
    assert session.query(BankrollReservation).count() == 1


def test_place_bet_persists_all_three_idempotency_keys_and_decision_time(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(
        _request(
            match.id,
            analysis_run_key="analysis-9",
            decision_slot_key="slot-9",
            bet_intent_key="bet-9",
        )
    )
    assert bet.analysis_run_key == "analysis-9"
    assert bet.decision_slot_key == "slot-9"
    assert bet.bet_intent_key == "bet-9"
    assert bet.decision_at == KICKOFF
    assert bet.placed_at == KICKOFF
    assert bet.status is BetStatus.PENDING


def test_duplicate_bet_intent_is_rejected_by_database_constraint(session):
    match = _match(session)
    ledger = LedgerService(session)
    ledger.place_bet(_request(match.id, bet_intent_key="bet-1"))
    duplicate = PaperBet(
        match_id=match.id,
        market=MarketType.HAD,
        line_key="0.0",
        selection=Side.H,
        odds_decimal=D("2.00"),
        stake=D("10.00"),
        bankroll_before=D("9900.00"),
        placed_at=KICKOFF,
        status=BetStatus.PENDING,
        analysis_run_key="analysis-2",
        decision_slot_key="slot-1",
        bet_intent_key="bet-1",
        decision_at=KICKOFF,
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_sequential_stakes_cannot_overspend_cash_available(session):
    match = _match(session)
    ledger = LedgerService(session, initial_bankroll=D("150.00"))
    ledger.place_bet(_request(match.id, stake="100.00", bet_intent_key="bet-1"))
    with pytest.raises(InsufficientBankrollError):
        ledger.place_bet(
            _request(
                match.id,
                stake="100.00",
                bet_intent_key="bet-2",
                decision_slot_key="slot-2",
            )
        )


def _postgres_url_or_skip() -> str:
    url = os.environ.get("FP_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("FP_TEST_POSTGRES_URL is not set")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def test_concurrent_stakes_serialize_on_a_postgres_bankroll_row():
    url = _postgres_url_or_skip()
    try:
        engine = create_engine(url, pool_pre_ping=True, future=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any connection failure means skip
        pytest.skip(f"Postgres unavailable: {exc}")

    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        run_id = uuid.uuid4().hex[:8]
        account_id = f"cc-{run_id}"
        with factory() as setup:
            competition = Competition(
                code=f"C{run_id}",
                name="Concurrency Test",
                country="Test",
                is_cup=False,
                football_data_code="PL",
            )
            home = Team(
                slug=f"home-{run_id}",
                name="Home",
                short_name="HOM",
                country="Test",
            )
            away = Team(
                slug=f"away-{run_id}",
                name="Away",
                short_name="AWY",
                country="Test",
            )
            setup.add_all([competition, home, away])
            setup.flush()
            match = Match(
                competition_id=competition.id,
                season="2025/26",
                kickoff_at=KICKOFF,
                home_team_id=home.id,
                away_team_id=away.id,
                status="scheduled",
                source_match_ids={},
                coverage_flags=[],
            )
            setup.add(match)
            setup.add(
                BankrollAccount(
                    account_id=account_id,
                    currency="HKD",
                    bankroll_balance=D("100.00"),
                    reserved_stake=D("0.00"),
                )
            )
            setup.commit()
            match_id = match.id

        barrier = threading.Barrier(2)
        results: list[str] = []
        errors: list[Exception] = []

        def attempt(suffix: str) -> None:
            session = factory()
            try:
                ledger = LedgerService(
                    session,
                    initial_bankroll=D("100.00"),
                    account_id=account_id,
                )
                barrier.wait(timeout=10)
                try:
                    ledger.place_bet(
                        _request(
                            match_id,
                            stake="80.00",
                            analysis_run_key=f"analysis-{run_id}",
                            decision_slot_key=f"slot-{run_id}-{suffix}",
                            bet_intent_key=f"concurrent-{run_id}-{suffix}",
                        )
                    )
                    session.commit()
                    results.append("placed")
                except InsufficientBankrollError:
                    session.rollback()
                    results.append("rejected")
            except Exception as exc:  # noqa: BLE001 - collect thread failure
                errors.append(exc)
            finally:
                session.close()

        threads = [
            threading.Thread(target=attempt, args=(suffix,))
            for suffix in ("a", "b")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert not errors
        assert not any(thread.is_alive() for thread in threads)
        assert sorted(results) == ["placed", "rejected"]

        with factory() as verify:
            assert verify.query(PaperBet).filter_by(match_id=match_id).count() == 1
            reservations = (
                verify.query(BankrollReservation)
                .filter(BankrollReservation.bet_intent_key.like(f"concurrent-{run_id}-%"))
                .all()
            )
            assert len(reservations) == 1
            account = verify.query(BankrollAccount).filter_by(
                account_id=account_id
            ).one()
            assert account.reserved_stake == D("80.00")
            assert account.bankroll_balance - account.reserved_stake == D("20.00")
    finally:
        engine.dispose()


def test_failed_place_bet_rolls_back_reservation_and_bet(session):
    match = _match(session)
    ledger = LedgerService(session, initial_bankroll=D("150.00"))
    ledger.place_bet(_request(match.id, stake="100.00", bet_intent_key="bet-1"))
    with pytest.raises(InsufficientBankrollError):
        ledger.place_bet(
            _request(
                match.id,
                stake="100.00",
                bet_intent_key="bet-2",
                decision_slot_key="slot-2",
            )
        )
    session.expire_all()
    assert session.query(PaperBet).count() == 1
    assert session.query(BankrollReservation).count() == 1
    account = session.query(BankrollAccount).one()
    assert account.reserved_stake == D("100.00")


def test_place_bet_rejects_insufficient_bankroll(session):
    match = _match(session)
    ledger = LedgerService(session, initial_bankroll=D("50.00"))
    with pytest.raises(InsufficientBankrollError):
        ledger.place_bet(_request(match.id, stake="100.00"))


def test_odds_of_exactly_one_point_zero_one_is_allowed(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id, odds="1.01", stake="10.00"))
    assert bet.odds_decimal == D("1.01")


def test_odds_below_one_point_zero_one_is_rejected(session):
    match = _match(session)
    ledger = LedgerService(session)
    with pytest.raises(SettlementInputError):
        ledger.place_bet(_request(match.id, odds="1.009"))
    assert session.query(PaperBet).count() == 0


def test_place_bet_rejects_non_positive_stake(session):
    match = _match(session)
    ledger = LedgerService(session)
    with pytest.raises(SettlementInputError):
        ledger.place_bet(_request(match.id, stake="0.00"))


def test_place_bet_rejects_non_had_market_for_g1(session):
    match = _match(session)
    ledger = LedgerService(session)
    with pytest.raises(UnsupportedMarket):
        ledger.place_bet(
            _request(match.id, market=MarketType.HDC, selection=Side.H)
        )
    assert session.query(PaperBet).count() == 0


def test_place_bet_rejects_blank_idempotency_keys(session):
    match = _match(session)
    ledger = LedgerService(session)
    with pytest.raises(SettlementInputError):
        ledger.place_bet(_request(match.id, bet_intent_key=""))


def test_available_bankroll_subtracts_reserved_stake(session):
    match = _match(session)
    ledger = LedgerService(session)
    assert ledger.available_bankroll() == D("10000.00")
    ledger.place_bet(_request(match.id, stake="100.00"))
    assert ledger.available_bankroll() == D("9900.00")


def test_ensure_account_is_idempotent(session):
    ledger = LedgerService(session)
    first = ledger.ensure_account()
    second = ledger.ensure_account()
    assert first.id == second.id
    assert session.query(BankrollAccount).count() == 1
    assert first.bankroll_balance == D("10000.00")
    assert first.reserved_stake == D("0.00")


def test_summary_uses_persisted_account_balance(session):
    ledger = LedgerService(session, initial_bankroll=D("500.00"))
    account = ledger.ensure_account()
    account.bankroll_balance = D("777.00")
    session.flush()
    summary = ledger.summary()
    assert summary.bankroll == D("777.00")


def test_summary_uses_custom_initial_bankroll_after_settlement(session):
    match = _match(session)
    ledger = LedgerService(session, initial_bankroll=D("500.00"))
    bet = ledger.place_bet(_request(match.id, stake="100.00"))
    _settle(ledger, bet.id)
    summary = ledger.summary()
    assert summary.bankroll == D("600.00")
    assert ledger.available_bankroll() == D("600.00")


def test_settle_bet_records_payout_clv_and_brier(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    settlement = ledger.settle_paper_bet(
        bet.id,
        home_goals_90=2,
        away_goals_90=1,
        refunded_markets=frozenset(),
        payout_confirmed=True,
        hk_result_ref="HK-1001",
        closing_odds=D("1.80"),
        final_probability=D("0.55"),
    )
    assert settlement.result_status is BetStatus.WON
    assert settlement.payout == D("200.00")
    assert settlement.provisional is False
    assert settlement.source is SettlementSource.HKJC_CONFIRMED
    assert settlement.clv is not None
    assert abs(settlement.clv - (D("2.0") / D("1.80") - D("1"))) < D("0.000001")
    assert settlement.brier_score == D("0.2025")
    assert bet.status is BetStatus.WON


def test_settlement_releases_reservation_and_updates_bankroll(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    _settle(ledger, bet.id)
    session.expire_all()
    account = session.query(BankrollAccount).one()
    assert account.reserved_stake == D("0.00")
    assert account.bankroll_balance == D("10100.00")
    reservation = session.query(BankrollReservation).one()
    assert reservation.status is ReservationStatus.COMMITTED
    assert ledger.available_bankroll() == D("10100.00")


def test_settle_bet_rejects_double_settlement(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    _settle(ledger, bet.id)
    with pytest.raises(AlreadySettledError):
        _settle(ledger, bet.id)


def test_settle_refunded_market_voids_bet(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id, bet_intent_key="void-run"))
    settlement = ledger.settle_paper_bet(
        bet.id,
        home_goals_90=2,
        away_goals_90=1,
        refunded_markets=frozenset({MarketType.HAD}),
        payout_confirmed=True,
        hk_result_ref="HK-1001",
        closing_odds=None,
        final_probability=None,
    )
    assert settlement.result_status is BetStatus.VOID
    assert settlement.payout == D("100.00")
    session.expire_all()
    account = session.query(BankrollAccount).one()
    assert account.reserved_stake == D("0.00")
    assert account.bankroll_balance == D("10000.00")
    reservation = session.query(BankrollReservation).one()
    assert reservation.status is ReservationStatus.RELEASED


def test_settle_unknown_bet_raises_input_error(session):
    ledger = LedgerService(session)
    with pytest.raises(SettlementInputError):
        _settle(ledger, uuid.uuid4())


def test_settle_failure_rolls_back_bet_and_bankroll(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    reservation = session.query(BankrollReservation).one()
    session.delete(reservation)
    session.flush()
    with pytest.raises(SettlementInputError):
        _settle(ledger, bet.id)
    session.expire_all()
    reloaded = session.get(PaperBet, bet.id)
    assert reloaded.status is BetStatus.PENDING
    account = session.query(BankrollAccount).one()
    assert account.reserved_stake == D("100.00")
    assert account.bankroll_balance == D("10000.00")


def test_settle_rejects_provisional_settlement_without_mutation(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    with pytest.raises(SettlementInputError, match="provisional"):
        _settle(ledger, bet.id, payout_confirmed=False)
    session.expire_all()
    reloaded = session.get(PaperBet, bet.id)
    assert reloaded.status is BetStatus.PENDING
    assert session.query(Settlement).count() == 0
    reservation = session.query(BankrollReservation).one()
    assert reservation.status is ReservationStatus.HELD
    account = session.query(BankrollAccount).one()
    assert account.reserved_stake == D("100.00")
    assert account.bankroll_balance == D("10000.00")


def test_void_settlement_does_not_store_brier(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    settlement = _settle(
        ledger,
        bet.id,
        refunded_markets=frozenset({MarketType.HAD}),
        final_probability=D("0.9"),
    )
    assert settlement.result_status is BetStatus.VOID
    assert settlement.brier_score is None


def test_push_settlement_does_not_store_brier(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    bet.market = MarketType.HDC
    bet.line_key = "0.0"
    bet.selection = Side.H
    session.flush()
    settlement = _settle(
        ledger,
        bet.id,
        home_goals_90=1,
        away_goals_90=1,
        final_probability=D("0.6"),
    )
    assert settlement.result_status is BetStatus.PUSH
    assert settlement.payout == D("100.00")
    assert settlement.brier_score is None


def test_half_push_settlement_does_not_store_brier(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    bet.market = MarketType.HDC
    bet.line_key = "0.0/-1.0"
    bet.selection = Side.H
    session.flush()
    settlement = _settle(
        ledger,
        bet.id,
        home_goals_90=1,
        away_goals_90=0,
        final_probability=D("0.6"),
    )
    assert settlement.result_status is BetStatus.HALF_WON_HALF_PUSH
    assert settlement.brier_score is None


def test_closing_odds_snapshot_id_is_persisted(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    snapshot_id = uuid.uuid4()
    settlement = _settle(
        ledger,
        bet.id,
        closing_odds=D("1.80"),
        closing_odds_snapshot_id=snapshot_id,
    )
    assert settlement.clv is not None
    session.expire_all()
    reloaded = session.get(PaperBet, bet.id)
    assert reloaded.closing_odds_snapshot_id == snapshot_id


def test_fee_rate_is_charged_on_profit_only(session):
    match = _match(session)
    ledger = LedgerService(session, fee_rate=D("0.05"))
    bet = ledger.place_bet(_request(match.id))
    settlement = _settle(ledger, bet.id)
    assert settlement.payout == D("200.00")
    summary = ledger.summary()
    assert summary.total_stake == D("100.00")
    assert summary.total_payout == D("195.00")
    assert summary.roi == D("0.95")
    assert summary.bankroll == D("10095.00")
    assert ledger.available_bankroll() == D("10095.00")


def test_fee_rate_does_not_charge_void_refund(session):
    match = _match(session)
    ledger = LedgerService(session, fee_rate=D("0.05"))
    bet = ledger.place_bet(_request(match.id))
    settlement = _settle(
        ledger, bet.id, refunded_markets=frozenset({MarketType.HAD})
    )
    assert settlement.payout == D("100.00")
    summary = ledger.summary()
    assert summary.total_payout == D("100.00")
    assert summary.roi == D("0")
    assert ledger.available_bankroll() == D("10000.00")


def test_fee_rate_does_not_charge_push_refund(session):
    match = _match(session)
    ledger = LedgerService(session, fee_rate=D("0.05"))
    bet = ledger.place_bet(_request(match.id))
    bet.market = MarketType.HDC
    bet.line_key = "0.0"
    bet.selection = Side.H
    session.flush()
    settlement = _settle(
        ledger, bet.id, home_goals_90=1, away_goals_90=1
    )
    assert settlement.result_status is BetStatus.PUSH
    summary = ledger.summary()
    assert summary.total_payout == D("100.00")
    assert summary.roi == D("0")
    assert ledger.available_bankroll() == D("10000.00")


def test_summary_reports_roi_and_bankroll(session):
    match = _match(session)
    ledger = LedgerService(session)
    bet = ledger.place_bet(_request(match.id))
    _settle(ledger, bet.id)
    summary = ledger.summary()
    assert summary.total_stake == D("100.00")
    assert summary.total_payout == D("200.00")
    assert summary.roi == D("1")
    assert summary.settled_count == 1
    assert summary.pending_count == 0
    assert summary.bankroll == D("10100.00")
    assert summary.max_drawdown == D("0")


def test_void_odd_cent_refund_has_no_fee_and_restores_bankroll(session):
    match = _match(session)
    ledger = LedgerService(session, fee_rate=D("0.05"))
    bet = ledger.place_bet(
        _request(match.id, stake="10.04", bet_intent_key="void-odd-cent")
    )
    settlement = _settle(
        ledger, bet.id, refunded_markets=frozenset({MarketType.HAD})
    )
    assert settlement.result_status is BetStatus.VOID
    assert settlement.payout == D("10.00")
    assert settlement.payout_unrounded == D("10.04")
    session.expire_all()
    account = session.query(BankrollAccount).one()
    assert account.bankroll_balance == D("10000.00")
    assert account.reserved_stake == D("0.00")
    summary = ledger.summary()
    assert summary.bankroll == D("10000.00")
    assert summary.total_payout == D("10.04")
    assert summary.roi == D("0")


def test_push_odd_cent_refund_has_no_fee_and_no_artificial_profit(session):
    match = _match(session)
    ledger = LedgerService(session, fee_rate=D("0.05"))
    bet = ledger.place_bet(
        _request(match.id, stake="10.04", bet_intent_key="push-odd-cent")
    )
    bet.market = MarketType.HDC
    bet.line_key = "0.0"
    bet.selection = Side.H
    session.flush()
    settlement = _settle(ledger, bet.id, home_goals_90=1, away_goals_90=1)
    assert settlement.result_status is BetStatus.PUSH
    assert settlement.payout == D("10.00")
    assert settlement.payout_unrounded == D("10.04")
    session.expire_all()
    account = session.query(BankrollAccount).one()
    assert account.bankroll_balance == D("10000.00")
    summary = ledger.summary()
    assert summary.total_payout == D("10.04")
    assert summary.roi == D("0")


def test_fee_uses_unrounded_profit_when_rounding_would_change_fee(session):
    match = _match(session)
    ledger = LedgerService(session, fee_rate=D("0.05"))
    bet = ledger.place_bet(
        _request(
            match.id,
            stake="10.00",
            odds="1.2879",
            bet_intent_key="won-rounding",
        )
    )
    settlement = _settle(ledger, bet.id)
    assert settlement.payout == D("12.90")
    assert settlement.payout_unrounded == D("12.879")
    summary = ledger.summary()
    # Fee on unrounded profit 2.879 * 5% = 0.14395 -> 0.14.
    # Fee on rounded payout 2.90 * 5% = 0.145 -> 0.15, so this pins the fix.
    assert summary.total_payout == D("12.76")
    assert summary.bankroll == D("10002.76")
    session.expire_all()
    account = session.query(BankrollAccount).one()
    assert account.bankroll_balance == summary.bankroll


def test_summary_counts_pending_bets_and_drawdown(session):
    match = _match(session)
    ledger = LedgerService(session)
    first = ledger.place_bet(_request(match.id, bet_intent_key="bet-1", stake="100.00"))
    _settle(ledger, first.id, home_goals_90=0, away_goals_90=1)
    ledger.place_bet(
        _request(match.id, bet_intent_key="bet-2", stake="100.00", decision_slot_key="slot-2")
    )
    summary = ledger.summary()
    assert summary.total_stake == D("100.00")
    assert summary.total_payout == D("0.00")
    assert summary.roi == D("-1")
    assert summary.settled_count == 1
    assert summary.pending_count == 1
    assert summary.bankroll == D("9900.00")
    assert summary.max_drawdown == D("0.01")
