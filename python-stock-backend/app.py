"""Flask application factory for the stock/coin paper-trading backend.

Run the web server with `gunicorn 'app:create_app()'`. Importing this module
has no side effects on the database or the scheduler: tables and seed data
come from `flask --app app init-db` / `seed-demo` (bootstrap.py), and the
recurring jobs run in their own process (worker.py).
"""

from settings import load_env_file

# Docker 없이 `python app.py`로 직접 실행할 때 저장소 루트의 .env를 읽는다.
# 이미 설정된 환경변수(Compose environment 등)가 우선하며, 파일이 없으면 무시된다.
# 다른 모듈이 import 시점에 os.environ을 읽으므로 반드시 그 import보다 먼저 실행한다.
load_env_file()

import threading  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402

import click  # noqa: E402
import requests as _req  # noqa: E402
from flask import Blueprint, Flask, g, got_request_exception, jsonify, request, session  # noqa: E402
from flask_cors import CORS  # noqa: E402
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

import bootstrap  # noqa: E402
from authz import is_admin_member  # noqa: E402
from admin import admin_bp  # noqa: E402
from ai import ai_bp  # noqa: E402
from ai_sheet import ai_sheet_bp  # noqa: E402
from alpaca_test_api import alpaca_test_bp  # noqa: E402
from alpaca_test_aws_api import aws_alpaca_test_bp  # noqa: E402
from alternatives import alternative_bp  # noqa: E402
from api_keys import api_key_bp  # noqa: E402
from api_usage import api_usage_bp, record_api_usage  # noqa: E402
from arbitrage import arb_bp  # noqa: E402
from broker_test_api import broker_test_bp  # noqa: E402
from broker_test_aws_api import aws_broker_test_bp  # noqa: E402
from crypto import market_bp, trade_bp  # noqa: E402
from crypto_exchange_test_api import crypto_exchange_test_bp  # noqa: E402
from error_analysis import error_analysis_bp, record_error  # noqa: E402
from errors import error_response, request_id  # noqa: E402
from extensions import limiter  # noqa: E402
from kis_api_explorer import kis_explorer_bp  # noqa: E402
from kis_chart_api import kis_chart_bp  # noqa: E402
from kis_practice import kis_practice_bp  # noqa: E402
from kis_real import kis_real_bp  # noqa: E402
from members import member_bp  # noqa: E402
from ohlcv_db import ohlcv_db_bp  # noqa: E402
from intent import intent_bp  # noqa: E402
from openapi import open_api_bp  # noqa: E402
import price_sources  # noqa: E402
from marketdata import registry as data_registry  # noqa: E402
from quant import quant_bp  # noqa: E402
from research_agent import create_invite_command, research_agent_bp  # noqa: E402
from security import cross_site_request_rejected  # noqa: E402
from settings import Settings  # noqa: E402
from stock_market import (  # noqa: E402
    BASE_PRICES, get_chart_with_source, get_dashboard_stock_quotes, get_index_cached, get_market_cap_rankings,
    get_quote_cached, get_stock_info, list_krx_stocks, search_krx_stocks,
)
from stocks import stock_bp  # noqa: E402

# Routes that used to be declared directly on the module-level app.
core_bp = Blueprint("core", __name__)

# Registration order matches the original module-level app.
BLUEPRINTS = (
    member_bp, market_bp, trade_bp, crypto_exchange_test_bp, admin_bp, ai_bp, ai_sheet_bp,
    alpaca_test_bp, aws_alpaca_test_bp, stock_bp, api_key_bp, broker_test_bp, kis_explorer_bp,
    kis_chart_bp, kis_practice_bp, kis_real_bp, aws_broker_test_bp, open_api_bp, ohlcv_db_bp,
    quant_bp, alternative_bp, error_analysis_bp, api_usage_bp, arb_bp, research_agent_bp, intent_bp,
)

