from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import BankrollAccount, LedgerExperiment
from packages.ledger.service import DEFAULT_CURRENCY, INITIAL_BANKROLL
from packages.shared.time import utc_now


def active_experiment(
    session: Session, lane: str = "deterministic"
) -> LedgerExperiment | None:
    """Return the current ledger epoch for a lane, or None for legacy data."""
    return session.scalar(
        select(LedgerExperiment)
        .where(
            LedgerExperiment.is_active.is_(True),
            LedgerExperiment.lane == lane,
        )
        .order_by(LedgerExperiment.created_at.desc(), LedgerExperiment.id.desc())
        .limit(1)
    )


def create_next_experiment(
    session: Session,
    *,
    label: str,
    model_version: str,
    strategy_version: str,
    initial_bankroll: Decimal = INITIAL_BANKROLL,
    currency: str = DEFAULT_CURRENCY,
    lane: str = "deterministic",
) -> LedgerExperiment:
    """Archive the active epoch and open a fresh bankroll/ROI baseline.

    Existing paper bets, decisions and settlements are never deleted. The new
    experiment has its own bankroll account, so the UI starts at the initial
    balance while the previous experiment remains queryable.
    """
    if not label.strip():
        raise ValueError("label must not be blank")
    if not model_version.strip() or not strategy_version.strip():
        raise ValueError("model_version and strategy_version must not be blank")
    if initial_bankroll < 0:
        raise ValueError("initial_bankroll must be non-negative")
    if not lane.strip():
        raise ValueError("lane must not be blank")

    current = active_experiment(session, lane)
    now = utc_now()
    if current is not None:
        current.is_active = False
        current.archived_at = now
        session.flush()

    experiment_id = uuid.uuid4()
    account_id = f"{lane.strip()}:{experiment_id.hex[:16]}"
    experiment = LedgerExperiment(
        id=experiment_id,
        label=label.strip(),
        lane=lane.strip(),
        model_version=model_version.strip(),
        strategy_version=strategy_version.strip(),
        initial_bankroll=initial_bankroll,
        account_id=account_id,
        is_active=True,
        is_legacy=False,
    )
    account = BankrollAccount(
        account_id=account_id,
        currency=currency,
        bankroll_balance=initial_bankroll,
        reserved_stake=Decimal("0.00"),
    )
    session.add_all([experiment, account])
    session.flush()
    return experiment


def ensure_lane_experiment(
    session: Session,
    *,
    lane: str,
    label: str,
    model_version: str,
    strategy_version: str,
    initial_bankroll: Decimal = INITIAL_BANKROLL,
    currency: str = DEFAULT_CURRENCY,
) -> LedgerExperiment:
    """Return the active experiment for a lane, creating it if necessary."""
    existing = active_experiment(session, lane)
    if existing is not None:
        return existing
    return create_next_experiment(
        session,
        label=label,
        model_version=model_version,
        strategy_version=strategy_version,
        initial_bankroll=initial_bankroll,
        currency=currency,
        lane=lane,
    )
