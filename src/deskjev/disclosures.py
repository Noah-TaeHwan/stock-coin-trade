"""DART 공시 제목을 교육용 유형과 '매매 불가 위험'으로 나누는 판정기(규칙 먼저, 남은 것만 Jev).

`report_nm`은 대부분 정해진 서식명이라 규칙 표(서식명 조각 → 유형·위험)로 정한다. Jev(TypeSafe
System One)는 규칙이 정하지 못한 것에만 쓴다: 자유 서식(투자판단관련주요경영사항, 기타시장안내·
기타경영사항의 부제)과, 유형은 알아도 위험이 부제에 달린 서식(조회공시·소송). 한 공시에 두 질문
(유형 Choice, 위험 Noul)을 한 요청으로 보내고 코드가 필요한 답만 쓴다. 회사명은 보내지 않는다.

교육용 분류이며 투자 권유가 아니다. 확률은 모델 판단 확률이고, 날짜·숫자 판단은 맡기지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from deskjev import MODEL  # noqa: F401 (평가와 테스트가 disclosures.MODEL로 읽는다)

# 유형 id → (화면 이름, Jev에게 주는 설명). 설명이 판단 기준이므로 대표 서식명을 적는다.
KINDS: dict[str, tuple[str, str]] = {
    "rights_offering": ("유상증자", "돈을 받고 새 주식을 발행(유상증자·유무상증자 결정, 발행가액 확정, 권리락)"),
    "equity_linked": (
        "주식관련사채",
        "전환사채(CB)·신주인수권부사채(BW)·교환사채(EB)·조건부자본증권 발행, "
        "전환가액 조정, 전환청구권 행사, 만기 전 사채 취득·매도",
    ),
    "treasury_stock": ("자기주식", "회사가 자기 주식을 취득·처분·소각(자기주식 신탁계약 포함)"),
    "capital_change": ("무상증자·감자", "무상증자, 감자, 주식 병합·분할, 액면 변경"),
    "supply_contract": ("공급계약", "단일판매·공급계약 체결·해지, 수주"),
    "control_change": (
        "최대주주·경영권",
        "최대주주 변경, 최대주주가 바뀌는 주식 양수도·담보 계약, 경영권 계약, 공개매수",
    ),
    "m_and_a": ("합병·분할·양수도", "합병, 회사 분할, 영업·유형자산·타법인 지분 양수도, 신규 시설 투자·증설"),
    "earnings": ("실적", "영업(잠정)실적, 매출액·손익구조 30%(대규모법인 15%) 이상 변경, 결산 실적"),
    "periodic_report": ("정기보고서", "사업·반기·분기보고서, 감사보고서 제출"),
    "ownership": ("지분 공시", "임원·주요주주 특정증권 소유상황, 5% 대량보유 상황, 최대주주 등 소유주식 변동"),
    "shareholder_meeting": ("주주총회", "주주총회 소집·결과, 의결권 대리행사 권유, 주주명부 폐쇄·기준일 설정"),
    "dividend": ("배당", "현금·현물 배당 결정, 배당락"),
    "inquiry": ("조회공시·해명", "거래소의 조회공시 요구와 답변, 풍문·보도에 대한 해명"),
    "unfaithful": ("불성실공시", "불성실공시법인 지정·지정예고"),
    "litigation": ("소송", "소송·가처분의 제기·신청, 판결·결정"),
    "trading_halt": ("거래정지", "주권 매매거래 정지, 정지기간 변경, 정지 해제"),
    "delisting_watch": (
        "상장폐지·관리종목",
        "상장폐지 사유·우려, 관리종목 지정(우려), 상장적격성 실질심사, 기업심사위원회, 개선계획, 정리매매",
    ),
    "insolvency": (
        "회생·파산·부도",
        "회생절차, 파산 신청, 부도, 해산 사유, 영업정지, 횡령·배임 혐의, 채권은행 관리절차",
    ),
    "securities_filing": ("증권 발행 서류", "증권신고서·투자설명서·증권발행실적보고서·일괄신고추가서류·효력발생안내"),
    "other": ("기타", "위 어디에도 속하지 않는 공시(기업설명회, 채무보증, 국책과제 선정, 임상시험, 대표이사 변경 등)"),
}
OTHER = "other"
# 위험 Noul이 이 값 이상이면 '매매 불가 위험'으로 표시한다(evals/jev_disclosures로 다시 잰다).
RISK_MIN = 0.5

# 규칙 표: (서식명 조각, 유형, 위험). 공백을 뺀 제목에 조각이 들어 있으면 맞고, 위에서부터 첫 줄이 이긴다.
# 유형·위험이 None이면 규칙이 정하지 못한 것이고 Jev에 묻는다. 해제·기각처럼 위험이 풀린 서식은 원래
# 사건 줄보다 위에 둔다.
RULES: tuple[tuple[str, str | None, bool | None], ...] = (
    ("정리매매", "delisting_watch", True),  # 정지 해제라도 정리매매는 상장폐지 절차다
    ("기타시장안내(관리종목지정우려", "delisting_watch", True),
    # 자유 서식: 부제에만 뜻이 있다
    ("기타시장안내", None, None),
    ("투자판단관련주요경영사항", None, None),
    ("기타경영사항", None, None),
    ("기타주요경영사항", None, None),
    ("수시공시의무관련사항", None, None),
    # 매매 불가 위험
    ("정지해제", "trading_halt", False),  # 주권매매거래정지해제, 매매거래정지및정지해제(당일 해제)
    ("거래정지", "trading_halt", True),
    ("조회공시", "inquiry", None),  # 파산신청설 같은 부제가 위험을 가른다
    ("풍문또는보도", "inquiry", None),
    ("소송등의", "litigation", None),  # 상장폐지 효력정지 가처분 같은 부제가 위험을 가른다
    ("불성실공시법인지정예고", "unfaithful", False),
    ("불성실공시법인지정", "unfaithful", True),  # 지정되면 매매거래가 하루 정지된다
    ("투자유의안내", "delisting_watch", True),
    ("관리종목", "delisting_watch", True),
    ("상장적격성", "delisting_watch", True),
    ("상장폐지", "delisting_watch", True),
    ("파산신청기각", "insolvency", False),
    ("관리절차해제", "insolvency", False),
    ("회생절차종결", "insolvency", False),
    ("회생절차", "insolvency", True),
    ("파산", "insolvency", True),
    ("부도", "insolvency", True),
    ("해산사유", "insolvency", True),
    ("영업정지", "insolvency", True),
    ("횡령ㆍ배임", "insolvency", True),
    ("관리절차", "insolvency", True),
    # 뒤쪽 조각('배당'·'신탁계약')에 먼저 걸리면 안 되는 서식
    ("기업가치제고", OTHER, False),
    ("기업인수목적회사", OTHER, False),  # SPAC 신탁계약은 자기주식 신탁이 아니다
    # 정해진 서식(위험 없음). 발행 결과 서류는 부제에 '유상증자'가 있어도 발행 서류이고, '무상증자'가
    # 들어간 유무상증자는 먼저 둔다. '소액공모'는 유상증자 발행가액 부제에도 나오므로 유상증자 뒤에 둔다.
    ("증권발행실적", "securities_filing", False),
    ("증권발행결과", "securities_filing", False),
    ("유상증자또는주식관련사채등의", "securities_filing", False),
    ("유무상증자", "rights_offering", False),
    ("무상증자", "capital_change", False),
    ("유상증자", "rights_offering", False),
    ("권리락", "rights_offering", False),
    ("소액공모", "securities_filing", False),
    ("전환사채", "equity_linked", False),
    ("신주인수권", "equity_linked", False),
    ("교환사채", "equity_linked", False),
    ("전환가액", "equity_linked", False),
    ("전환청구권", "equity_linked", False),
    ("조건부자본증권", "equity_linked", False),
    ("자본으로인정되는채무증권", "equity_linked", False),
    ("자기주식", "treasury_stock", False),
    ("주식소각", "treasury_stock", False),
    ("신탁계약", "treasury_stock", False),
    ("감자", "capital_change", False),
    ("주식병합", "capital_change", False),
    ("주식분할", "capital_change", False),
    ("단일판매ㆍ공급계약", "supply_contract", False),
    ("최대주주변경", "control_change", False),
    ("경영권변경", "control_change", False),
    ("공개매수", "control_change", False),
    ("특수관계인", OTHER, False),
    ("동일인등출자계열회사", OTHER, False),
    ("합병", "m_and_a", False),
    ("회사분할", "m_and_a", False),
    ("영업양수", "m_and_a", False),
    ("영업양도", "m_and_a", False),
    ("타법인주식", "m_and_a", False),
    ("유형자산양", "m_and_a", False),
    ("유형자산취득", "m_and_a", False),
    ("신규시설투자", "m_and_a", False),
    ("손익구조", "earnings", False),
    ("(잠정)실적", "earnings", False),
    ("결산실적", "earnings", False),
    ("사업보고서", "periodic_report", False),
    ("반기보고서", "periodic_report", False),
    ("분기보고서", "periodic_report", False),
    ("감사보고서", "periodic_report", False),
    ("임원ㆍ주요주주", "ownership", False),
    ("대량보유", "ownership", False),
    ("소유주식변동", "ownership", False),
    ("주주총회", "shareholder_meeting", False),
    ("의결권대리행사", "shareholder_meeting", False),
    ("주주명부", "shareholder_meeting", False),
    ("배당", "dividend", False),
    ("증권신고서", "securities_filing", False),
    ("투자설명서", "securities_filing", False),
    ("일괄신고", "securities_filing", False),
    ("효력발생안내", "securities_filing", False),
    ("정정신고서제출요구", "securities_filing", False),
    *(
        (fragment, OTHER, False)
        for fragment in (
            "기업설명회",
            "채무보증",
            "담보제공",
            "금전대여",
            "자금대여",
            "대표이사",
            "독립이사",
            "유동성공급계약",
            "주식매수선택권",
            "본점소재지",
            "자금차입",
            "단기차입금",
            "벌금등의부과",
            "특허권",
            "기업지배구조",
            "지속가능경영",
            "거래처와의거래중단",
            "생산재개",
            "자산재평가",
            "약관에의한금융거래",
            "해외증권거래소",
            "중대재해",
        )
    ),
)

# Jev가 없을 때(꺼짐·예산 초과·장애, 규칙만 평가) 자유 서식의 위험을 가르는 낱말.
# 기업심사위원회·시장위원회·상장공시위원회·개선계획은 거래소의 상장폐지 심사 절차다(evals/jev_disclosures v2).
RISK_WORDS = (
    "거래정지",
    "상장폐지",
    "정리매매",
    "관리종목",
    "상장적격성",
    "실질심사",
    "회생",
    "파산",
    "부도",
    "기업심사위원회",
    "시장위원회",
    "상장공시위원회",
    "상장·공시위원회",
    "개선계획",
)
RELEASE_WORDS = ("해제", "취소", "철회", "기각", "취하", "종결", "중단")
# 자회사·종속회사의 사건은 상장회사 주식의 매매 위험이 아니다.
SUBSIDIARY_WORDS = ("자회사의주요경영사항", "종속회사의주요경영사항")

MARKETS = {"Y": "유가증권시장", "K": "코스닥", "N": "코넥스", "E": "기타 법인"}
# rm(비고)의 한 글자 코드. Jev에게는 뜻으로 풀어 보낸다.
REMARKS = {
    "유": "유가증권시장본부 소관",
    "코": "코스닥시장본부 소관",
    "넥": "코넥스시장 소관",
    "채": "채권상장법인 공시",
    "공": "공정거래위원회 신고",
    "연": "연결재무제표 포함",
    "정": "이후 정정 공시가 있음",
    "철": "철회된 공시",
}
_PREFIX = re.compile(r"^\[([^\]]*)\]")


@dataclass(frozen=True)
class Judgment:
    """공시 한 건의 판정. 확률은 Jev가 정한 항목에만 있고 규칙이 정한 항목은 None이다."""

    kind: str
    corrected: bool
    risk: bool
    judged_by: str  # rules | jev
    kind_prob: float | None = None
    risk_prob: float | None = None
    input_tokens: int = 0


def normalize(report_nm: str) -> str:
    """연속 공백을 한 칸으로 줄인다(DART 제목은 부제 앞에 공백이 여러 칸 들어 있다).

    @param report_nm DART list.json의 report_nm
    @returns 정리된 제목
    """
    return " ".join(str(report_nm).split())


def split(report_nm: str) -> tuple[bool, str]:
    """[기재정정]·[첨부정정] 같은 머리말을 떼어 정정 여부와 본문 제목으로 나눈다.

    @param report_nm DART 제목
    @returns (정정 여부, 머리말을 뗀 정리된 제목)
    """
    text = normalize(report_nm)
    match = _PREFIX.match(text)
    if not match:
        return False, text
    return "정정" in match.group(1), text[match.end() :].strip()


def by_rules(report_nm: str) -> tuple[str | None, bool | None]:
    """규칙 표로 유형과 위험을 정한다. 정하지 못한 항목은 None이다.

    @param report_nm DART 제목(머리말이 있어도 된다)
    @returns (유형 또는 None, 위험 또는 None)
    """
    key = "".join(split(report_nm)[1].split())
    for fragment, kind, risk in RULES:
        if fragment in key:
            return kind, False if risk and _subsidiary(key) else risk
    return None, None


def _subsidiary(key: str) -> bool:
    return any(word in key for word in SUBSIDIARY_WORDS)


def _keyword_risk(text: str) -> bool:
    key = "".join(text.split())
    return (
        any(word in key for word in RISK_WORDS)
        and not any(word in key for word in RELEASE_WORDS)
        and not _subsidiary(key)
    )


def questions() -> dict:
    """한 공시에 보낼 질문 두 개(유형 Choice, 위험 Noul).

    @returns 질문 id → typesafe_sdk 질문 객체
    """
    from typesafe_sdk import Choice, Noul, NoulCriteria

    return {
        "kind": Choice(
            instructions=(
                "`report_nm`은 한국 전자공시시스템(DART)에 올라온 상장회사 공시의 제목이다. 괄호 안 부제가 실제 "
                "내용을 말한다. 이 공시는 어느 유형인가? 해제·취소·철회·기각 공시도 원래 사건과 같은 유형으로 본다."
            ),
            criteria={key: f"{label}: {text}" for key, (label, text) in KINDS.items()},
        ),
        "risk": Noul(
            instructions=(
                "`report_nm` 공시는 이 회사 주식을 사고팔 수 없게 되었거나 그럴 위험(매매거래정지, "
                "상장폐지·정리매매, 관리종목 지정, 거래소의 상장폐지 심사, 회생·파산·부도)이 생기거나 "
                "이어진다는 뜻인가? 거래소의 상장폐지 심사는 상장적격성 실질심사, "
                "기업심사위원회·시장위원회·상장공시위원회 심의, 개선계획서 제출·이행, 개선기간으로 "
                "이어지는 절차이며, 이 절차의 어느 단계를 알리는 공시든 위험이 이어진다는 뜻이다."
            ),
            criteria=NoulCriteria(
                true=(
                    "거래정지·상장폐지·관리종목·회생·파산·부도가 새로 생겼거나 우려되거나, "
                    "상장폐지 심사 절차(실질심사, 기업심사위원회·시장위원회 심의, 개선계획)가 진행 중이라는 내용"
                ),
                false=(
                    "그런 위험과 관계없는 경영 소식이거나, 정지 해제·채권자 파산신청 기각·취하·심사 중단처럼 "
                    "위험이 풀렸다는 내용. 자회사·종속회사의 일은 이 회사 주식의 위험이 아니다"
                ),
            ),
        ),
    }


def _top(answer) -> tuple[str, float]:
    # SDK의 choice 값이 최고 확률 항목과 어긋난 보고가 있어(sdk-python#15) 분포에서 직접 고른다.
    key = max(answer.probabilities, key=answer.probabilities.get)
    return key, float(answer.probabilities[key])


def decide(
    report_nm: str, rules: tuple[str | None, bool | None], answers: dict | None, input_tokens: int = 0
) -> Judgment:
    """규칙 결과에 Jev 답을 채워 판정을 만든다. API를 부르지 않는 순수 함수다.

    외부 API의 답은 신뢰 경계 밖이다. 유형은 KINDS에 있는 값만 쓰고, 나머지는 기타로 둔다.
    위험은 Jev 확률이 RISK_MIN 이상이거나 낱말(RISK_WORDS)이 가리키면 참이다.
    answers가 None이면(Jev 꺼짐·예산 초과·장애) 규칙만으로 정한다: 유형은 기타, 위험은 낱말로 가른다.

    @param report_nm DART 제목
    @param rules by_rules의 결과
    @param answers system_one 응답의 answers 또는 None
    @param input_tokens 과금 기록용 입력 토큰 수
    @returns Judgment
    """
    corrected, text = split(report_nm)
    kind, risk = rules
    kind_prob = risk_prob = None
    if answers is not None and kind is None:
        kind, kind_prob = _top(answers["kind"])
        if kind not in KINDS:
            kind = OTHER
    if answers is not None and risk is None:
        risk_prob = float(answers["risk"].noul)
        # Jev와 낱말 중 하나라도 위험이면 위험이다. 평가에서 둘이 서로 다른 것을 놓쳤고, 합쳐도 정밀도가
        # 떨어지지 않았다(evals/jev_disclosures/README.md). 확률은 Jev 값을 그대로 보여 준다.
        risk = risk_prob >= RISK_MIN or _keyword_risk(text)
    used_jev = kind_prob is not None or risk_prob is not None
    return Judgment(
        kind=kind or OTHER,
        corrected=corrected,
        risk=_keyword_risk(text) if risk is None else risk,
        judged_by="jev" if used_jev else "rules",
        kind_prob=None if kind_prob is None else round(kind_prob, 3),
        risk_prob=None if risk_prob is None else round(risk_prob, 3),
        input_tokens=input_tokens if used_jev else 0,
    )


def state(report_nm: str, rm: str, corp_cls: str) -> dict:
    """Jev에 보내는 state. 회사명·종목코드는 넣지 않는다.

    @param report_nm DART 제목
    @param rm 비고 코드(유·코·정 등)
    @param corp_cls 법인구분(Y·K·N·E)
    @returns {"report_nm", "rm", "market"}
    """
    remarks = [REMARKS[ch] for ch in str(rm or "") if ch in REMARKS]
    return {
        "report_nm": normalize(report_nm),
        "rm": ", ".join(remarks) or "없음",
        "market": MARKETS.get(corp_cls, "기타 법인"),
    }


def judge(report_nm: str, rm: str, corp_cls: str, client=None) -> Judgment:
    """공시 한 건을 판정한다. 규칙이 다 정하면 Jev를 부르지 않는다.

    @param report_nm DART 제목
    @param rm 비고 코드
    @param corp_cls 법인구분
    @param client typesafe_sdk.TypeSafeClient 또는 같은 system_one을 가진 대역. None이면 규칙만 쓴다.
        호출 예외는 그대로 올린다(호출하는 쪽이 규칙만으로 다시 판정한다).
    @returns Judgment
    """
    rules = by_rules(report_nm)
    if client is None or None not in rules:
        return decide(report_nm, rules, None)
    response = client.system_one(state(report_nm, rm, corp_cls), questions(), model=MODEL)
    return decide(report_nm, rules, response.answers, int(response.usage.input_tokens or 0))
