"""Live prices only come from sources the registry allows, and say where they came from."""

from datetime import date
from unittest import mock

import pytest

import market_bots
import price_sources
import stock_market
from app import create_app
from settings import Settings

PUBLIC = Settings(
    profile="public",
    secret_key="p" * 40,
    session_cookie_secure=True,
    admin_email="owner@example.com",
    ratelimit_enabled=True,
)


@pytest.fixture
def public_client():
    application = create_app(PUBLIC)
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.fixture
def no_network():
    """Fail the test if anything tries to reach Yahoo, Naver or KRX."""

    def forbidden(*args, **kwargs):
        raise AssertionError("external market data call in a profile that forbids it")

    with (
        mock.patch.object(stock_market.yf, "Ticker", side_effect=forbidden),
        mock.patch.object(stock_market.requests, "get", side_effect=forbidden),
    ):
        yield


@pytest.fixture(autouse=True)
def clear_caches():
    stock_market._quote_cache.clear()
    stock_market._chart_cache.clear()
    stock_market._index_cache.clear()
    yield
    stock_market._quote_cache.clear()
    stock_market._chart_cache.clear()
    stock_market._index_cache.clear()


def test_public_quote_is_synthetic_and_labelled(public_client, no_network):
    body = public_client.get("/api/stocks/quote?symbol=005930").get_json()
    assert body["source"] == "synthetic"
    assert "실제 시세가 아닙니다" in body["attribution"]
    assert body["name"] == "삼성전자" and body["price"] > 0
    assert "simulated" not in body


def test_public_quote_is_deterministic_for_the_day(public_client, no_network):
    first = public_client.get("/api/stocks/quote?symbol=000660").get_json()
    second = public_client.get("/api/stocks/quote?symbol=000660").get_json()
    assert first == second


def test_public_chart_index_list_and_dashboard_use_no_external_source(public_client, no_network):
    chart = public_client.get("/api/stocks/chart?symbol=005930&period=3m").get_json()
    assert chart["source"] == "synthetic" and len(chart["data"]) > 60
    assert {"x", "o", "h", "l", "c", "v"} <= set(chart["data"][0])
    market = public_client.get("/api/stocks/market").get_json()
    assert market["KOSPI"]["source"] == market["KOSDAQ"]["source"] == "synthetic"
    listing = public_client.get("/api/stocks/list").get_json()
    assert listing["source"] == "builtin" and listing["stocks"]
    with public_client.application.app_context():
        quotes = stock_market.get_dashboard_stock_quotes()
    assert {quote["source"] for quote in quotes.values()} == {"synthetic"}


def test_public_orders_fill_at_the_labelled_synthetic_price(public_client, no_network):
    with public_client.application.app_context():
        price, simulated = stock_market.order_quote("005930")
        expected = price_sources.synthetic_quote("005930")["price"]
    assert (price, simulated) == (expected, False)


def test_local_labels_the_live_source():
    history = mock.Mock(empty=False)
    frame = mock.MagicMock(empty=False)
    frame.__len__.return_value = 2
    frame.iloc.__getitem__.side_effect = lambda i: {"Close": 70_000 if i == -1 else 69_000, "Volume": 5}
    history.history.return_value = frame
    with mock.patch.object(stock_market.yf, "Ticker", return_value=history):
        quote = stock_market.get_quote_cached("005930")
    assert (quote["source"], quote["price"]) == ("yfinance", 70_000)


def test_local_labels_the_offline_fallback_as_simulated():
    with (
        mock.patch.object(stock_market.yf, "Ticker", side_effect=RuntimeError("down")),
        mock.patch.object(stock_market, "_fetch_naver_quote", side_effect=RuntimeError("down")),
    ):
        quote = stock_market.get_quote_cached("005930")
    assert quote["source"] == "simulated" and quote["simulated"] is True


def test_crypto_features_need_upbit_to_be_allowed(client, public_client):
    for path in ("/api/crypto/market-list", "/api/trade/hold", "/api/arb/snapshot"):
        assert public_client.get(path).status_code == 404, path
    local_rules = {rule.rule for rule in client.application.url_map.iter_rules()}
    assert any(rule.startswith("/api/crypto/") for rule in local_rules)
    assert any(rule.startswith("/api/trade/") for rule in local_rules)


def test_worker_skips_jobs_and_trades_whose_sources_are_off(monkeypatch):
    from apscheduler.schedulers.background import BackgroundScheduler

    import scheduler

    monkeypatch.setenv("APP_PROFILE", "public")
    names = [job.func.__name__ for job in scheduler.build_scheduler(BackgroundScheduler).get_jobs()]
    assert names == ["run_bot_trading_round", "purge_expired", "purge_unverified_members", "purge_old_logs"]
    assert market_bots._tradable_asset_classes() == {"STOCK": 3}
    monkeypatch.setenv("APP_PROFILE", "local")
    assert set(market_bots._tradable_asset_classes()) == {"STOCK", "CRYPTO", "ALT"}


def test_synthetic_quote_uses_the_last_two_bars():
    quote = price_sources.synthetic_quote("005930", today=date(2026, 9, 25))
    bars = price_sources.synthetic_bars("005930", date(2026, 9, 25), 10)
    assert quote["price"] == round(bars[-1].close) and quote["prevClose"] == round(bars[-2].close)
