"""quantlab behind POST /api/quant/backtests: receipts, idempotency, stored rows."""

import pytest
from sqlalchemy import text

import quant

pytestmark = pytest.mark.integration

PAYLOAD = {
    "symbol": "005930",
    "strategy": "trend",
    "fast": 7,
    "slow": 30,
    "feeRate": 0.0002,
    "slippage": 0.0003,
    "start": "2025-01-01",
    "end": "2026-09-01",
}


def _count(sql, **params):
    with quant._db().connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def test_backtest_returns_a_receipt_and_a_daily_curve(client):
    body = client.post("/api/quant/backtests", json=PAYLOAD).get_json()
    receipt = body["receipt"]
    assert body["receiptId"] == receipt["receiptId"] and len(receipt["receiptId"]) == 64
    assert receipt["engineVersion"].startswith("quantlab/")
    assert receipt["params"]["fast"] == 7 and receipt["params"]["slow"] == 30
    assert receipt["params"]["costs"] == {"fee_bps": 2.0, "slippage_bps": 3.0, "sell_tax_bps": 0.0}
    assert body["equity"] and len(body["equity"]) == receipt["barCount"]
    assert body["totalReturn"] == pytest.approx(body["metrics"]["totalReturn"] * 100, abs=1e-3)
    assert body["maxDrawdown"] == pytest.approx(body["metrics"]["maxDrawdown"] * 100, abs=1e-3)
    assert set(body["benchmark"]) == set(body["metrics"])
    assert body["receipt"]["firstBar"] >= "2025-01-01"


def test_the_same_request_is_one_run(client):
    first = client.post("/api/quant/backtests", json={**PAYLOAD, "fast": 8}).get_json()
    runs = _count("SELECT count(*) FROM backtest_runs")
    strategies = _count("SELECT count(*) FROM strategies")
    again = client.post("/api/quant/backtests", json={**PAYLOAD, "fast": 8})
    assert again.status_code == 200
    body = again.get_json()
    assert body["reused"] is True
    assert (body["receiptId"], body["strategyId"]) == (first["receiptId"], first["strategyId"])
    assert body["metrics"] == first["metrics"]
    assert _count("SELECT count(*) FROM backtest_runs") == runs
    assert _count("SELECT count(*) FROM strategies") == strategies
    stored = _count("SELECT count(*) FROM trade_logs WHERE strategy_id = :id", id=first["strategyId"])
    assert stored == first["tradeCount"]


def test_ui_rates_become_exact_basis_points(client):
    body = client.post("/api/quant/backtests", json={**PAYLOAD, "feeRate": 0.00015, "slippage": 0.0005}).get_json()
    assert body["parameters"]["costs"] == {"fee_bps": 1.5, "slippage_bps": 5.0, "sell_tax_bps": 0.0}


def test_a_different_cost_is_a_different_run(client):
    a = client.post("/api/quant/backtests", json=PAYLOAD).get_json()
    b = client.post("/api/quant/backtests", json={**PAYLOAD, "feeRate": 0.001}).get_json()
    assert a["receiptId"] != b["receiptId"]


def test_crypto_positions_are_fractional_and_annualised_over_365_days(client):
    body = client.post("/api/quant/backtests", json={**PAYLOAD, "symbol": "KRW-BTC", "strategy": "ma2050"}).get_json()
    assert body["parameters"]["fractional"] is True and body["metrics"]["periodsPerYear"] == 365
    if body["trades"]:
        assert body["trades"][0]["units"] != int(body["trades"][0]["units"])


@pytest.mark.parametrize(
    "change",
    [
        {"fast": 50, "slow": 20},
        {"strategy": "nope"},
        {"feeRate": "x"},
        {"start": "2026-01-01", "end": "2025-01-01"},
        {"slippage": 0.9},
        {"symbol": "../etc"},
        {"initialCapital": 1},
    ],
)
def test_bad_input_is_a_400_not_a_500(client, change):
    response = client.post("/api/quant/backtests", json={**PAYLOAD, **change})
    assert response.status_code == 400, response.get_data(as_text=True)


def test_unknown_symbol_is_a_404(client):
    assert client.post("/api/quant/backtests", json={**PAYLOAD, "symbol": "ZZZZ9"}).status_code == 404


def test_a_stored_run_can_be_fetched_by_its_receipt(client):
    created = client.post("/api/quant/backtests", json=PAYLOAD).get_json()
    fetched = client.get(f"/api/quant/backtests/{created['receiptId']}").get_json()
    assert fetched["metrics"] == created["metrics"] and fetched["strategyId"] == created["strategyId"]
    assert fetched["receipt"]["inputSha256"] == created["receipt"]["inputSha256"]
    assert client.get(f"/api/quant/backtests/{'0' * 64}").status_code == 404
    assert client.get("/api/quant/backtests/not-a-receipt").status_code == 400


def test_sources_endpoint_reports_the_registry_for_this_profile(client):
    body = client.get("/api/quant/sources").get_json()
    assert body["profile"] == "local"
    by_id = {source["id"]: source for source in body["sources"]}
    assert by_id["synthetic"]["enabled"] is True and by_id["synthetic"]["attribution"]


def _store(symbol, source):
    from datetime import UTC, datetime, timedelta

    from marketdata import store
    from marketdata.bars import Bar

    start = datetime(2025, 3, 3, tzinfo=UTC)
    bars = [
        Bar(symbol, start + timedelta(days=i), 100 + i, 101 + i, 99 + i, 100.5 + i, 1000.0, source) for i in range(90)
    ]
    with quant._db().begin() as conn:
        conn.execute(text("DELETE FROM market_data WHERE symbol = :s"), {"s": symbol})
        store.upsert_bars(conn, bars)


def _public_client():
    from app import create_app
    from settings import Settings

    application = create_app(
        Settings(profile="public", secret_key="q" * 40, session_cookie_secure=False, admin_email="o@example.com")
    )
    application.config.update(TESTING=True)
    return application.test_client()


def test_backtests_only_use_sources_the_registry_allows_in_this_profile(client):
    body = {"symbol": "SRCUPBIT", "strategy": "rsi", "start": "2025-01-01", "end": "2025-12-31"}
    _store("SRCUPBIT", "upbit")  # enabled for local, off for public (terms not checked)
    assert client.post("/api/quant/backtests", json=body).status_code in (200, 201)
    blocked = _public_client().post("/api/quant/backtests", json=body)
    assert blocked.status_code == 403 and "upbit" in blocked.get_json()["message"]
    _store("SRCMYST", "mystery_feed")  # not in the registry at all
    assert client.post("/api/quant/backtests", json={**body, "symbol": "SRCMYST"}).status_code == 403


def test_the_seeded_sample_data_is_allowed_in_public():
    response = _public_client().post("/api/quant/backtests", json={"symbol": "005930", "strategy": "ma2050"})
    assert response.status_code in (200, 201) and response.get_json()["source"] == ["synthetic_sql"]


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", "null", ""])
def test_a_body_that_is_not_a_json_object_is_a_400(client, raw):
    response = client.post("/api/quant/backtests", data=raw, content_type="application/json")
    assert response.status_code == 400
