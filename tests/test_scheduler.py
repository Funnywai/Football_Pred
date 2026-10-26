from app.config import Settings
from app.scheduler import build_scheduler


class _FakeProvider:
    name = "fake"

    async def fetch_leagues(self):
        return []

    async def fetch_fixtures(self, date_from, date_to):
        return []

    async def fetch_odds(self, fixtures):
        return []

    async def fetch_results(self, date_from, date_to):
        return []


def test_build_scheduler_registers_expected_jobs():
    settings = Settings(_env_file=None, sync_odds_interval=600, sync_settle_interval=900)
    scheduler = build_scheduler(settings, None, _FakeProvider(), _FakeProvider())
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {
        "sync_odds",
        "settle_results",
        "prune_odds",
        "ledger_update",
        "shadow_ledger_update",
        "clv_update",
    }
    assert jobs["sync_odds"].trigger.interval.total_seconds() == 600
    assert jobs["settle_results"].trigger.interval.total_seconds() == 900
    assert jobs["prune_odds"].trigger.__class__.__name__ == "CronTrigger"
    assert jobs["ledger_update"].trigger.interval.total_seconds() == 3600
    assert jobs["shadow_ledger_update"].trigger.interval.total_seconds() == 3600
    assert jobs["clv_update"].trigger.interval.total_seconds() == 3600


def test_build_scheduler_without_ledger_when_disabled():
    settings = Settings(_env_file=None, ledger_enable=False)
    scheduler = build_scheduler(settings, None, _FakeProvider(), _FakeProvider())
    jobs = {job.id for job in scheduler.get_jobs()}
    assert jobs == {"sync_odds", "settle_results", "prune_odds", "clv_update"}


def test_build_scheduler_without_shadow_when_disabled():
    settings = Settings(_env_file=None, shadow_ledger_enable=False)
    scheduler = build_scheduler(settings, None, _FakeProvider(), _FakeProvider())
    jobs = {job.id for job in scheduler.get_jobs()}
    assert jobs == {"sync_odds", "settle_results", "prune_odds", "ledger_update", "clv_update"}


def test_build_scheduler_without_clv_when_disabled():
    settings = Settings(_env_file=None, clv_enable=False)
    scheduler = build_scheduler(settings, None, _FakeProvider(), _FakeProvider())
    jobs = {job.id for job in scheduler.get_jobs()}
    assert jobs == {
        "sync_odds",
        "settle_results",
        "prune_odds",
        "ledger_update",
        "shadow_ledger_update",
    }
