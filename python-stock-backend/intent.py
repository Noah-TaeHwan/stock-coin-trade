"""자연어 터미널 명령 API (src/deskjev, TypeSafe Jev).

POST /api/intent {"text": "하닉 골든크로스 백테스트"} → 이동할 화면과 신뢰도.
- 기본 꺼짐(JEV_ENABLED). 꺼져 있거나 월 예산을 넘었거나 Jev가 응답하지 않으면 {"enabled": false}를
  돌려주고, 명령 바는 기존 동작(메뉴 검색 → 주식 검색)으로 돌아간다.
- Jev에 보내는 것은 명령 문장 한 줄뿐이다. 계좌·보유 정보는 보내지 않고, 문장은 저장하지 않는다.
- 문장은 미국(TypeSafe AI, Inc.)으로 가므로(국외 이전, 개인정보 처리방침 4절) 현재 처리방침 버전에
  동의한 요청만 보낸다. 동의가 없으면 Jev를 부르지 않고 consentRequired로 답한다.
- 이동과 폼 채우기만 한다. 주문은 하지 않는다.
"""

from __future__ import annotations

import threading
from functools import lru_cache

from flask import Blueprint, current_app, jsonify, request

import jev_usage
from accounts import PRIVACY_VERSION
from errors import log_exception
from extensions import limiter

intent_bp = Blueprint("intent", __name__, url_prefix="/api/intent")

# 코인 한글명과 흔한 줄임말. 후보는 김프 화면이 다루는 코인과 같다.
COIN_NAMES = {
    "BTC": "비트코인, 흔히 비트",
    "ETH": "이더리움, 흔히 이더",
    "XRP": "리플",
    "SOL": "솔라나",
    "DOGE": "도지코인, 흔히 도지",
    "ADA": "에이다",
    "TRX": "트론",
    "LINK": "체인링크",
}

# 흔히 부르는 종목 별칭. 선택지 설명에 넣어 Jev가 약칭을 종목에 연결하게 한다.
STOCK_ALIASES = {
    "005930": "삼전",
    "000660": "하이닉스, 하닉",
    "035420": "네이버",
    "207940": "삼바",
    "373220": "엔솔",
    "005490": "포스코",
    "005380": "현대자동차",
}


def candidates() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Jev 선택지: (종목코드→이름, 코인→한글명, 전략 키→설명).

    @returns 주식·코인·전략 후보. 평가(src/deskjev/eval.py)도 같은 후보를 쓴다.
    """
    from quantlab.strategies import STRATEGIES
    from stock_market import STOCKS

    stocks = {
        code: f"{info['name']}, 흔히 {STOCK_ALIASES[code]}" if code in STOCK_ALIASES else info["name"]
        for code, info in STOCKS.items()
    }
    # 같은 이평 교차 규칙을 쓰는 전략(ma2050·trend)은 기본 기간으로만 구별되므로 기간을 적는다.
    strategies = {
        key: f"{spec.label}"
        + (f"(기본 {spec.default_fast}일/{spec.default_slow}일 이동평균)" if spec.uses_fast_slow else "")
        + f": {spec.rule}"
        for key, (spec, _) in STRATEGIES.items()
    }
    return stocks, dict(COIN_NAMES), strategies


# 캐시에서 나온 답은 과금되지 않았으므로 원장에 적지 않는다. 캐시를 놓쳐 실제로 호출한 요청만
# 이 스레드의 플래그를 켠다(cache_info() 카운터는 다른 스레드의 적중과 섞인다).
_call = threading.local()


@lru_cache(maxsize=1024)  # ponytail: 프로세스별 캐시. 같은 명령 반복은 API를 다시 부르지 않는다.
def _route(normalized: str):
    from deskjev.intent import route

    _call.billed = True
    # 명령 바는 사람이 기다리는 화면이라 짧게 끊고(기본 3초), 실패하면 기존 동작으로 돌아간다.
    return route(jev_usage.client(), normalized, *candidates())


@intent_bp.post("")
@limiter.limit("20 per minute")
def resolve():
    if not current_app.config.get("JEV_ENABLED"):
        return jsonify({"enabled": False})
    body = request.get_json(silent=True) or {}
    if body.get("consent") != PRIVACY_VERSION:
        return jsonify({"enabled": True, "consentRequired": True, "consentVersion": PRIVACY_VERSION})
    raw = body.get("text")
    if not isinstance(raw, str) or not raw.strip():
        return jsonify({"message": "text가 필요합니다."}), 400
    from deskjev.intent import MAX_TEXT

    normalized = " ".join(raw.split())[:MAX_TEXT]
    try:
        # ponytail: 확인 후 기록이라 동시 요청은 예산을 호출 몇 건(건당 약 $0.0001)만큼 넘을 수 있다.
        # 상한이 달러 단위라 잠금 없이 둔다. 엄격한 상한이 필요하면 SELECT ... FOR UPDATE로 묶는다.
        if jev_usage.over_budget(current_app.config["JEV_MONTHLY_BUDGET_USD"]):
            return jsonify({"enabled": False, "reason": "budget"})
        _call.billed = False
        intent = _route(normalized)
        if _call.billed:
            jev_usage.record(intent.input_tokens)
    except Exception as exc:  # Jev 장애·시간 초과는 명령 바를 막지 않는다
        log_exception("intent route", exc)
        return jsonify({"enabled": False, "reason": "unavailable"})
    return jsonify(
        {
            "enabled": True,
            "action": intent.action,
            "screen": intent.screen,
            "href": intent.href,
            "confidence": intent.confidence,
            "alternatives": intent.alternatives,
        }
    )
