"""Coin arbitrage (ARB) calculations and /api/arb routes, with every exchange call mocked."""

import time
from unittest.mock import Mock, patch

import pytest
import requests
from flask import Flask

import arbitrage


def _resp(status=200, body=None):
    response = Mock(status_code=status, ok=200 <= status < 300)
    response.json.return_value = body
    return response


def _coin(snapshot, symbol):
    return next(c for c in snapshot["coins"] if c["symbol"] == symbol)


# ── premium math ─────────────────────────────────────────────────────────────


def test_kimp_uses_usdt_and_fx_bases():
    tickers = {"UPBIT": {"BTC": 138_000_000, "USDT": 1_380}, "OKX": {"BTC": 100_000}}
    snap = arbitrage.build_snapshot(tickers, usd_krw=1_370)
    btc = _coin(snap, "BTC")
    assert btc["kimpUsdtPct"] == pytest.approx(0.0)
    assert btc["kimpFxPct"] == pytest.approx((138_000_000 / (100_000 * 1_370) - 1) * 100, abs=1e-3)
    assert snap["fx"]["usdtPremiumPct"] == pytest.approx((1_380 / 1_370 - 1) * 100, abs=1e-3)
    assert btc["prices"]["OKX"]["krw"] == 138_000_000


def test_domestic_spread_names_low_and_high_exchange():
    tickers = {"UPBIT": {"ETH": 5_000_000}, "BITHUMB": {"ETH": 5_050_000}, "KORBIT": {"ETH": 4_990_000}}
    eth = _coin(arbitrage.build_snapshot(tickers, None), "ETH")
    assert eth["domesticSpread"]["low"] == "KORBIT"
    assert eth["domesticSpread"]["high"] == "BITHUMB"
    assert eth["domesticSpread"]["pct"] == pytest.approx((5_050_000 / 4_990_000 - 1) * 100, abs=1e-3)
    # Without an overseas price and a USDT rate there is no premium to report.
    assert eth["kimpUsdtPct"] is None


def test_missing_prices_stay_null():
    snap = arbitrage.build_snapshot({}, None)
    assert snap["fx"]["usdtKrw"] is None
    assert all(c["kimpUsdtPct"] is None and c["domesticSpread"]["pct"] is None for c in snap["coins"])


def test_history_series_keeps_only_aligned_candles():
    points = arbitrage.premium_series({1: 1_390, 2: 1_380, 3: 1_000}, {1: 1.0, 2: 1.0}, {1: 1_380, 2: 1_380, 3: 1_380})
    assert [p["time"] for p in points] == [1, 2]
    assert points[0]["premiumPct"] == pytest.approx((1_390 / 1_380 - 1) * 100, abs=1e-3)
    assert points[1]["premiumPct"] == 0.0


# ── order-book math ──────────────────────────────────────────────────────────


def test_vwap_buy_walks_levels():
    result = arbitrage.vwap_buy([(100, 1), (110, 1)], 155)
    assert result["qty"] == pytest.approx(1.5)
    assert result["avgPrice"] == pytest.approx(155 / 1.5)
    assert not result["insufficient"]


def test_vwap_buy_flags_insufficient_depth():
    result = arbitrage.vwap_buy([(100, 1)], 500)
    assert result["qty"] == pytest.approx(1)
    assert result["insufficient"]


def test_vwap_sell_walks_levels():
    result = arbitrage.vwap_sell([(120, 1), (110, 2)], 2)
    assert result["proceeds"] == pytest.approx(230)
    assert not result["insufficient"]
    assert arbitrage.vwap_sell([(120, 1)], 3)["insufficient"]


def test_fees_turn_a_small_gross_spread_negative():
    buy = {"asks": [(100.0, 1_000)], "bids": [(99.0, 1_000)]}
    sell = {"asks": [(101.0, 1_000)], "bids": [(100.3, 1_000)]}
    free = arbitrage.simulate_pair(buy, sell, 10_000, 0, 0, 0)
    assert free["grossPct"] == pytest.approx(0.3)
    assert free["netKrw"] == pytest.approx(30)
    paid = arbitrage.simulate_pair(buy, sell, 10_000, 0.2, 0.2, 0.5)
    assert paid["netKrw"] < 0
    assert paid["costs"]["withdrawFeeKrw"] == pytest.approx(0.5 * 100.3)


def test_withdraw_fee_larger_than_the_position_is_not_viable():
    buy = {"asks": [(100.0, 10)], "bids": []}
    sell = {"asks": [], "bids": [(100.0, 10)]}
    assert not arbitrage.simulate_pair(buy, sell, 100, 0, 0, 5)["ok"]


def test_cache_expires_after_ttl():
    arbitrage._cache.clear()
    loader = Mock(side_effect=[1, 2])
    assert arbitrage._cached("k", 60, loader) == 1
    assert arbitrage._cached("k", 60, loader) == 1
    with patch("arbitrage.time.monotonic", return_value=time.monotonic() + 61):
        assert arbitrage._cached("k", 60, loader) == 2


# ── routes ───────────────────────────────────────────────────────────────────


def _fake_exchange_get(url, params=None, **kwargs):
    if "binance.com" in url:
        return _resp(451, {"code": 0, "msg": "Service unavailable from a restricted location"})
    if "coinone" in url:
        raise requests.ConnectionError("down")
    if "api.upbit.com/v1/ticker" in url:
        return _resp(
            body=[{"market": "KRW-BTC", "trade_price": 138_000_000}, {"market": "KRW-USDT", "trade_price": 1_380}]
        )
    if "bithumb.com/public/ticker" in url:
        return _resp(body={"status": "0000", "data": {"BTC": {"closing_price": "138100000"}}})
    if "korbit" in url:
        return _resp(body={"success": True, "data": [{"symbol": "btc_krw", "close": "137900000"}]})
    if "okx.com/api/v5/market/tickers" in url:
        return _resp(body={"code": "0", "data": [{"instId": "BTC-USDT", "last": "100000"}]})
    if "er-api" in url:
        return _resp(body={"rates": {"KRW": 1_370}, "time_last_update_utc": "Thu, 24 Sep 2026 00:00:00 +0000"})
    return _resp(404, {})


@pytest.fixture
def arb_client():
    arbitrage._cache.clear()
    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True)
    flask_app.register_blueprint(arbitrage.arb_bp)
    return flask_app.test_client()


def test_snapshot_survives_blocked_and_failed_sources(arb_client):
    with patch("arbitrage.requests.get", side_effect=_fake_exchange_get):
        response = arb_client.get("/api/arb/snapshot")
    assert response.status_code == 200
    body = response.get_json()
    assert body["sources"]["BINANCE"]["status"] == "blocked"
    assert body["sources"]["COINONE"]["status"] == "error"
    assert body["sources"]["UPBIT"]["status"] == "ok"
    btc = _coin(body, "BTC")
    assert btc["kimpUsdtPct"] == pytest.approx(0.0)
    assert btc["globalRef"] == "OKX"


def test_snapshot_is_served_from_cache(arb_client):
    with patch("arbitrage.requests.get", side_effect=_fake_exchange_get) as get:
        arb_client.get("/api/arb/snapshot")
        calls = get.call_count
        arb_client.get("/api/arb/snapshot")
    assert get.call_count == calls


@pytest.mark.parametrize(
    ("path", "status"),
    [("/api/arb/FOO/matrix", 404), ("/api/arb/FOO/history", 404), ("/api/arb/BTC/history?interval=5m", 400)],
)
def test_rejects_unknown_symbol_and_interval(arb_client, path, status):
    assert arb_client.get(path).status_code == status
