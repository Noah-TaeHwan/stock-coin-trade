"""deskmcp: tool surface, annotations, error mapping and request shapes (no network)."""

import json

import pytest
from mcp import Client

from deskmcp.client import DeskAPI
from deskmcp.server import build_server, from_env

RECEIPT = "a" * 64


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    """Records requests and answers from a {(method, path): (status, body)} table."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def request(self, method, url, headers=None, timeout=None, **kwargs):
        path = url.removeprefix("http://desk.test")
        self.calls.append({"method": method, "path": path, "headers": headers or {}, **kwargs})
        status, body = self.routes.get((method, path), (404, {"message": "not found"}))
        return FakeResponse(status, body)


BACKTEST = {
    "receiptId": RECEIPT,
    "reused": False,
    "strategy": {"name": "ma2050"},
    "parameters": {"fast": 20},
    "metrics": {"sharpe": 0.5},
    "benchmark": {"sharpe": 0.3},
    "tradeCount": 4,
    "receipt": {"receiptId": RECEIPT},
    "equity": [{"t": "2025-01-02"}] * 500,
    "trades": [{}] * 4,
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _server(routes, api_key="secret-key", allow_orders=False):
    session = FakeSession(routes)
    return build_server(DeskAPI("http://desk.test", api_key, session=session), allow_orders), session


async def _tools(server):
    async with Client(server) as client:
        return {tool.name: tool for tool in (await client.list_tools()).tools}


@pytest.mark.anyio
async def test_default_tools_are_read_only_or_idempotent_and_no_order_tool():
    server, _ = _server({})
    tools = await _tools(server)
    assert set(tools) == {
        "list_sources",
        "get_quote",
        "get_account",
        "get_positions",
        "list_orders",
        "run_backtest",
        "get_backtest",
    }
    for name, tool in tools.items():
        if name == "run_backtest":
            assert tool.annotations.idempotent_hint and not tool.annotations.destructive_hint
        else:
            assert tool.annotations.read_only_hint, name


@pytest.mark.anyio
async def test_order_tool_exists_only_when_enabled_and_is_marked_destructive():
    server, _ = _server({}, allow_orders=True)
    tool = (await _tools(server))["place_paper_order"]
    assert tool.annotations.destructive_hint and not tool.annotations.read_only_hint
    assert "place_paper_order" not in await _tools(from_env({"DESK_API_KEY": "k"}))
    assert "place_paper_order" in await _tools(from_env({"DESK_API_KEY": "k", "DESK_MCP_ALLOW_ORDERS": "1"}))


@pytest.mark.anyio
async def test_account_tools_send_the_api_key_as_a_bearer_token():
    server, session = _server({("GET", "/openapi/v1/account"): (200, {"cash": 1000})})
    async with Client(server) as client:
        result = await client.call_tool("get_account", {})
    assert not result.is_error and result.structured_content == {"cash": 1000}
    assert session.calls[0]["headers"]["Authorization"] == "Bearer secret-key"


@pytest.mark.anyio
async def test_research_tools_do_not_send_the_api_key():
    server, session = _server({("GET", "/api/quant/sources"): (200, {"profile": "local", "sources": []})})
    async with Client(server) as client:
        await client.call_tool("list_sources", {})
    assert "Authorization" not in session.calls[0]["headers"]


@pytest.mark.anyio
async def test_missing_api_key_is_a_tool_error_without_a_request():
    server, session = _server({}, api_key="")
    async with Client(server) as client:
        result = await client.call_tool("get_positions", {})
    assert result.is_error and "DESK_API_KEY" in result.content[0].text
    assert session.calls == []


@pytest.mark.anyio
async def test_desk_errors_become_tool_errors_with_the_server_message():
    server, _ = _server({("GET", "/openapi/v1/quote/ZZZ"): (404, {"message": "종목을 찾을 수 없습니다."})})
    async with Client(server) as client:
        result = await client.call_tool("get_quote", {"symbol": "zzz"})
    assert result.is_error and "종목을 찾을 수 없습니다." in result.content[0].text and "404" in result.content[0].text


@pytest.mark.anyio
@pytest.mark.parametrize("symbol", ["../account", "005930/../x", "a" * 21, ""])
async def test_symbols_cannot_escape_the_quote_path(symbol):
    server, session = _server({})
    async with Client(server) as client:
        result = await client.call_tool("get_quote", {"symbol": symbol})
    assert result.is_error and session.calls == []


@pytest.mark.anyio
async def test_run_backtest_converts_bps_and_drops_the_bulky_arrays():
    server, session = _server({("POST", "/api/quant/backtests"): (201, BACKTEST)})
    async with Client(server) as client:
        result = await client.call_tool(
            "run_backtest", {"symbol": "005930", "strategy": "trend", "fee_bps": 2, "start": "2024-01-01"}
        )
    sent = session.calls[0]["json"]
    assert sent == {
        "symbol": "005930",
        "strategy": "trend",
        "feeRate": 0.0002,
        "slippage": 0.0005,
        "start": "2024-01-01",
    }
    body = result.structured_content
    assert body["receiptId"] == RECEIPT and "equity" not in body and "trades" not in body
    assert len(json.dumps(body)) < 1000


@pytest.mark.anyio
async def test_unknown_strategy_is_rejected_by_the_tool_schema():
    server, session = _server({})
    async with Client(server) as client:
        result = await client.call_tool("run_backtest", {"symbol": "005930", "strategy": "martingale"})
    assert result.is_error and session.calls == []


@pytest.mark.anyio
async def test_get_backtest_validates_the_receipt_id_before_calling():
    server, session = _server({("GET", f"/api/quant/backtests/{RECEIPT}"): (200, {"receiptId": RECEIPT})})
    async with Client(server) as client:
        bad = await client.call_tool("get_backtest", {"receipt_id": "../../orders"})
        good = await client.call_tool("get_backtest", {"receipt_id": RECEIPT})
    assert bad.is_error and not good.is_error
    assert [call["path"] for call in session.calls] == [f"/api/quant/backtests/{RECEIPT}"]


@pytest.mark.anyio
async def test_order_quantity_bounds_are_checked_before_calling():
    server, session = _server({("POST", "/openapi/v1/orders"): (200, {"ok": True})}, allow_orders=True)
    async with Client(server) as client:
        too_many = await client.call_tool("place_paper_order", {"symbol": "005930", "side": "BUY", "quantity": 0})
        ok = await client.call_tool("place_paper_order", {"symbol": "005930", "side": "BUY", "quantity": 3})
    assert too_many.is_error and not ok.is_error
    assert session.calls[0]["json"] == {"symbol": "005930", "side": "BUY", "quantity": 3}


@pytest.mark.anyio
async def test_unreachable_desk_is_a_tool_error():
    import requests

    class Down:
        def request(self, *args, **kwargs):
            raise requests.ConnectionError("refused")

    server = build_server(DeskAPI("http://desk.test", "k", session=Down()))
    async with Client(server) as client:
        result = await client.call_tool("get_account", {})
    assert result.is_error and "unreachable" in result.content[0].text
