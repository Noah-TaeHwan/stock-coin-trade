"""Invite codes, limits, budget and receipts of /api/agent on MariaDB + PostgreSQL.

The Claude API is replaced by a scripted transport under the real SDK
(tests/agent_script.py), so no request leaves the machine and nothing is billed.
"""

import uuid
from datetime import timedelta

import anthropic
import httpx2
import pytest
from agent_script import Script, _client, answer, call_backtest
from sqlalchemy import text

import bootstrap
import db
import quant
import research_agent
from app import create_app
from settings import Settings

pytestmark = pytest.mark.integration

PEPPER = "integration-pepper-" + "x" * 20
GOOD = "005930 전략의 총수익률은 {{n1}}, Sharpe는 {{n2}}, 같은 기간 보유는 {{n3}}입니다."


@pytest.fixture(scope="module", autouse=True)
def tables():
    bootstrap.create_tables()


def _app(enabled=True, budget=50.0):
    settings = Settings(
        profile="local",
        secret_key="a" * 40,
        session_cookie_secure=False,
        ai_enabled=enabled,
        ai_monthly_budget_usd=budget,
        ai_invite_pepper=PEPPER,
    )
    application = create_app(settings)
    application.config.update(TESTING=True)
    return application


def _member(client):
    email = f"agent-{uuid.uuid4().hex[:10]}@example.com"
    client.post(
        "/api/member/register",
        json={
            "username": "agent",
            "email": email,
            "password": "pw-long-passphrase-for-tests",
            "password2": "pw-long-passphrase-for-tests",
        },
    )
    client.post("/api/member/login", json={"email": email, "password": "pw-long-passphrase-for-tests"})
    return email


@pytest.fixture
def scripted(monkeypatch):
    def install(*steps):
        script = Script(*steps)
        monkeypatch.setattr(research_agent, "_anthropic_client", lambda: _client(script))
        return script

    return install


def _invite(**limits):
    return research_agent.create_invite(
        "test", limits.get("days", 7), limits.get("requests", 5), limits.get("tokens", 1_000_000), PEPPER
    )


def _invite_row(code):
    with db.engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT * FROM ai_invite WHERE code_hash = :h"), {"h": research_agent.code_hash(code, PEPPER)}
            )
            .mappings()
            .one()
        )


def test_disabled_by_default():
    client = _app(enabled=False).test_client()
    _member(client)
    assert client.post("/api/agent/ask", json={"question": "q"}).status_code == 503
    assert client.get("/api/agent/status").get_json()["enabled"] is False


def test_login_and_invite_are_required():
    client = _app().test_client()
    assert client.post("/api/agent/ask", json={"question": "q"}).status_code == 401
    _member(client)
    response = client.post("/api/agent/ask", json={"question": "q"})
    assert response.status_code == 403 and response.get_json()["error"] == "INVITE_REQUIRED"


def test_invite_codes_are_stored_hashed_and_bind_to_one_member():
    code = _invite()
    row = _invite_row(code)
    assert code.startswith("inv_") and code not in str(dict(row)) and row["member_id"] is None
    first, second = _app().test_client(), _app().test_client()
    _member(first)
    _member(second)
    assert first.post("/api/agent/redeem", json={"code": "inv_wrong"}).status_code == 400
    assert first.post("/api/agent/redeem", json={"code": code}).status_code == 200
    assert second.post("/api/agent/redeem", json={"code": code}).status_code == 400
    assert first.get("/api/agent/status").get_json()["invite"]["requestsLeft"] == 5


def test_a_question_runs_the_agent_on_real_backtests_and_records_cost(scripted):
    script = scripted(call_backtest, answer(GOOD))
    client = _app().test_client()
    _member(client)
    code = _invite()
    client.post("/api/agent/redeem", json={"code": code})
    response = client.post("/api/agent/ask", json={"question": "005930 MA 전략 성과를 알려줘"})
    body = response.get_json()
    assert response.status_code == 200 and body["status"] == "answered", body
    receipt = body["answer"]["receipts"][0]
    stored = quant.stored_backtest(receipt)  # the same receipt the quant API serves
    assert {n["path"]: n["value"] for n in body["answer"]["numbers"]}["metrics.sharpe"] == pytest.approx(
        stored["metrics"]["sharpe"]
    )
    assert script.requests[0]["model"] == "claude-opus-5-5"
    row = _invite_row(code)
    assert (
        row["used_requests"] == 1
        and row["used_tokens"] == body["usage"]["input_tokens"] + body["usage"]["output_tokens"]
    )
    with db.engine.connect() as conn:
        usage = (
            conn.execute(text("SELECT * FROM ai_usage WHERE invite_id = :i"), {"i": row["invite_id"]}).mappings().one()
        )
    assert usage["status"] == "answered" and float(usage["cost_usd"]) == pytest.approx(body["costUsd"], abs=1e-6)
    assert receipt in usage["receipts"]


def test_request_limit_is_enforced(scripted):
    scripted(answer("범위 밖 질문입니다.", cited="x", out_of_scope=True))
    client = _app().test_client()
    _member(client)
    code = _invite(requests=1)
    client.post("/api/agent/redeem", json={"code": code})
    assert client.post("/api/agent/ask", json={"question": "내일 오를까?"}).status_code == 200
    response = client.post("/api/agent/ask", json={"question": "또 물어볼게"})
    assert response.status_code == 403 and "횟수" in response.get_json()["message"]


def test_expired_invite_is_refused():
    client = _app().test_client()
    _member(client)
    code = _invite()
    client.post("/api/agent/redeem", json={"code": code})
    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE ai_invite SET expires_at = :t WHERE code_hash = :h"),
            {"t": research_agent._now() - timedelta(minutes=1), "h": research_agent.code_hash(code, PEPPER)},
        )
    response = client.post("/api/agent/ask", json={"question": "q"})
    assert response.status_code == 403 and "만료" in response.get_json()["message"]


def test_monthly_budget_stops_new_questions(scripted):
    scripted(answer("범위 밖입니다.", cited="x", out_of_scope=True))
    with db.engine.connect() as conn:
        spent = research_agent.month_spend(conn, research_agent._now())
    client = _app(budget=spent + 1e-9).test_client()  # any recorded cost pushes it over
    _member(client)
    code = _invite()
    client.post("/api/agent/redeem", json={"code": code})
    assert client.post("/api/agent/ask", json={"question": "첫 질문"}).status_code == 200
    response = client.post("/api/agent/ask", json={"question": "두 번째"})
    assert response.status_code == 503 and response.get_json()["error"] == "BUDGET_EXHAUSTED"


def test_upstream_rate_limit_is_a_503_and_the_request_stays_counted(monkeypatch):
    def overloaded(request):
        return httpx2.Response(429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}})

    monkeypatch.setattr(
        research_agent,
        "_anthropic_client",
        lambda: anthropic.Anthropic(
            api_key="t",
            max_retries=0,
            http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(overloaded)),
        ),
    )
    client = _app().test_client()
    _member(client)
    code = _invite()
    client.post("/api/agent/redeem", json={"code": code})
    response = client.post("/api/agent/ask", json={"question": "q"})
    assert response.status_code == 503 and response.get_json()["error"] == "AI_BUSY"
    assert _invite_row(code)["used_requests"] == 1


def test_create_invite_cli_prints_the_code_once():
    application = _app()
    result = application.test_cli_runner().invoke(args=["create-invite", "--label", "cli", "--max-requests", "3"])
    code = result.output.strip()
    assert result.exit_code == 0 and code.startswith("inv_")
    assert _invite_row(code)["max_requests"] == 3
