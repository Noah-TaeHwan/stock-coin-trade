"""The MCP server against the real app (public profile), MariaDB and PostgreSQL.

The desk's HTTP calls are routed into a Flask test client instead of a socket,
so everything behind the URL (API key lookup, per-key limit, paper account,
data source registry, quantlab and its receipts table) is the real code.
"""

import uuid

import pytest
from mcp import Client
from sqlalchemy import text

import bootstrap
import db
from app import create_app
from deskmcp.client import DeskAPI
from deskmcp.server import build_server
from settings import Settings

pytestmark = pytest.mark.integration


class FlaskSession:
    def __init__(self, client):
        self.client = client

    def request(self, method, url, headers=None, timeout=None, params=None, json=None):
        response = self.client.open(
            url.removeprefix("http://desk.test"), method=method, headers=headers, query_string=params, json=json
        )
        return _Response(response.status_code, response.get_json(silent=True))


class _Response:
    """The two attributes DeskAPI reads from a requests.Response."""

    def __init__(self, status_code, body):
        self.status_code, self._body = status_code, body

    def json(self):
        if self._body is None:
            raise ValueError("no json body")
        return self._body


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def desk():
    bootstrap.create_tables()
    settings = Settings(
        profile="public",
        secret_key="m" * 40,
        session_cookie_secure=False,
        admin_email="owner@example.com",
        ratelimit_enabled=True,
    )
    application = create_app(settings)
    application.config.update(TESTING=True)
    browser = application.test_client()
    email = f"mcp-{uuid.uuid4().hex[:10]}@example.com"
    registered = browser.post(
        "/api/member/register",
        json={
            "username": "mcp",
            "email": email,
            "password": "pw-long-passphrase-for-tests",
            "password2": "pw-long-passphrase-for-tests",
        },
    )
    assert registered.status_code in (200, 201), registered.get_data(as_text=True)
    browser.post("/api/member/login", json={"email": email, "password": "pw-long-passphrase-for-tests"})
    created = browser.post("/api/member/api-keys", json={"label": "mcp test"})
    assert created.status_code in (200, 201), created.get_data(as_text=True)
    api = DeskAPI("http://desk.test", created.get_json()["apiKey"], session=FlaskSession(application.test_client()))
    yield api
    with db.engine.begin() as conn:
        member_id = conn.execute(text("SELECT member_id FROM member WHERE email = :e"), {"e": email}).scalar()
        for table in ("stock_order", "stock_position", "api_key", "system_error_log", "member_session", "member"):
            conn.execute(text(f"DELETE FROM {table} WHERE member_id = :id"), {"id": member_id})


@pytest.mark.anyio
async def test_research_flow_run_then_resolve_the_receipt(desk):
    async with Client(build_server(desk)) as client:
        sources = (await client.call_tool("list_sources", {})).structured_content
        run = await client.call_tool("run_backtest", {"symbol": "005930", "strategy": "rsi", "start": "2025-01-01"})
        again = await client.call_tool("run_backtest", {"symbol": "005930", "strategy": "rsi", "start": "2025-01-01"})
        stored = await client.call_tool("get_backtest", {"receipt_id": run.structured_content["receiptId"]})
    assert sources["profile"] == "public"
    assert [s["id"] for s in sources["sources"] if s["enabled"]] == ["synthetic", "synthetic_sql"]
    assert not run.is_error, run.content
    assert again.structured_content["reused"] is True
    assert again.structured_content["receiptId"] == run.structured_content["receiptId"]
    assert stored.structured_content["metrics"] == run.structured_content["metrics"]
    assert stored.structured_content["receipt"]["inputSha256"] == run.structured_content["receipt"]["inputSha256"]


@pytest.mark.anyio
async def test_account_flow_uses_the_key_owners_paper_account(desk):
    async with Client(build_server(desk, allow_orders=True)) as client:
        quote = (await client.call_tool("get_quote", {"symbol": "005930"})).structured_content
        order = await client.call_tool("place_paper_order", {"symbol": "005930", "side": "BUY", "quantity": 1})
        positions = (await client.call_tool("get_positions", {})).structured_content
        orders = (await client.call_tool("list_orders", {"limit": 5})).structured_content
        account = await client.call_tool("get_account", {})
    assert quote["source"] == "synthetic"
    assert not order.is_error, order.content
    assert [p["symbol"] for p in positions["positions"]] == ["005930"]
    assert len(orders["orders"]) == 1
    assert not account.is_error


@pytest.mark.anyio
async def test_a_revoked_or_wrong_key_is_a_tool_error(desk):
    wrong = DeskAPI(desk.base_url, "sk-not-a-key", session=desk.session)
    async with Client(build_server(wrong)) as client:
        result = await client.call_tool("get_account", {})
    assert result.is_error and "401" in result.content[0].text
