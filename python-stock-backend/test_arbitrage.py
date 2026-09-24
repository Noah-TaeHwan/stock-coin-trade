import time
import unittest
from unittest.mock import Mock, patch

import requests
from flask import Flask

import arbitrage
from arbitrage import arb_bp


def _resp(status=200, body=None):
    response = Mock(status_code=status, ok=200 <= status < 300)
    response.json.return_value = body
    return response


class PremiumMathTest(unittest.TestCase):
    def test_kimp_uses_usdt_and_fx_bases(self):
        tickers = {
            "UPBIT": {"BTC": 138_000_000, "USDT": 1_380},
            "OKX": {"BTC": 100_000},
        }
        snap = arbitrage.build_snapshot(tickers, usd_krw=1_370)
        btc = next(c for c in snap["coins"] if c["symbol"] == "BTC")
        self.assertAlmostEqual(btc["kimpUsdtPct"], 0.0)
        self.assertAlmostEqual(btc["kimpFxPct"], (138_000_000 / (100_000 * 1_370) - 1) * 100, places=3)
        self.assertAlmostEqual(snap["fx"]["usdtPremiumPct"], (1_380 / 1_370 - 1) * 100, places=3)
        self.assertEqual(btc["prices"]["OKX"]["krw"], 138_000_000)

    def test_domestic_spread_names_low_and_high_exchange(self):
        tickers = {"UPBIT": {"ETH": 5_000_000}, "BITHUMB": {"ETH": 5_050_000}, "KORBIT": {"ETH": 4_990_000}}
        eth = next(c for c in arbitrage.build_snapshot(tickers, None)["coins"] if c["symbol"] == "ETH")
        self.assertEqual(eth["domesticSpread"]["low"], "KORBIT")
        self.assertEqual(eth["domesticSpread"]["high"], "BITHUMB")
        self.assertAlmostEqual(eth["domesticSpread"]["pct"], (5_050_000 / 4_990_000 - 1) * 100, places=3)
        self.assertIsNone(eth["kimpUsdtPct"])  # 해외 가격·USDT가 없으면 계산하지 않는다.

    def test_missing_prices_stay_null(self):
        snap = arbitrage.build_snapshot({}, None)
        self.assertIsNone(snap["fx"]["usdtKrw"])
        self.assertTrue(all(c["kimpUsdtPct"] is None and c["domesticSpread"]["pct"] is None for c in snap["coins"]))


class OrderbookMathTest(unittest.TestCase):
    def test_vwap_buy_walks_levels(self):
        result = arbitrage.vwap_buy([(100, 1), (110, 1)], 155)
        self.assertAlmostEqual(result["qty"], 1.5)
        self.assertAlmostEqual(result["avgPrice"], 155 / 1.5)
        self.assertFalse(result["insufficient"])

    def test_vwap_buy_flags_insufficient_depth(self):
        result = arbitrage.vwap_buy([(100, 1)], 500)
        self.assertAlmostEqual(result["qty"], 1)
        self.assertTrue(result["insufficient"])

    def test_vwap_sell_walks_levels(self):
        result = arbitrage.vwap_sell([(120, 1), (110, 2)], 2)
        self.assertAlmostEqual(result["proceeds"], 230)
        self.assertFalse(result["insufficient"])
        self.assertTrue(arbitrage.vwap_sell([(120, 1)], 3)["insufficient"])

    def test_fees_turn_small_gross_spread_negative(self):
        buy = {"asks": [(100.0, 1_000)], "bids": [(99.0, 1_000)]}
        sell = {"asks": [(101.0, 1_000)], "bids": [(100.3, 1_000)]}
        free = arbitrage.simulate_pair(buy, sell, 10_000, 0, 0, 0)
        self.assertAlmostEqual(free["grossPct"], 0.3)
        self.assertAlmostEqual(free["netKrw"], 30)
        paid = arbitrage.simulate_pair(buy, sell, 10_000, 0.2, 0.2, 0.5)
        self.assertLess(paid["netKrw"], 0)
        self.assertAlmostEqual(paid["costs"]["withdrawFeeKrw"], 0.5 * 100.3)

    def test_withdraw_fee_larger_than_position(self):
        buy = {"asks": [(100.0, 10)], "bids": []}
        sell = {"asks": [], "bids": [(100.0, 10)]}
        result = arbitrage.simulate_pair(buy, sell, 100, 0, 0, 5)
        self.assertFalse(result["ok"])


