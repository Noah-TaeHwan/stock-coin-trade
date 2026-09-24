"""Pin the response contract of POST /api/quant/backtests before the engine rewrite.

frontend/js/quant-lab.js sends exactly this payload and reads these keys.
Phase 3 replaces the engine behind the route; this test keeps the contract.
The metric values themselves are not pinned: several are known to be wrong
(docs/evidence/foundation-2026-09-24.md).
"""

import pytest

pytestmark = pytest.mark.integration

UI_PAYLOAD = {
    "symbol": "005930",
    "strategy": "ma2050",
    "fast": 20,
    "slow": 50,
    "quantity": 10,
    "feeRate": 0.00015,
    "slippage": 0.0005,
}
RESPONSE_KEYS = {
    "strategyId",
    "tradeCount",
    "realizedPnl",
    "totalReturn",
    "sharpeRatio",
    "maxDrawdown",
    "annualReturn",
    "message",
}


def test_backtest_response_keys_match_what_the_ui_reads(client):
    response = client.post("/api/quant/backtests", json=UI_PAYLOAD)
    assert response.status_code == 201, response.get_data(as_text=True)
    body = response.get_json()
    assert set(body) == RESPONSE_KEYS
    assert isinstance(body["strategyId"], int)
    assert isinstance(body["tradeCount"], int)
    for key in ("realizedPnl", "totalReturn", "maxDrawdown", "annualReturn"):
        assert isinstance(body[key], (int, float)), key


def test_results_endpoint_lists_the_stored_trades(client):
    created = client.post("/api/quant/backtests", json=UI_PAYLOAD).get_json()
    response = client.get("/api/quant/results")
    assert response.status_code == 200
    trades = response.get_json()["trades"]
    assert any(trade["strategy_id"] == created["strategyId"] for trade in trades) or created["tradeCount"] == 0
