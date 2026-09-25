"""Public profile surface: which routes exist, CORS, knowledge-base writes, crawler redirects."""

from pathlib import Path
from unittest import mock

import pytest
import requests

import ai_sheet
import app as app_module
from app import create_app
from settings import Settings

PUBLIC_SNAPSHOT = Path(__file__).with_name("snapshots") / "routes_public.txt"
PUBLIC = Settings(
    profile="public",
    secret_key="p" * 40,
    session_cookie_secure=True,
    admin_email="owner@example.com",
    ratelimit_enabled=True,
)


@pytest.fixture
def public_app():
    application = create_app(PUBLIC)
    application.config.update(TESTING=True)
    return application


def _route_lines(flask_app):
    return sorted(
        f"{' '.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))} {rule.rule} {rule.endpoint}"
        for rule in flask_app.url_map.iter_rules()
    )


def test_public_route_table_matches_snapshot(public_app):
    assert _route_lines(public_app) == PUBLIC_SNAPSHOT.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "path",
    [
        "/api/broker-test/kis/quote?symbol=005930",
        "/api/kis-real/status",
        "/api/alpaca-test/status",
        "/api/ai-sheet/sectors",
        "/api/ohlcv-db/summary",
        "/api/alternatives/markets",
    ],
)
def test_local_only_labs_are_not_served_in_public(public_app, path):
    assert public_app.test_client().get(path).status_code == 404


def test_core_product_routes_remain_in_public(public_app):
    rules = {rule.rule for rule in public_app.url_map.iter_rules()}
    for rule in ("/api/member/login", "/api/stocks/orders/buy", "/openapi/v1/orders", "/api/quant/backtests"):
        assert rule in rules


# ── CORS ─────────────────────────────────────────────────────────────────────


def _cors(client, path, origin):
    response = client.get(path, headers={"Origin": origin})
    return response.headers.get("Access-Control-Allow-Origin"), response.headers.get("Access-Control-Allow-Credentials")


def test_local_dev_origin_gets_credentialed_cors(client):
    assert _cors(client, "/api/member/me", "http://localhost:3344") == ("http://localhost:3344", "true")


@pytest.mark.parametrize("origin", ["http://localhost.evil.example", "http://127x0x0x1:3000", "https://evil.example"])
def test_lookalike_origins_are_not_allowed(client, origin):
    assert _cors(client, "/api/member/me", origin) == (None, None)


def test_public_api_is_same_origin_only(public_app):
    assert _cors(public_app.test_client(), "/api/member/me", "http://localhost:3344") == (None, None)


def test_openapi_cors_never_allows_credentials(client):
    allow_origin, allow_credentials = _cors(client, "/openapi/v1/stocks", "https://tool.example")
    assert allow_origin is not None
    assert allow_credentials is None


# ── Knowledge base writes ────────────────────────────────────────────────────


def test_only_the_admin_adds_knowledge_base_documents(client):
    with mock.patch.object(app_module, "is_admin_member", return_value=False):
        response = client.post("/api/stocks/ai/qdrant/add", json={"text": "<img src=x onerror=alert(1)>"})
    assert response.status_code == 403


def test_admin_can_add_knowledge_base_documents(client):
    fake_qdrant = mock.Mock(add_doc=mock.Mock(return_value="doc-1"))
    with (
        mock.patch.object(app_module, "is_admin_member", return_value=True),
        mock.patch.dict("sys.modules", {"qdrant_service": fake_qdrant}),
    ):
        response = client.post("/api/stocks/ai/qdrant/add", json={"text": "memo", "title": "t" * 500})
    assert response.status_code == 200
    _text, title, _category = fake_qdrant.add_doc.call_args.args
    assert len(title) == 200


def test_search_limit_must_be_a_number(client):
    response = client.post("/api/stocks/ai/qdrant/search", json={"query": "x", "limit": "many"})
    assert response.status_code == 400


# ── Crawler redirects ────────────────────────────────────────────────────────


def _redirect(location):
    response = mock.MagicMock(is_redirect=True, headers={"Location": location})
    return response


def test_crawler_checks_every_redirect_hop_before_requesting_it():
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        assert kwargs["allow_redirects"] is False
        return _redirect("http://169.254.169.254/latest/meta-data/")

    def is_public(url):
        return "169.254" not in url

    with (
        mock.patch.object(ai_sheet, "_is_public_url", side_effect=is_public),
        mock.patch.object(ai_sheet.requests, "get", side_effect=fake_get),
        pytest.raises(ai_sheet.UnsafeRedirectError),
    ):
        ai_sheet._get_public_page("https://example.com/start")
    # The internal address was never contacted.
    assert requested == ["https://example.com/start"]


def test_crawler_follows_public_redirects_and_resolves_relative_locations():
    page = mock.MagicMock(is_redirect=False)
    responses = [_redirect("/next"), page]
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        return responses.pop(0)

    with (
        mock.patch.object(ai_sheet, "_is_public_url", return_value=True),
        mock.patch.object(ai_sheet.requests, "get", side_effect=fake_get),
    ):
        assert ai_sheet._get_public_page("https://example.com/start") is page
    assert requested == ["https://example.com/start", "https://example.com/next"]


def test_crawler_stops_redirect_loops():
    with (
        mock.patch.object(ai_sheet, "_is_public_url", return_value=True),
        mock.patch.object(ai_sheet.requests, "get", side_effect=lambda url, **kw: _redirect(url)),
        pytest.raises(requests.TooManyRedirects),
    ):
        ai_sheet._get_public_page("https://example.com/loop")


def test_crawl_route_reports_an_unsafe_redirect(client):
    with (
        mock.patch.object(ai_sheet, "_get_public_page", side_effect=ai_sheet.UnsafeRedirectError("x")),
        mock.patch.object(ai_sheet, "_is_public_url", return_value=True),
    ):
        response = client.post("/api/ai-sheet/crawl", json={"url": "https://example.com"})
    assert response.status_code == 400
