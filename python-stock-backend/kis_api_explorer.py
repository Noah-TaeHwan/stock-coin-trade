"""KIS API 탐색기 백엔드.

공식 저장소(open-trading-api) 예제에서 추출한 카탈로그(kis_api_catalog.json)를 제공하고,
Testbed(모의투자)를 지원하는 읽기 전용(GET) API 만 서버가 대신 호출한다.

- 계좌 파라미터(CANO, ACNT_PRDT_CD)는 브라우저 값을 쓰지 않고 서버의 kis.key/.env 로 채운다.
- 주문성(POST) API 는 탐색기에서 호출하지 않는다. 보호된 모의 주문 흐름 테스트로 안내한다.
- 응답은 KIS 원문(rt_cd, msg_cd, msg1, output*)을 그대로 돌려주고, 한글 필드명 매핑을 함께 준다.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import requests
from flask import Blueprint, jsonify, request, session

from broker_test import KIS_TESTBED_URL, BrokerApiError, _json, _kis_account, _kis_headers

kis_explorer_bp = Blueprint("kis_explorer", __name__, url_prefix="/api/kis-explorer")

_CATALOG_PATH = Path(__file__).with_name("kis_api_catalog.json")
_CATALOG: dict[str, Any] = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
_BY_ID: dict[str, dict[str, Any]] = {api["id"]: api for api in _CATALOG["apis"]}

_ACCOUNT_CATEGORIES = {"주문/계좌"}
_VALUE_RE = re.compile(r"^[A-Za-z0-9_.\-:/ ]{0,40}$")
_CALL_GAP_SECONDS = 0.5  # Testbed 초당 호출 제한 회피 (시세)
_ACCOUNT_GAP_SECONDS = 1.1  # 계좌 TR 은 제한이 더 엄격해 간격을 더 둔다
_RATE_LIMIT_MSG_CD = "EGW00201"  # 초당 거래건수 초과 → 1회 자동 재시도
_call_lock = threading.Lock()
_last_call_at = 0.0


@kis_explorer_bp.get("/catalog")
def catalog():
    return jsonify({"ok": True, **_CATALOG})


def _throttle(gap: float = _CALL_GAP_SECONDS) -> None:
    global _last_call_at
    with _call_lock:
        wait = gap - (time.time() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.time()


def _build_params(api: dict[str, Any], user_params: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """(KIS 로 보낼 파라미터, 화면에 보여 줄 마스킹된 파라미터)."""
    cano, acnt_prdt_cd = (None, None)
    sent: dict[str, str] = {}
    shown: dict[str, str] = {}
    for p in api["params"]:
        key = p["key"]
        source = p["source"]
        if source == "server":
            if cano is None:
                cano, acnt_prdt_cd = _kis_account()
            value = cano if key == "CANO" else acnt_prdt_cd
            sent[key] = value
            shown[key] = (value[:4] + "****") if key == "CANO" else value
            continue
        if source == "blank":
            sent[key] = ""
            shown[key] = ""
            continue
        if source == "fixed":
            sent[key] = str(p.get("value", ""))
            shown[key] = sent[key]
            continue
        raw = user_params.get(key, p.get("default", ""))
        value = str(raw if raw is not None else "").strip()
        if not _VALUE_RE.match(value):
            raise BrokerApiError(f"{key} 값에 허용되지 않는 문자가 있거나 너무 깁니다.")
        if p.get("required") and value == "":
            raise BrokerApiError(f"{p.get('label') or key} 값은 필수입니다.")
        sent[key] = value
        shown[key] = value
    return sent, shown


def _select_tr_id(api: dict[str, Any], variant: str | None) -> str:
    selector = api.get("trSelector")
    if selector:
        if variant in selector["map"]:
            return selector["map"][variant]
        return next(iter(selector["map"].values()))
    return api["trIdDemo"][0]


@kis_explorer_bp.post("/call")
def call():
    body = request.get_json(silent=True) or {}
    api = _BY_ID.get(str(body.get("id", "")))
    if api is None:
        return jsonify({"ok": False, "message": "카탈로그에 없는 API 입니다."}), 404
    if not api["demoSupported"]:
        return jsonify({"ok": False, "message": "이 API 는 모의투자(Testbed)를 지원하지 않아 이 웹앱에서 호출하지 않습니다. 실전 계좌·실전 키가 필요합니다."})
    if api["method"] != "GET":
        return jsonify({"ok": False, "message": "주문·정정·취소 같은 주문성 API 는 탐색기에서 직접 호출하지 않습니다. 로그인 후 '모의 주문 흐름 테스트'에서 보호된 흐름으로만 실행합니다."})
    if api["category"] in _ACCOUNT_CATEGORIES and not session.get("member_id"):
        return jsonify({"ok": False, "message": "계좌 관련 API 는 이 웹앱에 로그인한 뒤 호출할 수 있습니다."}), 401

    try:
        params, shown = _build_params(api, body.get("params") or {})
        tr_id = _select_tr_id(api, body.get("variant"))
        gap = _ACCOUNT_GAP_SECONDS if api["category"] in _ACCOUNT_CATEGORIES else _CALL_GAP_SECONDS
        started = time.time()
        for attempt in range(2):
            _throttle(gap if attempt == 0 else gap + 1.0)
            response = requests.get(
                f"{KIS_TESTBED_URL}{api['url']}",
                headers={**_kis_headers(tr_id), "custtype": "P", "tr_cont": ""},
                params=params,
                timeout=15,
            )
            data = _json(response, "한국투자증권")
            if data.get("msg_cd") != _RATE_LIMIT_MSG_CD:
                break
        elapsed_ms = int((time.time() - started) * 1000)
    except BrokerApiError as exc:
        return jsonify({"ok": False, "message": str(exc)})
    except requests.RequestException:
        return jsonify({"ok": False, "message": "한국투자증권 서버 연결에 실패했습니다. 잠시 후 다시 시도하세요."}), 503

    return jsonify({
        "ok": data.get("rt_cd") == "0",
        "http": response.status_code,
        "rtCd": data.get("rt_cd"),
        "msgCd": data.get("msg_cd"),
        "msg1": (data.get("msg1") or "").strip(),
        "trId": tr_id,
        "url": api["url"],
        "elapsedMs": elapsed_ms,
        "request": shown,
        "body": data,
        "columns": api.get("columns", {}),
    })
