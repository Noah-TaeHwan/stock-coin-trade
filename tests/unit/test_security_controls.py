"""Cross-site request checks, rate limits, account rules and client-safe errors."""

from contextlib import contextmanager
from unittest import mock

import pytest

import accounts
import app as app_module
import members
from app import create_app
from settings import Settings

PUBLIC = Settings(
    profile="public",
    secret_key="p" * 40,
    session_cookie_secure=True,
    admin_email="owner@example.com",
    ratelimit_enabled=True,
)


def _client(settings):
    application = create_app(settings)
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.fixture
def public_client():
    return _client(PUBLIC)


# ── Cross-site requests ──────────────────────────────────────────────────────
# /api/member/logout is a state-changing POST that needs no database.


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 200),  # not a browser request
        ({"Sec-Fetch-Site": "same-origin"}, 200),
        ({"Sec-Fetch-Site": "none"}, 200),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
        ({"Origin": "http://localhost"}, 200),  # same host as the test request
        ({"Origin": "https://evil.example"}, 403),
        ({"Origin": "null"}, 403),
    ],
)
def test_cross_site_posts_are_rejected(client, headers, status):
    assert client.post("/api/member/logout", headers=headers).status_code == status


def test_rejection_body_names_the_reason(client):
    response = client.post("/api/member/logout", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.get_json()["error"] == "CSRF_REJECTED"


def test_safe_methods_are_not_checked(client):
    assert client.get("/health", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_local_allows_a_dev_frontend_on_another_localhost_port(client):
    assert client.post("/api/member/logout", headers={"Sec-Fetch-Site": "same-site"}).status_code == 200
    assert client.post("/api/member/logout", headers={"Origin": "http://localhost:3344"}).status_code == 200


def test_public_accepts_only_same_origin(public_client):
    assert public_client.post("/api/member/logout", headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    assert public_client.post("/api/member/logout", headers={"Origin": "http://localhost:3344"}).status_code == 403


def test_bearer_token_api_is_exempt(client):
    # /openapi/* authenticates with an API key, not the cookie; 401 means the
    # request reached the key check instead of being stopped as cross-site.
    response = client.post("/openapi/v1/orders", headers={"Sec-Fetch-Site": "cross-site"}, json={})
    assert response.status_code == 401


# ── Rate limits ──────────────────────────────────────────────────────────────


@contextmanager
def _no_member_scope():
    session = mock.Mock()
    session.query.return_value.filter.return_value.first.return_value = None
    yield session


def test_login_is_rate_limited_per_client_in_public(public_client):
    with mock.patch.object(members, "session_scope", _no_member_scope):
        codes = [
            public_client.post("/api/member/login", json={"email": "a@example.com", "password": "x"}).status_code
            for _ in range(11)
        ]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_rate_limited_response_is_json_and_not_written_to_the_error_log(public_client):
    with (
        mock.patch.object(members, "session_scope", _no_member_scope),
        mock.patch.object(app_module, "record_error") as record,
    ):
        for _ in range(10):
            public_client.post("/api/member/login", json={"email": "a@example.com", "password": "x"})
        record.reset_mock()
        response = public_client.post("/api/member/login", json={"email": "a@example.com", "password": "x"})
    assert response.status_code == 429
    assert response.get_json()["error"] == "RATE_LIMITED"
    record.assert_not_called()


def test_local_profile_does_not_rate_limit_by_default(client):
    with mock.patch.object(members, "session_scope", _no_member_scope):
        codes = {
            client.post("/api/member/login", json={"email": "a@example.com", "password": "x"}).status_code
            for _ in range(12)
        }
    assert codes == {401}


def test_proxy_fix_uses_the_forwarded_client_address():
    settings = Settings(profile="local", secret_key="k" * 40, session_cookie_secure=False, trusted_proxy_count=1)
    application = create_app(settings)

    # ProxyFix wraps the WSGI app, so check through a real request.
    @application.get("/_ip")
    def _ip():
        from flask import request

        return request.remote_addr

    response = application.test_client().get(
        "/_ip", headers={"X-Forwarded-For": "203.0.113.7"}, environ_base={"REMOTE_ADDR": "172.18.0.5"}
    )
    assert response.get_data(as_text=True) == "203.0.113.7"


# ── Accounts ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("email", "profile", "allowed"),
    [
        ("system01@system-bot.local", "local", False),
        ("SYSTEM01@System-Bot.Local", "public", False),
        ("sample-investor-01@sample-investor.local", "local", True),
        ("sample-investor-01@sample-investor.local", "public", False),
        ("someone@example.com", "public", True),
    ],
)
def test_who_can_sign_in(email, profile, allowed):
    assert accounts.can_sign_in(email, profile) is allowed


def test_unusable_password_matches_nothing():
    assert members._check_password("", accounts.UNUSABLE_PASSWORD) is False
    assert members._check_password("!unusable", accounts.UNUSABLE_PASSWORD) is False
    assert members._check_password("anything", None) is False


@pytest.mark.parametrize("email", ["x@sample-investor.local", "x@SYSTEM-BOT.local"])
def test_reserved_domains_cannot_register(client, email):
    body = {"username": "x", "email": email, "password": "pw", "password2": "pw"}
    response = client.post("/api/member/register", json=body)
    assert response.status_code == 400
    assert response.get_json()["field"] == "email"


def test_public_admin_address_cannot_register(public_client):
    body = {"username": "x", "email": "Owner@Example.com", "password": "pw", "password2": "pw"}
    response = public_client.post("/api/member/register", json=body)
    assert response.status_code == 400
    assert response.get_json()["error"] == "사용할 수 없는 이메일입니다."


def test_create_admin_command_reports_validation_errors(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["create-admin", "--email", "owner@example.com", "--password", "short"])
    assert result.exit_code != 0
    assert "at least 12 characters" in result.output


def test_create_admin_command_calls_bootstrap(app):
    runner = app.test_cli_runner()
    with mock.patch.object(app_module.bootstrap, "create_admin", return_value="created") as create:
        result = runner.invoke(args=["create-admin", "--email", "Owner@Example.com", "--password", "p" * 12])
    assert result.exit_code == 0, result.output
    create.assert_called_once_with("Owner@Example.com", "p" * 12)
    assert "created owner@example.com" in result.output


# ── Client-safe errors ───────────────────────────────────────────────────────


def test_exception_text_stays_in_the_log(client, caplog):
    secret_detail = "db-internal.example:3306 password=hunter2"
    with mock.patch.object(app_module, "list_krx_stocks", side_effect=RuntimeError(secret_detail)):
        response = client.get("/api/stocks/list")
    body = response.get_data(as_text=True)
    assert response.status_code == 503
    assert secret_detail not in body
    request_id = response.get_json()["requestId"]
    assert response.headers["X-Request-ID"] == request_id
    assert any(request_id in record.getMessage() for record in caplog.records)


def test_ai_analyze_requires_login(client):
    assert client.post("/api/ai/analyze", json={"context": "x"}).status_code == 401


def test_openapi_key_limit_uses_the_shared_limiter_when_rate_limiting_is_on(public_client):
    import openapi

    with (
        public_client.application.test_request_context(),
        mock.patch.object(openapi, "_rate_buckets", {}) as local_buckets,
    ):
        results = [openapi._check_rate_limit(4242) for _ in range(openapi.RATE_LIMIT_MAX + 1)]
        other_key = openapi._check_rate_limit(4243)
    assert results[:-1] == [True] * openapi.RATE_LIMIT_MAX and results[-1] is False
    assert other_key is True
    assert local_buckets == {}  # counted in the limiter's storage, not the process-local window


def test_openapi_key_limit_falls_back_to_a_local_window_when_rate_limiting_is_off(client):
    import openapi

    with client.application.test_request_context(), mock.patch.object(openapi, "_rate_buckets", {}) as local:
        results = [openapi._check_rate_limit(7) for _ in range(openapi.RATE_LIMIT_MAX + 1)]
    assert results[-1] is False and len(local[7]) == openapi.RATE_LIMIT_MAX