# Classroom labs that need broker or cloud credentials, the host Docker socket,
# or an external database. The public profile does not register them.
LOCAL_ONLY_BLUEPRINTS = frozenset({
    crypto_exchange_test_bp, alpaca_test_bp, aws_alpaca_test_bp, broker_test_bp, kis_explorer_bp,
    kis_chart_bp, kis_practice_bp, kis_real_bp, aws_broker_test_bp,  # broker labs (KIS, KB, Alpaca, AWS SSM, exchanges)
    ai_sheet_bp,  # page crawler and LEAN backtest through the host Docker socket
    ohlcv_db_bp,  # external OHLCV database with a hardcoded default DSN
    alternative_bp,  # futures/options P&L model not yet reviewed
    ai_bp,  # market summary on the server's API key with no invite or budget; public uses research_agent_bp
})

# Features that exist only to show a given data source's prices. They are
# registered only when config/data_sources.toml allows every source they need
# in the running profile, so enabling a verified source there brings them back.
SOURCE_DEPENDENT_BLUEPRINTS = {
    market_bp: ("upbit",),  # crypto market list and quotes
    trade_bp: ("upbit",),  # crypto paper trading priced from Upbit
    arb_bp: ("upbit", "exchange_quotes"),  # cross-exchange arbitrage view
}

# Exact origins, not prefixes: flask-cors treats these strings as regular
# expressions matched from the start, so "http://localhost:*" also matched
# "http://localhost.evil.example".
LOCAL_DEV_ORIGINS = [r"^http://localhost(:\d+)?$", r"^http://127\.0\.0\.1(:\d+)?$"]

_API_USAGE_PREFIXES = (
    "/api/broker-test/", "/api/kis-chart/", "/api/kis-explorer/", "/api/kis-real/", "/api/aws-broker-test/",
    "/api/alpaca-test/", "/api/aws-alpaca-test/", "/api/crypto-exchange-test/",
)


def create_app(settings: Settings | None = None) -> Flask:
    """Build the Flask app. Pure: no database access, no background threads."""
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    app.config.update(settings.flask_config())
    if settings.trusted_proxy_count:
        # request.remote_addr(레이트 리밋 키)를 nginx 뒤의 실제 클라이언트 IP로 복원한다.
        # 프록시 수와 정확히 같아야 한다(더 크면 클라이언트가 IP를 위조할 수 있다).
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=settings.trusted_proxy_count)
    limiter.init_app(app)

    CORS(
        app,
        resources={
            # The public site serves the frontend and the API from one origin.
            r"/api/*": {"origins": [] if settings.is_public else LOCAL_DEV_ORIGINS, "supports_credentials": True},
            # API-key clients from anywhere; no cookies, so no credentials.
            r"/openapi/*": {"origins": "*", "supports_credentials": False},
        },
    )

    sources = data_registry.load()
    for blueprint in BLUEPRINTS:
        if settings.is_public and blueprint in LOCAL_ONLY_BLUEPRINTS:
            continue
        needed = SOURCE_DEPENDENT_BLUEPRINTS.get(blueprint, ())
        if not all(sources.get(source_id).allowed_in(settings.profile) for source_id in needed):
            continue
        app.register_blueprint(blueprint)
    app.register_blueprint(core_bp)

    got_request_exception.connect(_capture_unhandled_exception, app, weak=False)
    app.before_request(_reject_cross_site_requests)
    app.before_request(_start_api_usage_timer)
    app.after_request(_record_failed_response)
    app.after_request(_add_request_id_header)
    app.register_error_handler(429, _rate_limited)

    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_demo_command)
    app.cli.add_command(create_admin_command)
    app.cli.add_command(init_quant_db_command)
    app.cli.add_command(create_invite_command)
    return app


@click.command("init-db")
def init_db_command() -> None:
    """Create the MariaDB tables (idempotent)."""
    bootstrap.create_tables()
    click.echo("init-db: tables are ready")


@click.command("init-quant-db")
def init_quant_db_command() -> None:
    """Upgrade the quant PostgreSQL schema (source column, receipts table; idempotent)."""
    from marketdata import store

    store.ensure_schema(store.engine_from_env())
    click.echo("init-quant-db: schema is up to date")


@click.command("seed-demo")
def seed_demo_command() -> None:
    """Add sample investors, their datasets and market-bot accounts (idempotent)."""
    bootstrap.seed_demo_data()
    click.echo("seed-demo: done")


