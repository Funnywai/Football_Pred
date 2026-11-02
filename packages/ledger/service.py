from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.db.models import (
    BankrollAccount,
    BankrollReservation,
    PaperBet,
    Settlement,
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
from packages.domain.markets import validate_side
from packages.ledger.metrics import (
    bankroll_curve,
    brier_score,
    clv,
    max_drawdown,
    roi,
)
from packages.ledger.settlement import MIN_ODDS, settle_market, settle_void
from packages.shared.time import ensure_utc, utc_now

INITIAL_BANKROLL = Decimal("10000.00")
DEFAULT_ACCOUNT_ID = "paper"
DEFAULT_CURRENCY = "HKD"
_ZERO = Decimal(0)
_MONEY_QUANTUM = Decimal("0.01")


def _money(amount: Decimal) -> Decimal:
    return amount.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _fee_on_profit(payout: Decimal, stake: Decimal, fee_rate: Decimal) -> Decimal:
    """Fee applies only to positive profit; VOID/PUSH refunds are fee-free."""
    profit = payout - stake
    if profit <= _ZERO or fee_rate <= _ZERO:
        return _ZERO
    return _money(profit * fee_rate)


def _credited_gross(
    stake: Decimal,
    rounded_payout: Decimal,
    unrounded_payout: Decimal,
) -> Decimal:
    """Credit exact refunds, rounded dividends.

    HK$0.10 payout rounding must not manufacture P&L on a VOID/PUSH refund, but
    a winning dividend is paid at the rounded amount.
    """
    return unrounded_payout if unrounded_payout <= stake else rounded_payout


def _brier_for_status(result_status: BetStatus, probability: Decimal | None) -> Decimal | None:
    """Phase 1 binary selection-level Brier; three-class HAD Brier is Phase 2."""
    if probability is None:
        return None
    if result_status is BetStatus.WON:
        return brier_score(probability, 1)
    if result_status is BetStatus.LOST:
        return brier_score(probability, 0)
    return None


@dataclass(frozen=True)
class PlaceBetRequest:
    match_id: uuid.UUID
    market: MarketType
    line_key: str
    selection: Side
    odds_decimal: Decimal
    stake: Decimal
    analysis_run_key: str
    decision_slot_key: str
    bet_intent_key: str
    decision_at: datetime
    odds_snapshot_id: uuid.UUID | None = None


@dataclass(frozen=True)
class LedgerSummary:
    total_stake: Decimal
    total_payout: Decimal
    roi: Decimal
    settled_count: int
    pending_count: int
    bankroll: Decimal
    max_drawdown: Decimal


class LedgerService:
    def __init__(
        self,
        session: Session,
        initial_bankroll: Decimal = INITIAL_BANKROLL,
        fee_rate: Decimal = _ZERO,
        account_id: str = DEFAULT_ACCOUNT_ID,
        currency: str = DEFAULT_CURRENCY,
    ) -> None:
        if not initial_bankroll.is_finite() or initial_bankroll < _ZERO:
            raise ValueError("initial_bankroll must be a non-negative finite Decimal")
        if not fee_rate.is_finite() or fee_rate < _ZERO or fee_rate >= Decimal(1):
            raise ValueError("fee_rate must be in [0, 1)")
        if not account_id.strip():
            raise ValueError("account_id must not be blank")
        self._session: Session = session
        self._initial: Decimal = initial_bankroll
        self._fee_rate: Decimal = fee_rate
        self._account_id: str = account_id
        self._currency: str = currency

    def available_bankroll(self) -> Decimal:
        account = self._get_account()
        if account is None:
            return self._initial
        return account.bankroll_balance - account.reserved_stake

    def place_bet(self, request: PlaceBetRequest) -> PaperBet:
        existing = self._find_bet_by_slot(request.decision_slot_key)
        if existing is None:
            existing = self._find_bet(request.bet_intent_key)
        if existing is not None:
            return existing
        self._validate_new_bet(request)
        try:
            return self._insert_bet(request)
        except IntegrityError:
            existing = self._find_bet_by_slot(request.decision_slot_key)
            if existing is None:
                existing = self._find_bet(request.bet_intent_key)
            if existing is None:
                raise
            return existing

    def settle_paper_bet(
        self,
        bet_id: uuid.UUID,
        *,
        home_goals_90: int,
        away_goals_90: int,
        refunded_markets: frozenset[MarketType],
        payout_confirmed: bool,
        hk_result_ref: str | None,
        closing_odds: Decimal | None,
        final_probability: Decimal | None,
        closing_odds_snapshot_id: uuid.UUID | None = None,
        settled_at: datetime | None = None,
    ) -> Settlement:
        if not payout_confirmed:
            raise SettlementInputError(
                "provisional settlement is deferred to Phase 2; payout_confirmed=True is required"
            )
        with self._session.begin_nested():
            bet = self._session.execute(
                select(PaperBet).where(PaperBet.id == bet_id).with_for_update()
            ).scalar_one_or_none()
            if bet is None:
                raise SettlementInputError(f"unknown paper bet {bet_id}")
            if bet.status is not BetStatus.PENDING:
                raise AlreadySettledError(f"paper bet {bet_id} is already settled")
            refunded = bet.market in refunded_markets
            if refunded:
                outcome = settle_void(bet.stake)
            else:
                outcome = settle_market(
                    bet.market,
                    bet.selection,
                    home_goals_90,
                    away_goals_90,
                    bet.line_key,
                    bet.odds_decimal,
                    bet.stake,
                )
            reservation = self._session.execute(
                select(BankrollReservation)
                .where(
                    BankrollReservation.bet_intent_key == bet.bet_intent_key,
                    BankrollReservation.status == ReservationStatus.HELD,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if reservation is None:
                raise SettlementInputError(
                    f"no held reservation for bet intent {bet.bet_intent_key}"
                )
            account = self._locked_account()
            if reservation.amount > account.reserved_stake:
                raise SettlementInputError(
                    "reserved stake is smaller than the held reservation"
                )
            account.reserved_stake -= reservation.amount
            fee = _fee_on_profit(outcome.payout_unrounded, bet.stake, self._fee_rate)
            net_payout = _credited_gross(
                bet.stake,
                outcome.payout,
                outcome.payout_unrounded,
            ) - fee
            account.bankroll_balance = _money(
                account.bankroll_balance + net_payout - bet.stake
            )
            if outcome.result_status is BetStatus.VOID:
                reservation.status = ReservationStatus.RELEASED
            else:
                reservation.status = ReservationStatus.COMMITTED
            if closing_odds_snapshot_id is not None:
                bet.closing_odds_snapshot_id = closing_odds_snapshot_id
            settlement = Settlement(
                paper_bet_id=bet.id,
                result_status=outcome.result_status,
                payout=outcome.payout,
                payout_unrounded=outcome.payout_unrounded,
                clv=clv(bet.odds_decimal, closing_odds),
                brier_score=_brier_for_status(
                    outcome.result_status, final_probability
                ),
                settled_at=ensure_utc(settled_at) if settled_at is not None else utc_now(),
                hk_result_ref=hk_result_ref,
                provisional=False,
                source=SettlementSource.HKJC_CONFIRMED,
            )
            bet.status = outcome.result_status
            self._session.add(settlement)
            self._session.flush()
            return settlement

    def summary(self) -> LedgerSummary:
        rows = self._session.execute(
            select(
                PaperBet.stake,
                Settlement.payout,
                Settlement.payout_unrounded,
                Settlement.settled_at,
                Settlement.id,
            )
            .join(Settlement, Settlement.paper_bet_id == PaperBet.id)
            .where(Settlement.provisional.is_(False))
            .order_by(Settlement.settled_at, Settlement.id)
        ).all()
        settled = [
            (Decimal(str(row[0])), Decimal(str(row[1])), Decimal(str(row[2])))
            for row in rows
        ]
        total_stake = sum((stake for stake, _, _ in settled), _ZERO)
        net_payouts = [
            _credited_gross(stake, gross_rounded, gross_unrounded)
            - _fee_on_profit(gross_unrounded, stake, self._fee_rate)
            for stake, gross_rounded, gross_unrounded in settled
        ]
        total_payout = sum(net_payouts, _ZERO)
        curve = bankroll_curve(
            self._initial,
            list(zip((stake for stake, _, _ in settled), net_payouts, strict=True)),
        )
        pending_count = self._session.execute(
            select(func.count())
            .select_from(PaperBet)
            .where(PaperBet.status == BetStatus.PENDING)
        ).scalar_one()
        account = self._get_account()
        bankroll = account.bankroll_balance if account is not None else curve[-1]
        return LedgerSummary(
            total_stake=total_stake,
            total_payout=total_payout,
            roi=roi(total_stake, total_payout),
            settled_count=len(rows),
            pending_count=int(pending_count),
            bankroll=bankroll,
            max_drawdown=max_drawdown(curve),
        )

    def _validate_new_bet(self, request: PlaceBetRequest) -> None:
        for name, value in (
            ("analysis_run_key", request.analysis_run_key),
            ("decision_slot_key", request.decision_slot_key),
            ("bet_intent_key", request.bet_intent_key),
        ):
            if not value.strip():
                raise SettlementInputError(f"{name} must not be blank")
        if request.market is not MarketType.HAD:
            raise UnsupportedMarket(
                f"G1 paper betting only supports {MarketType.HAD.value}, got {request.market.value}"
            )
        validate_side(request.market, request.selection)
        odds = request.odds_decimal
        if not odds.is_finite() or odds < MIN_ODDS:
            raise SettlementInputError(
                f"odds must be at least {MIN_ODDS}, got {odds}"
            )
        stake = request.stake
        if not stake.is_finite() or stake <= _ZERO:
            raise SettlementInputError(f"stake must be positive, got {stake}")

    def _insert_bet(self, request: PlaceBetRequest) -> PaperBet:
        with self._session.begin_nested():
            existing = self._find_bet_by_slot(request.decision_slot_key)
            if existing is None:
                existing = self._find_bet(request.bet_intent_key)
            if existing is not None:
                return existing
            account = self._locked_account()
            cash_available = account.bankroll_balance - account.reserved_stake
            if request.stake > cash_available:
                raise InsufficientBankrollError(
                    f"stake {request.stake} exceeds cash available {cash_available}"
                )
            account.reserved_stake = account.reserved_stake + request.stake
            decision_at = ensure_utc(request.decision_at)
            reservation = BankrollReservation(
                bet_intent_key=request.bet_intent_key,
                amount=request.stake,
                status=ReservationStatus.HELD,
            )
            bet = PaperBet(
                match_id=request.match_id,
                market=request.market,
                line_key=request.line_key,
                selection=request.selection,
                odds_decimal=request.odds_decimal,
                stake=request.stake,
                bankroll_before=cash_available,
                placed_at=decision_at,
                odds_snapshot_id=request.odds_snapshot_id,
                status=BetStatus.PENDING,
                analysis_run_key=request.analysis_run_key,
                decision_slot_key=request.decision_slot_key,
                bet_intent_key=request.bet_intent_key,
                decision_at=decision_at,
            )
            self._session.add_all([reservation, bet])
            self._session.flush()
            return bet

    def _find_bet(self, bet_intent_key: str) -> PaperBet | None:
        return self._session.execute(
            select(PaperBet).where(PaperBet.bet_intent_key == bet_intent_key)
        ).scalar_one_or_none()

    def _find_bet_by_slot(self, decision_slot_key: str) -> PaperBet | None:
        return self._session.execute(
            select(PaperBet).where(
                PaperBet.decision_slot_key == decision_slot_key
            )
        ).scalar_one_or_none()

    def _get_account(self) -> BankrollAccount | None:
        return self._session.execute(
            select(BankrollAccount).where(
                BankrollAccount.account_id == self._account_id
            )
        ).scalar_one_or_none()

    def ensure_account(self) -> BankrollAccount:
        """Create the paper account if missing; safe to call repeatedly."""
        account = self._get_account()
        if account is not None:
            return account
        account = BankrollAccount(
            account_id=self._account_id,
            currency=self._currency,
            bankroll_balance=self._initial,
            reserved_stake=Decimal("0.00"),
        )
        try:
            with self._session.begin_nested():
                self._session.add(account)
                self._session.flush()
        except IntegrityError:
            existing = self._get_account()
            if existing is None:
                raise
            return existing
        return account

    def _locked_account(self) -> BankrollAccount:
        # Do not preload the account before locking: an identity-map hit would
        # make the FOR UPDATE select return stale reserved_stake/balance values.
        statement = (
            select(BankrollAccount)
            .where(BankrollAccount.account_id == self._account_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        account = self._session.execute(statement).scalar_one_or_none()
        if account is not None:
            return account
        _ = self.ensure_account()
        return self._session.execute(statement).scalar_one()
