from datetime import timedelta
from unittest.mock import patch

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import scheduler


def _jobs_by_function(sched):
    return {job.func.__name__: job for job in sched.get_jobs()}


def test_build_scheduler_registers_the_recurring_jobs_without_starting():
    sched = scheduler.build_scheduler(BackgroundScheduler)
    try:
        assert not sched.running
        jobs = _jobs_by_function(sched)
        assert set(jobs) == {
            "sync_coinmarketcap_rankings",
            "sync_upbit_markets",
            "run_bot_trading_round",
            "purge_expired",
        }

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

        purge = jobs["purge_expired"].trigger
        assert isinstance(purge, CronTrigger) and str(purge.timezone) == "Asia/Seoul"
        assert str(purge.fields[purge.FIELD_NAMES.index("hour")]) == "3"
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

    assert started == [["purge_expired", "run_bot_trading_round", "sync_coinmarketcap_rankings", "sync_upbit_markets"]]


def test_dart_radar_jobs_need_the_source_and_a_key(monkeypatch):
    import price_sources

    monkeypatch.delenv("DART_API_KEY", raising=False)
    assert "collect" not in _jobs_by_function(scheduler.build_scheduler(BackgroundScheduler))

    monkeypatch.setenv("DART_API_KEY", "k")
    sched = scheduler.build_scheduler(BackgroundScheduler)
    jobs = {job.id: job for job in sched.get_jobs()}
    assert jobs["dart_collect"].trigger.interval == timedelta(minutes=5) and jobs["dart_collect"].kwargs == {}
    sweep = jobs["dart_sweep"].trigger
    assert jobs["dart_sweep"].kwargs == {"full": True}
    assert str(sweep.fields[sweep.FIELD_NAMES.index("minute")]) == "30"
    # 자정 직전 공시를 놓치지 않게 00:10에 전날을 한 번 더 훑는다.
    prev = jobs["dart_prev_day"].trigger
    assert jobs["dart_prev_day"].kwargs == {"full": True, "days_ago": 1}
    assert [str(prev.fields[prev.FIELD_NAMES.index(f)]) for f in ("hour", "minute")] == ["0", "10"]
    assert str(prev.timezone) == "Asia/Seoul"

    # public처럼 소스가 막힌 프로필에서는 키가 있어도 걸지 않는다.
    monkeypatch.setattr(price_sources, "allowed", lambda source_id: source_id != "dart")
    assert "collect" not in _jobs_by_function(scheduler.build_scheduler(BackgroundScheduler))
