"""거래소 공지 한 건을 "실행 위험" 판정으로 바꾼다(빗썸 공지 레이더).

규칙이 먼저다. 분류(categories)와 제목의 낱말·괄호 속 티커·재개 날짜로 판정할 수 있으면 코드가 끝낸다.
규칙이 못 정한 공지만 Jev(TypeSafe System One)에 한 번 묻는다. 한 요청에 두 질문(공지 종류·대상 범위)을
함께 보내고(speculative fan-out), 날짜·숫자 판단은 맡기지 않는다(공식 한계. 한국어는 영어보다 덜 안정적이다).
Jev의 답은 신뢰 경계 밖이다: 보낸 선택지에 있는 값만 쓴다.

판정의 뜻
- kind: suspend(입출금 중단·예정) | caution(거래유의 지정·거래지원 종료) | external(외부 거래소 대상 출금 주의)
  | none(위험 아님) | unknown(규칙이 못 정했고 Jev도 쓰지 못함)
- coins: 티커 목록 | "ALL"(거래소 전체 자산) | "UNKNOWN"(대상 불명)
- probability: Jev가 판정했을 때 위험 종류들의 확률 합. 규칙 판정은 None이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from deskjev import MODEL

KST = timezone(timedelta(hours=9))
RISK_KINDS = ("suspend", "caution", "external")
# evals/jev_notices 실측(2026-09-26, jev-1.13.0)으로 정한 값. 모델을 바꾸면 다시 잰다.
# 위험 확률 합이 이 값 이상이면 경고한다.
# 규칙+Jev에서 0.3~0.5의 재현율은 같았다(98.7%). 0.5는 오경보가 가장 적지만 맞게 잡은 위험 하나가 0.53이라,
# 놓치는 쪽이 더 비싼 점을 보고 여유를 둔 0.4로 정했다(오경보 5.1%).
RISK_MIN = 0.4

# Jev에게 주는 선택지. 설명이 판단 기준이다. resume·release는 위험이 아니지만 "중단"·"지정"과 헷갈리지 않게 따로 둔다.
KINDS = {
    "suspend": "입출금 중단: 가상자산의 입금이나 출금이 멈췄거나 멈출 예정이다(점검, 네트워크 업그레이드·하드포크, "
    "토큰 전환·스왑, 전체 서비스 점검 포함)",
    "resume": "재개·정상화: 멈췄던 입출금이 다시 열렸거나 정상화됐다고 알린다",
    "caution": "거래 경고: 거래유의종목 지정·지정 기간 연장, 투자 유의 촉구, 거래지원 종료(상장폐지)를 알린다",
    "release": "경고 해제: 거래유의종목 지정 해제, 거래지원 종료 철회처럼 경고가 풀렸다고 알린다",
    "external": "외부 거래소 주의: 다른 거래소로 출금하거나 다른 거래소에서 입금받을 때 주의하라고 알린다",
    "none": "해당 없음: 이벤트, 에어드랍, 스테이킹, 신규 상장, 수수료·고객센터·약관 안내처럼 "
    "입출금·거래 위험과 관련 없다",
}
SCOPES = {
    "coins": "제목에 이름이 나온 특정 가상자산(한 개 또는 몇 개)",
    "network": "특정 블록체인 네트워크에 속한 가상자산 여러 종(예: 'OO 네트워크 계열 가상자산 N종')",
    "all": "거래소의 모든 가상자산(전체 입출금 중단, 전체 서비스 점검 등)",
    "none": "특정 가상자산을 가리키지 않음(외부 거래소, 고객센터, 일반 안내)",
}

# 규칙이 못 정하고 Jev도 쓸 수 없을 때, 이 분류의 공지는 "확인 필요"로 띄운다(놓치는 쪽이 더 비싸다).
RISK_CATEGORIES = {"입출금", "거래유의", "점검"}
SAFE_CATEGORIES = {"이벤트", "신규서비스"}

_TICKER = re.compile(r"\(\s*([A-Z0-9]{1,12}(?:\s*,\s*[A-Z0-9]{1,12})*)\s*\)")
_RESUMED_ON = re.compile(r"\((\d{1,2})/(\d{1,2})\s*재개\)")
_SUSPEND = re.compile(r"(입출금|입금|출금)[^()]*?(중지|중단)")
_CAUTION = re.compile(r"유의\s*종목\s*지정|거래\s*지원\s*종료|투자\s*유의\s*촉구")
_UNDO = re.compile(r"해제|철회|취소|연기")
_EXTERNAL = re.compile(r"거래소\s*대상.*주의|출금\s*주의")
_BACK = re.compile(r"재개|정상화")
_ALL = re.compile(r"(전체|모든)\s*(가상자산|자산|코인)|가상자산\s*입출금")
_NETWORK = re.compile(r"네트워크\s*계열|계열\s*가상자산")


@dataclass(frozen=True)
class Verdict:
    """공지 한 건의 판정.

    @param risk 김프 화면에 "확인 필요"로 띄울지
    @param kind suspend | caution | external | none | unknown
    @param coins 티커 목록 | "ALL" | "UNKNOWN"
    @param network coins가 네트워크 이름이고 그 네트워크의 토큰 전체가 대상인지
    @param probability Jev 판정의 위험 확률 합(규칙 판정은 None)
    @param by rules | jev
    @param input_tokens 과금 기록용 입력 토큰 수
    """

    risk: bool
    kind: str
    coins: list[str] | str
    network: bool = False
    probability: float | None = None
    by: str = "rules"
    input_tokens: int = 0


def tickers(title: str) -> list[str]:
    """제목 괄호 안의 대문자 티커. 거래소 이름(Bitget)·날짜·숫자만 있는 괄호는 빠진다.

    @param title 공지 제목
    @returns 나온 순서대로 중복 없는 티커 목록
    """
    found: list[str] = []
    for group in _TICKER.findall(title):
        for token in re.split(r"\s*,\s*", group):
            if any(c.isalpha() for c in token) and token not in found:
                found.append(token)
    return found


def _published(notice: dict) -> date | None:
    try:
        return datetime.strptime(notice.get("published_at") or "", "%Y-%m-%d %H:%M:%S").date()
    except ValueError:
        return None


def _resumed_on(title: str, published: date | None, now: datetime) -> date | None:
    """제목의 "(MM/DD 재개)"를 날짜로. 연도는 게시일에서 잡고, 게시일보다 반년 넘게 앞서면 다음 해로 본다."""
    match = _RESUMED_ON.search(title)
    if not match:
        return None
    base = published or now.date()
    try:
        day = date(base.year, int(match[1]), int(match[2]))
    except ValueError:
        return None
    return day.replace(year=day.year + 1) if day < base - timedelta(days=180) else day


def _coins_or_unknown(title: str) -> list[str] | str:
    return tickers(title) or "UNKNOWN"


def rules(notice: dict, now: datetime) -> Verdict | None:
    """분류·제목 규칙으로 판정한다. 못 정하면 None(Jev에 묻는다).

    @param notice 빗썸 공지 한 건({title, categories, published_at, ...})
    @param now 지금 시각(KST aware). 재개 날짜가 지났는지 비교한다
    @returns Verdict 또는 None
    """
    title = " ".join(str(notice.get("title") or "").split())
    categories = set(notice.get("categories") or [])
    coins = tickers(title)
    worded = _SUSPEND.search(title) or _CAUTION.search(title) or _EXTERNAL.search(title)

    if categories & SAFE_CATEGORIES and not worded:
        return Verdict(False, "none", coins)
    resumed_on = _resumed_on(title, _published(notice), now)
    if resumed_on is not None and coins:
        # 재개일이 지났으면 끝난 중단, 아직이면 그날까지 중단이다.
        if resumed_on <= now.astimezone(KST).date():
            return Verdict(False, "none", coins, bool(_NETWORK.search(title)))
        return Verdict(True, "suspend", coins, bool(_NETWORK.search(title)))
    if _CAUTION.search(title):
        if _UNDO.search(title):
            return Verdict(False, "none", coins)
        return Verdict(True, "caution", coins) if coins else None
    if _EXTERNAL.search(title):
        return Verdict(True, "external", "ALL")
    if _SUSPEND.search(title):
        if _BACK.search(title):  # "중지 … 재개"인데 날짜가 없다
            return None
        if coins:
            return Verdict(True, "suspend", coins, bool(_NETWORK.search(title)))
        if _ALL.search(title) and "일부" not in title:
            return Verdict(True, "suspend", "ALL")
        return None
    if _BACK.search(title) and coins:
        return Verdict(False, "none", coins)
    return None


def fallback(notice: dict) -> Verdict:
    """규칙이 못 정했고 Jev를 쓸 수 없을 때: 위험 분류의 공지는 종류 불명의 경고로 띄운다.

    @param notice 빗썸 공지 한 건
    @returns by="rules", kind="unknown"인 Verdict
    """
    risky = bool(set(notice.get("categories") or []) & RISK_CATEGORIES)
    return Verdict(risky, "unknown", _coins_or_unknown(str(notice.get("title") or "")))


def questions() -> dict:
    """한 요청에 보낼 질문 두 개(공지 종류·대상 범위).

    @returns 질문 id → typesafe_sdk 질문 객체
    """
    from typesafe_sdk import Choice

    return {
        "kind": Choice(
            instructions=(
                "가상자산 거래소 빗썸의 공지 제목 `title`과 분류 `categories`를 보고, 이 공지가 알리는 내용을 고른다. "
                "공지 본문은 없다."
            ),
            criteria=KINDS,
        ),
        "scope": Choice(
            instructions="이 빗썸 공지(`title`, `categories`)가 해당하는 가상자산의 범위는 어디까지인가?",
            criteria=SCOPES,
        ),
    }


def _distribution(answer, allowed: dict) -> dict[str, float]:
    # 보낸 선택지에 없는 값은 버린다. SDK의 choice 값은 쓰지 않고 분포를 쓴다(sdk-python#15).
    probabilities = {k: float(p) for k, p in (answer.probabilities or {}).items() if k in allowed}
    if not probabilities:
        raise ValueError("Jev 답에 보낸 선택지가 없다")
    return probabilities


def decide(answers: dict, notice: dict, input_tokens: int = 0) -> Verdict:
    """Jev 답을 판정으로 바꾼다. API를 부르지 않는 순수 함수다.

    위험 확률은 위험 종류(suspend·caution·external) 확률의 합이다. 하나의 종류로 몰리지 않아도
    위험 쪽 합이 크면 경고한다.

    @param answers system_one 응답의 answers(kind, scope)
    @param notice 빗썸 공지 한 건(티커는 제목에서 코드가 뽑는다)
    @param input_tokens 과금 기록용 입력 토큰 수
    @returns by="jev"인 Verdict
    @raises ValueError 답에 보낸 선택지가 하나도 없을 때(호출한 쪽이 규칙으로 돌아간다)
    """
    kinds = _distribution(answers["kind"], KINDS)
    scopes = _distribution(answers["scope"], SCOPES)
    p_risk = sum(kinds.get(k, 0.0) for k in RISK_KINDS)
    risk = p_risk >= RISK_MIN
    kind = max(RISK_KINDS, key=lambda k: kinds.get(k, 0.0)) if risk else "none"
    scope = max(scopes, key=scopes.get)
    title = str(notice.get("title") or "")
    coins: list[str] | str = "ALL" if kind == "external" or scope == "all" else _coins_or_unknown(title)
    return Verdict(
        risk=risk,
        kind=kind,
        coins=coins,
        network=scope == "network" and isinstance(coins, list),
        probability=round(p_risk, 3),
        by="jev",
        input_tokens=input_tokens,
    )


def ask(client, notice: dict) -> tuple[dict, int]:
    """공지 한 건을 Jev에 한 번 보낸다. 제목과 분류만 보낸다.

    @param client typesafe_sdk.TypeSafeClient(또는 같은 system_one을 가진 테스트 대역)
    @param notice 빗썸 공지 한 건
    @returns (answers, input_tokens)
    """
    state = {"title": str(notice.get("title") or "")[:200], "categories": list(notice.get("categories") or [])}
    response = client.system_one(state, questions(), model=MODEL)
    return response.answers, int(response.usage.input_tokens or 0)


def judge(notice: dict, now: datetime, ask_jev=None) -> Verdict:
    """규칙 → (못 정하면) Jev → (Jev를 쓰지 않으면) 규칙 폴백.

    @param notice 빗썸 공지 한 건
    @param now 지금 시각(KST aware)
    @param ask_jev notice → (answers, input_tokens). None이면 Jev를 쓰지 않는다. 예외는 호출한 쪽으로 올린다
    @returns Verdict
    """
    verdict = rules(notice, now)
    if verdict is not None:
        return verdict
    if ask_jev is None:
        return fallback(notice)
    answers, input_tokens = ask_jev(notice)
    return decide(answers, notice, input_tokens)