@click.command("create-admin")
@click.option("--email", envvar="ADMIN_EMAIL", required=True, help="Defaults to the ADMIN_EMAIL setting.")
@click.password_option(help="At least 12 characters. Prompted when omitted.")
def create_admin_command(email: str, password: str) -> None:
    """Create the admin account (or reset its password). Registration refuses this address in public."""
    try:
        outcome = bootstrap.create_admin(email, password)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"create-admin: {outcome} {email.strip().lower()}")


def _reject_cross_site_requests():
    from flask import current_app

    if cross_site_request_rejected(current_app.config["APP_PROFILE"]):
        return jsonify({"error": "CSRF_REJECTED", "message": "다른 사이트에서 보낸 요청은 처리하지 않습니다."}), 403
    return None


def _rate_limited(error):
    return jsonify({
        "error": "RATE_LIMITED",
        "message": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
        "limit": str(getattr(error, "description", "")),
    }), 429


def _add_request_id_header(response):
    response.headers["X-Request-ID"] = request_id()
    return response


def _capture_unhandled_exception(sender, exception, **extra):
    """Keep the exception until after_request persists its diagnostic details."""
    g.unhandled_error = exception


def _start_api_usage_timer():
    if request.path.startswith(_API_USAGE_PREFIXES):
        g.api_usage_started_at = time.perf_counter()


def _record_failed_response(response):
    """Capture handled API failures too, not only Flask exceptions."""
    if getattr(g, "api_usage_started_at", None) is not None:
        record_api_usage(response, g.api_usage_started_at)
    # 429는 기록하지 않는다. 제한에 걸린 요청마다 행을 쓰면 제한이 DB 쓰기를 막지 못한다.
    if (response.status_code >= 400 and response.status_code != 429
            and not request.path.startswith("/api/error-analysis/")):
        try:
            body = response.get_json(silent=True) or {}
            exc = getattr(g, "unhandled_error", None)
            message = body.get("message") or body.get("error") or str(exc) or response.status
            record_error(
                source="SERVER", severity="CRITICAL" if response.status_code >= 500 else "WARNING",
                status=response.status_code, method=request.method, path=request.full_path.rstrip("?"),
                error_type=type(exc).__name__ if exc else "HTTPError",
                message=message, stack_trace="".join(traceback.format_exception(exc)) if exc else None,
                request_meta={"endpoint": request.endpoint, "remoteAddr": request.remote_addr,
                              "requestId": request_id()},
                member_id=session.get("member_id"),
            )
        except Exception:
            pass
    return response


def _stock_list_label() -> dict:
    if price_sources.allowed("krx_kind"):
        return price_sources.label("krx_kind")
    return {"source": "builtin", "attribution": "내장 실습 종목 목록"}


# ── Health ──────────────────────────────────────────────────────────────────
@core_bp.get("/health")
def health():
    return jsonify({"status": "ok"})


# ── Stock list ───────────────────────────────────────────────────────────────
@core_bp.get("/api/stocks/list")
def stock_list():
    try:
        limit = max(1, min(int(request.args.get("limit", 30)), 100))
        market = request.args.get("market", "")
        return jsonify({"stocks": list_krx_stocks(limit, market), **_stock_list_label()})
    except Exception as exc:
        return error_response("KRX 종목 목록을 가져오지 못했습니다.", exc, 503, key="message")


@core_bp.get("/api/stocks/search")
def stock_search():
    query = request.args.get("q", "")
    try:
        limit = max(1, min(int(request.args.get("limit", 20)), 50))
        return jsonify({"stocks": search_krx_stocks(query, limit), **_stock_list_label()})
    except Exception as exc:
        return error_response("KRX 종목 검색을 사용할 수 없습니다.", exc, 503, key="message")


# ── Market indices ───────────────────────────────────────────────────────────
@core_bp.get("/api/stocks/market")
def market():
    kospi  = get_index_cached("^KS11")
    kosdaq = get_index_cached("^KQ11")
    return jsonify({"KOSPI": kospi, "KOSDAQ": kosdaq})


# ── Quote ────────────────────────────────────────────────────────────────────
@core_bp.get("/api/stocks/quote")
def quote():
    symbol = request.args.get("symbol", "").upper()
    if not symbol:
        return jsonify({"message": "symbol is required"}), 400
    if not get_stock_info(symbol):
        return jsonify({"message": f"지원하지 않는 KRX 종목입니다: {symbol}"}), 404
    try:
        return jsonify(get_quote_cached(symbol))
    except RuntimeError as e:
        return jsonify({"message": str(e)}), 503
    except ValueError as e:
        return jsonify({"message": str(e)}), 404


