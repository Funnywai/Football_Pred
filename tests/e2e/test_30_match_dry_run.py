from decimal import Decimal

from sqlalchemy import func, select

from packages.db.models import BankrollAccount, ModelPrediction, PaperBet, Settlement
from packages.ingest.dry_run_batch import run_30_match_dry_run


def test_30_match_dry_run_has_no_duplicates_and_no_negative_bankroll(session):
    result = run_30_match_dry_run(session)

    assert result.matches == 30
    assert result.bets == 30
    assert result.predictions == 90
    assert result.settled == 30
    assert result.bankroll >= Decimal(0)
    assert session.scalar(select(func.count()).select_from(PaperBet)) == 30
    assert session.scalar(select(func.count()).select_from(Settlement)) == 30
    assert (
        session.scalar(select(func.count()).select_from(ModelPrediction)) == 90
    )
    account = session.execute(select(BankrollAccount)).scalar_one()
    assert account.reserved_stake == Decimal("0.00")
    assert account.bankroll_balance >= Decimal(0)
    assert session.scalar(
        select(func.count(func.distinct(PaperBet.bet_intent_key)))
    ) == 30
