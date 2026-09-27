"""공개 사이트는 코인을 다루지 않는다: 퀀트 API도 6자리 국내 주식 종목코드만 받는다(노아 결정, 9/27 검증)."""

import pytest

import quant
from app import create_app
from settings import Settings

PUBLIC = Settings(profile="public", secret_key="p" * 40, session_cookie_secure=True, admin_email="owner@example.com")
LOCAL = Settings(profile="local", secret_key="k" * 40, session_cookie_secure=False)


@pytest.fixture(scope="module")
def public_app():
    return create_app(PUBLIC)


@pytest.fixture(scope="module")
def local_app():
    return create_app(LOCAL)


@pytest.mark.parametrize("symbol", ["KRW-BTC", "BTC", "AAPL", "12345"])
def test_public_backtest_refuses_anything_but_a_six_digit_stock_code(public_app, symbol):
    with public_app.app_context(), pytest.raises(ValueError, match="6자리"):
        quant._backtest_request({"symbol": symbol})


def test_public_backtest_accepts_a_stock_code(public_app):
    with public_app.app_context():
        assert quant._backtest_request({"symbol": "005930"})[0] == "005930"


def test_local_backtest_still_accepts_coins(local_app):
    with local_app.app_context():
        assert quant._backtest_request({"symbol": "KRW-BTC"})[0] == "KRW-BTC"


def test_public_query_routes_refuse_coin_symbols(public_app):
    with public_app.test_request_context("/api/quant/market-data?symbol=KRW-BTC"), pytest.raises(ValueError):
        quant._params()


def test_public_overview_lists_only_stock_codes():
    assert quant.visible_symbols(["000660", "005930", "KRW-BTC"], "public") == ["000660", "005930"]
    assert quant.visible_symbols(["000660", "KRW-BTC"], "local") == ["000660", "KRW-BTC"]
    assert quant.visible_symbols(None, "public") == []