# ── Chart ────────────────────────────────────────────────────────────────────
@core_bp.get("/api/stocks/chart")
def chart():
    symbol = request.args.get("symbol", "").upper()
    period = request.args.get("period", "1m")
    include_ma = request.args.get("include_ma") == "1"
    if not symbol:
        return jsonify({"message": "symbol is required"}), 400
    if not get_stock_info(symbol):
        return jsonify({"message": f"지원하지 않는 KRX 종목입니다: {symbol}"}), 404
    try:
        ohlcv, visible_from, source = get_chart_with_source(symbol, period, include_ma)
        return jsonify({"symbol": symbol, "period": period, "data": ohlcv, "visibleFrom": visible_from,
                        **price_sources.label(source)})
    except RuntimeError as e:
        return jsonify({"message": str(e)}), 503
    except ValueError as e:
        return jsonify({"message": str(e)}), 404


# ── Market Movers ─────────────────────────────────────────────────────────────
@core_bp.get("/api/stocks/movers")
def movers():
    quotes = []
    for q in get_dashboard_stock_quotes().values():
        quotes.append({
            "symbol": q["symbol"], "name": q["name"], "price": q["price"],
            "changeRate": q.get("changeRate", 0), "market": q["market"],
        })
    sorted_q = sorted(quotes, key=lambda x: x.get("changeRate", 0), reverse=True)
    gainers  = sorted_q[:3]
    losers   = sorted_q[-3:][::-1]
    return jsonify({"gainers": gainers, "losers": losers})


# ── Batch Prices (실시간 마켓 리스트용) ──────────────────────────────────────
@core_bp.get("/api/stocks/prices")
def batch_prices():
    result = {}
    requested = [symbol.strip().upper() for symbol in request.args.get("symbols", "").split(",") if symbol.strip()]
    if not requested:
        return jsonify({"prices": get_dashboard_stock_quotes(), "cachedForSeconds": 30})
    symbols = requested[:50]
    for symbol in symbols:
        info = get_stock_info(symbol)
        if not info:
            continue
        try:
            q = get_quote_cached(symbol)
            result[symbol] = {
                "name":       q["name"],
                "market":     q["market"],
                "price":      q["price"],
                "change":     q.get("change", 0),
                "changeRate": q.get("changeRate", 0),
                "volume":     q.get("volume", 0),
            }
        except Exception:
            result[symbol] = {
                "name":       info["name"],
                "market":     info["market"],
                "price":      BASE_PRICES.get(symbol, 0),
                "change":     0,
                "changeRate": 0,
                "volume":     0,
            }
    return jsonify({"prices": result})


@core_bp.get("/api/stocks/market-cap-rankings")
def market_cap_rankings():
    return jsonify({"rankings": get_market_cap_rankings(10)})


# ── Qdrant / RAG endpoints ────────────────────────────────────────────────────

@core_bp.post("/api/stocks/ai/qdrant/search")
def ai_qdrant_search():
    data  = request.get_json(silent=True) or {}
    query = str(data.get("query", "")).strip()
    try:
        limit = max(1, min(int(data.get("limit", 5)), 10))
    except (TypeError, ValueError):
        return jsonify({"error": "limit must be an integer"}), 400
    if not query:
        return jsonify({"error": "query is required"}), 400
    try:
        import qdrant_service as qs
        return jsonify({"results": qs.search(query, limit)})
    except Exception as exc:
        return error_response("지식 베이스 검색을 사용할 수 없습니다.", exc, 503)


@core_bp.get("/api/stocks/ai/qdrant/stats")
def ai_qdrant_stats():
    try:
        import qdrant_service as qs
        return jsonify(qs.stats())
    except Exception as exc:
        return error_response("지식 베이스 상태를 확인할 수 없습니다.", exc, 503)


@core_bp.get("/api/stocks/ai/qdrant/list")
def ai_qdrant_list():
    try:
        import qdrant_service as qs
        limit = max(1, min(int(request.args.get("limit", 30)), 100))
        return jsonify({"documents": qs.list_docs(limit)})
    except Exception as exc:
        return error_response("지식 베이스 문서 목록을 가져올 수 없습니다.", exc, 503)