class EndpointTest(unittest.TestCase):
    def setUp(self):
        arbitrage._cache.clear()
        app = Flask(__name__)
        app.config.update(TESTING=True)
        app.register_blueprint(arb_bp)
        self.client = app.test_client()

    def fake_get(self, url, params=None, **kwargs):
        if "binance.com" in url:
            return _resp(451, {"code": 0, "msg": "Service unavailable from a restricted location"})
        if "coinone" in url:
            raise requests.ConnectionError("down")
        if "api.upbit.com/v1/ticker" in url:
            return _resp(body=[{"market": "KRW-BTC", "trade_price": 138_000_000}, {"market": "KRW-USDT", "trade_price": 1_380}])
        if "bithumb.com/public/ticker" in url:
            return _resp(body={"status": "0000", "data": {"BTC": {"closing_price": "138100000"}}})
        if "korbit" in url:
            return _resp(body={"success": True, "data": [{"symbol": "btc_krw", "close": "137900000"}]})
        if "okx.com/api/v5/market/tickers" in url:
            return _resp(body={"code": "0", "data": [{"instId": "BTC-USDT", "last": "100000"}]})
        if "er-api" in url:
            return _resp(body={"rates": {"KRW": 1_370}, "time_last_update_utc": "Thu, 24 Sep 2026 00:00:00 +0000"})
        return _resp(404, {})

    def test_snapshot_survives_blocked_and_failed_sources(self):
        with patch("arbitrage.requests.get", side_effect=self.fake_get):
            response = self.client.get("/api/arb/snapshot")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["sources"]["BINANCE"]["status"], "blocked")
        self.assertEqual(body["sources"]["COINONE"]["status"], "error")
        self.assertEqual(body["sources"]["UPBIT"]["status"], "ok")
        btc = next(c for c in body["coins"] if c["symbol"] == "BTC")
        self.assertAlmostEqual(btc["kimpUsdtPct"], 0.0)
        self.assertEqual(btc["globalRef"], "OKX")

    def test_snapshot_is_cached(self):
        with patch("arbitrage.requests.get", side_effect=self.fake_get) as get:
            self.client.get("/api/arb/snapshot")
            calls = get.call_count
            self.client.get("/api/arb/snapshot")
            self.assertEqual(get.call_count, calls)

    def test_cache_expires(self):
        loader = Mock(side_effect=[1, 2])
        self.assertEqual(arbitrage._cached("k", 60, loader), 1)
        self.assertEqual(arbitrage._cached("k", 60, loader), 1)
        with patch("arbitrage.time.monotonic", return_value=time.monotonic() + 61):
            self.assertEqual(arbitrage._cached("k", 60, loader), 2)

    def test_unknown_symbol_and_interval(self):
        self.assertEqual(self.client.get("/api/arb/FOO/matrix").status_code, 404)
        self.assertEqual(self.client.get("/api/arb/FOO/history").status_code, 404)
        self.assertEqual(self.client.get("/api/arb/BTC/history?interval=5m").status_code, 400)

    def test_history_aligns_candles(self):
        points = arbitrage.premium_series({1: 1_390, 2: 1_380, 3: 1_000}, {1: 1.0, 2: 1.0}, {1: 1_380, 2: 1_380, 3: 1_380})
        self.assertEqual([p["time"] for p in points], [1, 2])
        self.assertAlmostEqual(points[0]["premiumPct"], (1_390 / 1_380 - 1) * 100, places=3)
        self.assertEqual(points[1]["premiumPct"], 0.0)


if __name__ == "__main__":
    unittest.main()
