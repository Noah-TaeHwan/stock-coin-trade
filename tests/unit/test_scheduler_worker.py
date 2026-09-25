from datetime import timedelta
from unittest.mock import patch

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import scheduler


def _jobs_by_function(sched):
    return {job.func.__name__: job for job in sched.get_jobs()}


def test_build_scheduler_registers_the_three_jobs_without_starting():
    sched = scheduler.build_scheduler(BackgroundScheduler)
    try:
        assert not sched.running
        jobs = _jobs_by_function(sched)
        assert set(jobs) == {"sync_coinmarketcap_rankings", "sync_upbit_markets", "run_bot_trading_round"}

        cmc = jobs["sync_coinmarketcap_rankings"].trigger
        assert isinstance(cmc, CronTrigger)
        assert str(cmc.timezone) == "Asia/Seoul"
        assert str(cmc.fields[cmc.FIELD_NAMES.index("minute")]) == "0"

        upbit = jobs["sync_upbit_markets"].trigger
        assert isinstance(upbit, CronTrigger)
        assert str(upbit.fields[upbit.FIELD_NAMES.index("hour")]) == "18"

        bots = jobs["run_bot_trading_round"].trigger
        assert isinstance(bots, IntervalTrigger)
        assert bots.interval == timedelta(minutes=10)
    finally:
        if sched.running:
            sched.shutdown(wait=False)


def test_worker_runs_the_same_jobs_in_a_blocking_scheduler():
    started = []

    def fake_start(self, *args, **kwargs):
        started.append(sorted(job.func.__name__ for job in self.get_jobs()))

    with patch.object(BlockingScheduler, "start", fake_start):
        import worker

        worker.main()

    assert started == [["run_bot_trading_round", "sync_coinmarketcap_rankings", "sync_upbit_markets"]]