@core_bp.post("/api/stocks/ai/qdrant/add")
def ai_qdrant_add():
    # 추가한 문서는 모든 방문자의 검색 결과와 AI 프롬프트에 들어간다. 관리자만 추가한다.
    if not is_admin_member(session.get("member_id")):
        return jsonify({"error": "관리자만 지식 베이스에 문서를 추가할 수 있습니다."}), 403
    data     = request.get_json(silent=True) or {}
    text     = str(data.get("text", "")).strip()
    title    = str(data.get("title", "")).strip()[:200]
    category = str(data.get("category", "custom")).strip()[:50] or "custom"
    if not text:
        return jsonify({"error": "text is required"}), 400
    if len(text) > 2000:
        return jsonify({"error": "text too long (max 2000 chars)"}), 400
    try:
        import qdrant_service as qs
        doc_id = qs.add_doc(text, title, category)
        return jsonify({"id": doc_id, "status": "added"})
    except Exception as exc:
        return error_response("지식 베이스에 문서를 추가할 수 없습니다.", exc, 503)


# ── KRX 보도자료 뉴스 ────────────────────────────────────────────────────────

_KRX_API     = "https://open.krx.co.kr/contents/OPN/99/OPN99000001.jspx"
_KRX_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type":    "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer":         "https://open.krx.co.kr/contents/OPN/05/05000000/OPN05000000T1.jsp",
    "X-Requested-With": "XMLHttpRequest",
    "Accept":          "application/json, text/javascript, */*; q=0.01",
}
_KRX_FILE_BASE = "https://file.krx.co.kr"
_KRX_PAGE_URL  = "https://open.krx.co.kr/contents/OPN/05/05000000/OPN05000000.jsp"

_news_cache = {"ts": 0.0, "data": None}
_news_lock  = threading.Lock()
_NEWS_TTL   = 300  # 5분


def _krx_pdf_url(noti_no: str) -> str:
    # noti_no = YYYYMMDDNN  →  file = YYYYMMDD0000NN2.pdf
    date   = noti_no[:8]
    serial = noti_no[8:]
    return f"{_KRX_FILE_BASE}/obk/dyn/noti/{date}0000{serial}2.pdf"


@core_bp.get("/api/stocks/news/krx")
def krx_news():
    now = time.time()
    with _news_lock:
        if _news_cache["data"] and now - _news_cache["ts"] < _NEWS_TTL:
            return jsonify(_news_cache["data"])

    try:
        from datetime import datetime, timedelta
        today    = datetime.now().strftime("%Y%m%d")
        one_year = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
        resp = _req.post(_KRX_API, headers=_KRX_HEADERS, data={
            "bld":      "OPN/05/05000000/opn05000000t1_01",
            "pagePath": "/contents/OPN/05/05000000/OPN05000000T1.jsp",
            "pageSize": "20",
            "sch_tp":   "title",
            "sch_word": "",
            "fromdate": one_year,
            "todate":   today,
        }, timeout=10)
        items = resp.json().get("output", [])
    except Exception as e:
        return error_response("KRX 보도자료를 가져올 수 없습니다.", e, 503, news=[])

    news = []
    for a in items:
        noti_no = a.get("noti_no", "")
        news.append({
            "noti_no":  noti_no,
            "title":    a.get("title", ""),
            "date":     a.get("creat_ddtm", ""),
            "view_cnt": a.get("inq_cnt", "0"),
            "pdf_url":  _krx_pdf_url(noti_no) if len(noti_no) == 10 else None,
            "page_url": _KRX_PAGE_URL,
        })

    result = {"news": news, "total": items[0].get("totCnt", "0") if items else "0"}

    with _news_lock:
        _news_cache["ts"]   = time.time()
        _news_cache["data"] = result

    return jsonify(result)



if __name__ == "__main__":
    # Direct `python app.py` run for development: same behaviour as before the
    # factory split (tables, seeds and the scheduler in this one process).
    from scheduler import start_scheduler

    bootstrap.create_tables()
    bootstrap.seed_demo_data()
    start_scheduler()
    create_app().run(host="0.0.0.0", port=8200, debug=False)
