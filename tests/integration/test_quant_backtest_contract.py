"""Response contract of POST /api/quant/backtests.

frontend/js/quant-lab.js sends this payload and reads these keys. Phase 3
replaced the engine behind the route (src/quantlab); the old keys stay, in
percent, and the new quantlab fields are added next to them.
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
    # 201 for a new run, 200 when the same receipt was already stored.
    assert response.status_code in (200, 201), response.get_data(as_text=True)
    body = response.get_json()
    assert set(body) >= RESPONSE_KEYS
    assert isinstance(body["strategyId"], int)
    assert isinstance(body["tradeCount"], int)
    for key in ("realizedPnl", "totalReturn", "maxDrawdown", "annualReturn"):
        assert isinstance(body[key], (int, float)), key


def test_results_endpoint_lists_the_stored_trades(client):
    created = client.post("/api/quant/backtests", json=UI_PAYLOAD).get_json()
    response = client.get(f"/api/quant/results?strategyId={created['strategyId']}")
    assert response.status_code == 200
    trades = response.get_json()["trades"]
    assert len(trades) == min(created["tradeCount"], 50)
    assert {trade["strategy_id"] for trade in trades} <= {created["strategyId"]}
