import hashlib
import hmac
import secrets
import time

import requests

from flask import Blueprint, jsonify, request, session

from broker_test import (
    BrokerApiError,
    check_kb_token,
    get_kb_domestic_quote,
    get_kb_stock_base_info,
    get_kb_stock_chart,
    get_kb_stock_orderbook,
    get_kb_configuration_status,
    get_kis_balance,
    get_kis_daily_chart,
    get_kis_index,
    get_kis_orderbook,
    get_kis_quote,
    run_kis_mock_order_flow_test,
)
from authz import can_use_kis_account
from security import csrf_is_valid


broker_test_bp = Blueprint("broker_test", __name__, url_prefix="/api/broker-test")


def _symbol() -> str:
    symbol = request.args.get("symbol", "005930").strip()
    if len(symbol) != 6 or not symbol.isdigit():
        raise BrokerApiError("종목코드는 6자리 KRX 숫자 코드여야 합니다.", 400)
    return symbol


def _kis_response(build):
    try:
        return jsonify({"ok": True, **build()})
    except BrokerApiError as exc:
        # Preserve a machine-observable HTTP status while returning a safe body.
        return jsonify({"ok": False, "broker": "한국투자증권 Testbed", "message": str(exc)}), exc.status_code
    except requests.RequestException:
        return jsonify({"ok": False, "broker": "한국투자증권 Testbed", "message": "한국투자증권 서버 연결에 실패했습니다. 잠시 후 다시 시도하세요."}), 503


def _kb_response(build):
    if not session.get("member_id"):
        return jsonify({"ok": False, "broker": "KB증권", "message": "KB API 실습은 로그인 후 이용할 수 있습니다."}), 401
    try:
        return jsonify({"ok": True, **build()})
    except BrokerApiError as exc:
        return jsonify({"ok": False, "broker": "KB증권", "message": str(exc)}), exc.status_code
    except requests.RequestException:
        return jsonify({"ok": False, "broker": "KB증권", "message": "KB증권 서버 연결에 실패했습니다. 잠시 후 다시 시도하세요."}), 503


@broker_test_bp.get("/kis/quote")
def kis_quote():
    return _kis_response(lambda: {"quote": get_kis_quote(_symbol())})


@broker_test_bp.get("/kis/balance")
def kis_balance():
    if not can_use_kis_account(session.get("member_id")):
        return jsonify({"ok": False, "message": "KIS 모의계좌 잔고는 로그인 후 조회할 수 있습니다."}), 401
    return _kis_response(lambda: {"balance": get_kis_balance()})


@broker_test_bp.get("/kis/chart")
def kis_chart():
    return _kis_response(lambda: {"chart": get_kis_daily_chart(_symbol())})


@broker_test_bp.get("/kis/orderbook")
def kis_orderbook():
    return _kis_response(lambda: {"orderbook": get_kis_orderbook(_symbol())})


@broker_test_bp.get("/kis/index")
def kis_index():
    code = request.args.get("code", "0001").strip()
    if code not in ("0001", "1001"):
        return jsonify({"ok": False, "broker": "한국투자증권 Testbed", "message": "code는 0001(코스피) 또는 1001(코스닥)이어야 합니다."}), 400
    return _kis_response(lambda: {"index": get_kis_index(code)})


_ORDER_APPROVAL_KEY = "kis_order_approval"


@broker_test_bp.post("/kis/order-flow-approval")
def kis_order_flow_approval():
    member_id = session.get("member_id")
    if not member_id:
        return jsonify({"ok": False, "message": "로그인이 필요합니다."}), 401
    if not can_use_kis_account(member_id):
        return jsonify({"ok": False, "message": "KIS 모의 주문 테스트는 로그인한 회원만 실행할 수 있습니다."}), 401
    if not csrf_is_valid():
        return jsonify({"ok": False, "message": "요청 검증에 실패했습니다. 화면을 새로고침한 뒤 다시 시도하세요."}), 403
    token = secrets.token_urlsafe(32)
    session[_ORDER_APPROVAL_KEY] = {
        "digest": hashlib.sha256(token.encode()).hexdigest(),
        "expiresAt": time.time() + 60,
    }
    return jsonify({"ok": True, "approvalToken": token, "expiresIn": 60})


@broker_test_bp.post("/kis/order-flow-test")
def kis_order_flow_test():
    member_id = session.get("member_id")
    if not member_id:
        return jsonify({"ok": False, "message": "모의 주문 흐름 테스트는 로그인 후 실행할 수 있습니다."}), 401
    if not can_use_kis_account(member_id):
        return jsonify({"ok": False, "message": "KIS 모의 주문 테스트는 로그인한 회원만 실행할 수 있습니다."}), 401
    if not csrf_is_valid():
        return jsonify({"ok": False, "message": "요청 검증에 실패했습니다. 화면을 새로고침한 뒤 다시 시도하세요."}), 403
    approval = session.pop(_ORDER_APPROVAL_KEY, None) or {}
    supplied = str((request.get_json(silent=True) or {}).get("approvalToken", ""))
    supplied_digest = hashlib.sha256(supplied.encode()).hexdigest()
    if not approval or approval.get("expiresAt", 0) < time.time() or not hmac.compare_digest(approval.get("digest", ""), supplied_digest):
        return jsonify({"ok": False, "message": "주문 실행 승인이 만료되었거나 유효하지 않습니다. 다시 확인 후 실행하세요."}), 403
    return _kis_response(lambda: {"test": run_kis_mock_order_flow_test()})


@broker_test_bp.get("/kb/token")
def kb_token():
    return _kb_response(lambda: {"check": check_kb_token()})


@broker_test_bp.get("/kb/status")
def kb_status():
    return _kb_response(lambda: {"status": get_kb_configuration_status()})


@broker_test_bp.get("/kb/quote")
def kb_quote():
    return _kb_response(lambda: {"quote": get_kb_domestic_quote(_symbol())})


@broker_test_bp.get("/kb/base-info")
def kb_base_info():
    return _kb_response(lambda: {"result": get_kb_stock_base_info(_symbol())})


@broker_test_bp.get("/kb/orderbook")
def kb_orderbook():
    return _kb_response(lambda: {"result": get_kb_stock_orderbook(_symbol())})


@broker_test_bp.get("/kb/chart")
def kb_chart():
    try:
        count = int(request.args.get("count", "60"))
    except ValueError:
        return jsonify({"ok": False, "broker": "KB증권", "message": "count는 숫자여야 합니다."}), 400
    market = request.args.get("market", "0").strip()
    period = request.args.get("period", "D").strip().upper()
    return _kb_response(lambda: {"result": get_kb_stock_chart(_symbol(), market, period, count)})
