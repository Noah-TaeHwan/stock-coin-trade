"""Order price source: simulated fallback is flagged, and refused when asked."""

from contextlib import contextmanager
from unittest import mock

import pytest

import market_bots
import member_sessions
import openapi
import stock_market
import stock_trading
import stocks
from app import create_app
from settings import Settings

SYMBOL = "005930"  # one of the built-in symbols that has a simulated fallback


def _live_quote(symbol):
    return {"symbol": symbol, "price": 70_000, "prevClose": 69_000, "volume": 10}


def test_live_quote_is_not_flagged():
    with mock.patch.object(stock_market, "get_quote_cached", side_effect=_live_quote):
        assert stock_market.order_quote(SYMBOL) == (70_000, False)


def test_quote_marked_simulated_is_flagged():
    quote = {**_live_quote(SYMBOL), "simulated": True}
    with mock.patch.object(stock_market, "get_quote_cached", return_value=quote):
        assert stock_market.order_quote(SYMBOL)[1] is True


def test_quote_failure_falls_back_to_a_flagged_simulated_price():
    with mock.patch.object(stock_market, "get_quote_cached", side_effect=RuntimeError("down")):
        price, simulated = stock_market.order_quote(SYMBOL)
    assert simulated is True
    assert price > 0
    # current_price keeps its old contract: a bare price.
    with mock.patch.object(stock_market, "get_quote_cached", side_effect=RuntimeError("down")):
        assert isinstance(stock_market.current_price(SYMBOL), int)


def test_refusing_simulated_prices_stops_before_touching_the_database():
    db = mock.Mock()
    with (
        mock.patch.object(stock_market, "get_quote_cached", side_effect=RuntimeError("down")),
        pytest.raises(ValueError, match="실시간 시세"),
    ):
        stock_trading.execute_order(db, mock.Mock(), SYMBOL, "BUY", 1, allow_simulated_price=False)
    db.refresh.assert_not_called()
    db.query.assert_not_called()


def test_only_the_public_profile_refuses_simulated_prices():
    assert stock_trading.allows_simulated_price("local") is True
    assert stock_trading.allows_simulated_price("public") is False


@contextmanager
def _fake_session_scope():
    yield mock.Mock()


def _live_session_store():
    """서버 세션 표가 이 쿠키를 살아 있는 세션으로 답하는 가짜 엔진."""
    now = member_sessions._now()
    conn = mock.MagicMock()
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "member_id": 1,
        "created_at": now,
        "last_seen_at": now,
    }
    engine = mock.MagicMock()
    engine.begin.return_value.__enter__.return_value = conn
    return engine


def _public_app():
    settings = Settings(profile="public", secret_key="p" * 40, session_cookie_secure=True)
    app = create_app(settings)
    app.config.update(TESTING=True)
    return app


@pytest.mark.parametrize(("profile", "expected"), [("local", True), ("public", False)])
def test_web_order_route_passes_the_profile_decision(app, profile, expected):
    app = _public_app() if profile == "public" else app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["member_id"], sess["sid"] = 1, "live-token"
    with (
        mock.patch.object(member_sessions, "engine", _live_session_store()),
        mock.patch.object(stocks, "session_scope", _fake_session_scope),
        mock.patch.object(stock_trading, "execute_order", return_value={"status": "ok"}) as execute,
    ):
        response = client.post("/api/stocks/orders/buy", json={"symbol": SYMBOL, "quantity": 1})
    assert response.status_code == 200
    assert execute.call_args.kwargs["allow_simulated_price"] is expected


@pytest.mark.parametrize(("profile", "expected"), [("local", True), ("public", False)])
def test_openapi_order_route_passes_the_profile_decision(app, profile, expected):
    app = _public_app() if profile == "public" else app
    with (
        mock.patch.object(openapi, "session_scope", _fake_session_scope),
        mock.patch.object(stock_trading, "execute_order", return_value={"status": "ok"}) as execute,
        app.test_request_context(
            "/openapi/v1/orders", method="POST", json={"symbol": SYMBOL, "side": "BUY", "quantity": 1}
        ),
    ):
        openapi.g.member_id = 1
        # Call the view underneath require_api_key; key lookup needs the database.
        response = openapi.place_order.__wrapped__()
    assert response.status_code == 200
    assert execute.call_args.kwargs["allow_simulated_price"] is expected


def test_one_failing_bot_does_not_stop_the_round(monkeypatch):
    committed = []

    @contextmanager
    def scope():
        session = mock.Mock()
        session.query.return_value.filter.return_value.all.return_value = [(1,), (2,), (3,)]
        session.get.side_effect = lambda _model, member_id: mock.Mock(member_id=member_id, username=f"bot{member_id}")
        yield session
        committed.append(session)

    def action(_db, member):
        if member.member_id == 1:
            raise RuntimeError("database error for one bot")
        return "주식 매수"

    monkeypatch.setattr(market_bots, "session_scope", scope)
    monkeypatch.setattr(market_bots, "_random_action_for_bot", action)
    monkeypatch.setattr(market_bots.random, "sample", lambda ids, k: list(ids))
    market_bots.run_bot_trading_round()
    # One scope lists the bots, then one per bot; the failing bot's scope never commits.
    assert len(committed) == 1 + 2


@pytest.mark.parametrize("simulated", [False, True])
def test_order_record_keeps_whether_the_fill_used_a_simulated_price(simulated):
    db = mock.MagicMock()
    member = mock.Mock(member_id=7, asset=10**9)
    with (
        mock.patch.object(stock_trading, "order_quote", return_value=(70_000, simulated)),
        mock.patch.object(stock_trading, "_get_position", return_value=None),
    ):
        stock_trading.execute_order(db, member, SYMBOL, "BUY", 1)
    orders = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], stock_trading.StockOrder)]
    assert [o.simulated for o in orders] == [simulated]
