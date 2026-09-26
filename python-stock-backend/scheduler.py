import logging
import os

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from db import session_scope
from market_bots import run_bot_trading_round
from models import CryptoRank, UpbitMarket
from settings import dart_api_key_from_env

log = logging.getLogger(__name__)

CMC_API_KEY = os.environ.get("CMC_API_KEY", "")


def sync_coinmarketcap_rankings():
    """코인마켓캡 API - 시가총액 top 100 동기화 (1시간 마다 실행)"""
    log.info("saveCoinMarketCapCryptoRank() -> 코인마켓캡 시가총액 Top100 스케쥴러 실행")
    if not CMC_API_KEY:
        log.warning("CMC_API_KEY가 설정되지 않아 동기화를 건너뜁니다.")
        return

    url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest?CMC_PRO_API_KEY={CMC_API_KEY}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    items = resp.json().get("data", [])

    with session_scope() as db:
        db.execute(text("TRUNCATE TABLE crypto_rank"))
        for item in items:
            quote = (item.get("quote") or {}).get("USD") or {}
            db.add(CryptoRank(
                name=item.get("name"),
                symbol=item.get("symbol"),
                api_crypto_id=item.get("id"),
                price=quote.get("price"),
                market_cap=quote.get("market_cap"),
                percent_change24h=quote.get("percent_change_24h"),
                percent_change7d=quote.get("percent_change_7d"),
            ))


def sync_upbit_markets():
    """업비트 API - 거래가능 market 목록 DB 동기화 (오후 6시 1일 1회)"""
    log.info("saveUpbitMarketDatabase() -> 업비트 거래가능 목록 DB 저장 스케쥴러 실행")
    resp = requests.get("https://api.upbit.com/v1/market/all", timeout=10)
    resp.raise_for_status()
    items = resp.json()

    with session_scope() as db:
        existing = {m.market_code for m in db.query(UpbitMarket).all()}
        for item in items:
            code = item.get("market")
            if not code or "KRW" not in code or code in existing:
                continue
            db.add(UpbitMarket(
                market_code=code,
                korean_name=item.get("korean_name"),
                english_name=item.get("english_name"),
            ))


def build_scheduler(scheduler_cls: type[BaseScheduler] = BackgroundScheduler) -> BaseScheduler:
    """Return an unstarted scheduler with the recurring jobs registered.

    worker.py runs it with BlockingScheduler in its own process so the web
    workers never run these jobs.
    """
    import price_sources

    scheduler = scheduler_cls(timezone="Asia/Seoul")
    # External syncs run only where the data source registry allows the source.
    if price_sources.allowed("coinmarketcap"):
        scheduler.add_job(sync_coinmarketcap_rankings, CronTrigger(minute=0, timezone="Asia/Seoul"))
    if price_sources.allowed("upbit"):
        scheduler.add_job(sync_upbit_markets, CronTrigger(hour=18, minute=0, timezone="Asia/Seoul"))
    scheduler.add_job(run_bot_trading_round, IntervalTrigger(minutes=10))
    from member_sessions import purge_expired

    scheduler.add_job(purge_expired, CronTrigger(hour=3, minute=0, timezone="Asia/Seoul"), id="member_session_purge")
    from retention import purge_old_logs, purge_unverified_members

    # 7일 안에 메일 인증을 마치지 않은 가입과 90일 지난 로그를 지운다(개인정보 처리방침의 보관 기간).
    scheduler.add_job(
        purge_unverified_members, CronTrigger(hour=3, minute=10, timezone="Asia/Seoul"), id="member_unverified_purge"
    )
    scheduler.add_job(purge_old_logs, CronTrigger(hour=3, minute=20, timezone="Asia/Seoul"), id="log_retention")
    if price_sources.allowed("dart") and dart_api_key_from_env():
        from dart_radar import collect

        # 5분마다 새 공시만(회당 보통 1회 호출, 하루 약 290~350회), 매시 30분에 하루 전체를 다시 훑는다
        # (683건인 날 7쪽 × 24 ≈ 170회). 합계 하루 약 520회로 키당 약 20,000건 한도(비공식) 안이다.
        # docs/evidence/jev-disclosures-2026-09-26.md
        scheduler.add_job(collect, IntervalTrigger(minutes=5), id="dart_collect")
        scheduler.add_job(collect, CronTrigger(minute=30, timezone="Asia/Seoul"), kwargs={"full": True}, id="dart_sweep")
        # 23:30 이후 올라온 공시는 날짜가 바뀌면 오늘 목록에 없다. 00:10에 전날을 한 번 더 훑는다(약 7회).
        scheduler.add_job(
            collect,
            CronTrigger(hour=0, minute=10, timezone="Asia/Seoul"),
            kwargs={"full": True, "days_ago": 1},
            id="dart_prev_day",
        )
    return scheduler


def start_scheduler() -> BackgroundScheduler:
    scheduler = build_scheduler(BackgroundScheduler)
    scheduler.start()
    return scheduler
