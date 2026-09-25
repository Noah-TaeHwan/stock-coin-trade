"""자연어 터미널 명령을 화면·종목·전략으로 바꾸는 Jev 라우터.

Jev(TypeSafe System One)는 의미 판단만 한다. 정해진 선택지 중에서 어느 화면인지, 어느
종목·코인·전략을 말했는지를 고르고 확률을 돌려준다. 숫자와 날짜는 다루지 않고(공식 한계),
주문도 실행하지 않는다. URL을 만들고 행동(이동·제안·도움말)을 정하는 것은 이 코드다.

한 요청에 네 질문(화면·주식·코인·전략)을 함께 보낸다. 서로의 답을 보지 않는 병렬 질문이라
"백테스트를 원한다면" 같은 가정은 질문 문장에 적고, 쓰일 답만 코드가 고른다(speculative fan-out).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode

from deskjev import MODEL  # noqa: F401 (평가와 테스트가 intent.MODEL로 읽는다)

MAX_TEXT = 200
# evals/jev_intent 실측으로 정한 값(모델을 바꾸면 다시 잰다).
# 화면 확률이 GO 이상이면 바로 이동하고, SUGGEST 이상이면 후보를 보여 준다.
# 종목·전략 같은 인자는 확률이 ARG_MIN 이상일 때만 싣는다. 애매한 인자는 틀리게 싣는 것보다 빼는 편이 낫다.
GO = 0.85
SUGGEST = 0.4
ARG_MIN = 0.85

# 화면 id → (경로, Jev에게 주는 설명). 설명이 판단 기준이므로 기능을 구체적으로 적는다.
SCREENS: dict[str, tuple[str | None, str]] = {
    "dashboard": ("/index.html", "시장 전체 요약을 보는 첫 화면(대시보드, 홈, 메인)"),
    "stock": ("/trade/stock.html", "국내 주식 한 종목의 시세·차트·호가를 보거나 모의 주문하는 화면"),
    "coin": ("/trade/order.html", "코인 한 종목의 시세·차트·호가를 보거나 모의 주문하는 화면"),
    "arbitrage": ("/arbitrage.html", "거래소 간 코인 가격 차이, 김치 프리미엄(김프), 차익 계산 화면"),
    "alternatives": ("/trade/alternatives.html", "선물·금·은·원자재·부동산 같은 대체자산 모의 거래 화면"),
    "holdings": ("/trade/hold.html", "사용자 본인의 보유 자산·잔고·평가손익 화면"),
    "history": ("/trade/history.html", "사용자 본인의 과거 매매·체결 기록 화면"),
    "avg_down": ("/trade/avg-down.html", "추가 매수(물타기) 뒤 평균 단가를 계산하는 도구"),
    "quant": ("/quant.html", "매매 전략을 과거 데이터로 시험하는 백테스트·퀀트 랩"),
    "research": ("/research-agent.html", "시장·업종·종목에 대한 질문에 근거를 갖춘 AI 리서치 답변을 받는 화면"),
    "knowledge": ("/knowledge-search.html", "투자 용어와 개념의 뜻을 찾아보는 지식 검색"),
    "analysis": ("/analysis.html", "재무제표·기술적 분석 같은 투자 분석을 배우는 학습 화면"),
    "openapi": ("/openapi.html", "이 플랫폼의 Open API 문서와 사용법"),
    "none": (None, "위 어느 화면과도 관련 없는 요청(잡담, 계정·비밀번호, 관리자 기능 등)"),
}
# 화면별로 URL에 싣는 인자. 여기에 없는 화면은 종목·전략 답을 쓰지 않는다.
USES = {"stock": ("stock",), "coin": ("coin",), "arbitrage": ("coin",), "quant": ("stock", "coin", "strategy")}
NONE = "none"


@dataclass(frozen=True)
class Intent:
    """라우팅 결과. confidence는 화면 확률이고, 인자는 ARG_MIN을 넘은 것만 담긴다."""

    action: str  # go | suggest | help
    screen: str
    href: str | None
    confidence: float
    stock: str | None = None
    coin: str | None = None
    strategy: str | None = None
    alternatives: list[dict] = field(default_factory=list)
    input_tokens: int = 0


def questions(stocks: dict[str, str], coins: dict[str, str], strategies: dict[str, str]) -> dict:
    """한 요청에 보낼 질문 네 개. stocks/coins/strategies는 {값: 설명}이고 선택지가 된다.

    @param stocks 종목코드 → 종목명
    @param coins 코인 심볼 → 한글명
    @param strategies 전략 키 → 설명
    @returns 질문 id → typesafe_sdk 질문 객체
    """
    from typesafe_sdk import Choice

    return {
        "screen": Choice(
            instructions="주식·코인 모의투자 터미널 사용자가 `user_command`로 가려는 화면은 어디인가?",
            criteria={key: text for key, (_, text) in SCREENS.items()},
        ),
        "stock": Choice(
            instructions=(
                "`user_command`가 가리키는 국내 주식 종목은 무엇인가? 약칭·영문 이름·오타도 그 종목으로 본다. "
                "목록에 없는 종목이거나 주식 종목을 말하지 않았으면 none이다."
            ),
            criteria={**{code: f"{name} ({code})" for code, name in stocks.items()}, NONE: "해당 없음"},
        ),
        "coin": Choice(
            instructions=(
                "`user_command`가 가리키는 코인은 무엇인가? 줄임말·영문 심볼도 그 코인으로 본다. "
                "목록에 없는 코인이거나 코인을 말하지 않았으면 none이다."
            ),
            criteria={**{sym: f"{name} ({sym})" for sym, name in coins.items()}, NONE: "해당 없음"},
        ),
        "strategy": Choice(
            instructions="사용자가 백테스트를 원한다고 가정할 때, `user_command`가 말하는 매매 전략은 무엇인가?",
            criteria={**strategies, NONE: "전략을 말하지 않음"},
        ),
    }


def _top(answer) -> tuple[str, float]:
    # SDK의 choice 값이 최고 확률 항목과 어긋난 보고가 있어(sdk-python#15) 분포에서 직접 고른다.
    key = max(answer.probabilities, key=answer.probabilities.get)
    return key, answer.probabilities[key]


def _href(screen: str, stock: str | None, coin: str | None, strategy: str | None) -> str | None:
    path = SCREENS[screen][0]
    if path is None:
        return None
    params = {
        "stock": {"symbol": stock},
        "coin": {"market": f"KRW-{coin}" if coin else None},
        "arbitrage": {"symbol": coin},
        "quant": {"symbol": stock or (f"KRW-{coin}" if coin else None), "strategy": strategy},
    }.get(screen, {})
    query = urlencode({k: v for k, v in params.items() if v})
    return f"{path}?{query}" if query else path


def decide(answers: dict, input_tokens: int = 0, allowed: dict[str, set[str]] | None = None) -> Intent:
    """Jev 답(질문 id → SDK 답 객체)을 행동으로 바꾼다. API를 부르지 않는 순수 함수다.

    외부 API의 답은 신뢰 경계 밖이다. 화면은 SCREENS에, 인자는 allowed(보낸 후보 키)에 있는 값만 쓴다.

    @param answers system_one 응답의 answers
    @param input_tokens 과금 기록용 입력 토큰 수
    @param allowed 인자 이름 → 허용 값 집합(route가 보낸 후보). None이면 검사하지 않는다(테스트용)
    @returns 이동·제안·도움말 중 하나를 담은 Intent
    """
    screen, p_screen = _top(answers["screen"])
    if screen not in SCREENS:
        screen = NONE
    picked: dict[str, str | None] = {"stock": None, "coin": None, "strategy": None}
    for name in USES.get(screen, ()):
        value, p = _top(answers[name])
        if value != NONE and p >= ARG_MIN and (allowed is None or value in allowed[name]):
            picked[name] = value
    if picked["stock"] and picked["coin"]:  # 퀀트는 종목 하나만 받는다. 주소와 필드가 어긋나지 않게 주식을 남긴다.
        picked["coin"] = None
    href = _href(screen, **picked)
    ranked = sorted(answers["screen"].probabilities.items(), key=lambda kv: kv[1], reverse=True)
    alternatives = [
        # 선택된 화면의 후보에는 종목·전략까지 담은 주소를 준다.
        {"screen": key, "href": href if key == screen else SCREENS[key][0], "probability": round(p, 3)}
        for key, p in ranked
        if key in SCREENS and key != NONE and p >= 0.05
    ][:3]
    if screen == NONE:
        action = "help"
    elif p_screen >= GO:
        action = "go"
    elif alternatives and alternatives[0]["probability"] >= SUGGEST:
        action = "suggest"
    else:
        action = "help"
    return Intent(
        action=action,
        screen=screen,
        href=href,
        confidence=round(p_screen, 3),
        alternatives=alternatives,
        input_tokens=input_tokens,
        **picked,
    )


def route(client, text: str, stocks: dict[str, str], coins: dict[str, str], strategies: dict[str, str]) -> Intent:
    """명령 한 줄을 Jev에 한 번 보내 Intent로 바꾼다.

    @param client typesafe_sdk.TypeSafeClient(또는 같은 system_one을 가진 테스트 대역)
    @param text 사용자가 입력한 명령(MAX_TEXT자로 자른다)
    @returns Intent
    """
    response = client.system_one(
        {"user_command": text.strip()[:MAX_TEXT]},
        questions(stocks, coins, strategies),
        model=MODEL,
    )
    allowed = {"stock": set(stocks), "coin": set(coins), "strategy": set(strategies)}
    return decide(response.answers, int(response.usage.input_tokens or 0), allowed)
