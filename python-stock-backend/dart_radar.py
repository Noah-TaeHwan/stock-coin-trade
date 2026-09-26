"""DART 공시 레이더: OpenDART 공시 목록을 모아 판정해 저장하고(worker), 저장된 것을 보여 준다(API).

- 수집: 오늘(KST) 목록을 1쪽부터 읽다가 이미 저장된 접수번호를 만난 쪽까지만 읽는다(5분마다).
  목록 순서가 접수번호 순으로 딱 맞지는 않아(2026-09-23 실측) 그 쪽은 끝까지 보고, 매시 30분에는
  하루 전체를 다시 훑어 놓친 것을 채운다. 상장사(유가·코스닥·코넥스)만 저장한다.
- 날짜는 rcept_dt만 쓴다. 접수번호 앞 8자리는 접수일과 다를 수 있다(9/23 683건 중 56건). 시각은
  DART가 주지 않으므로 우리가 처음 본 시각(first_seen_at, UTC)을 적는다.
- 판정: src/deskjev/disclosures. 규칙이 못 정한 것만 Jev에 묻고, Jev가 꺼져 있거나 예산을 넘었거나
  실패하면 규칙만으로 정해 judged_by='rules'로 남긴다(나중에 다시 판정할 수 있다).
- API 키(DART_API_KEY)는 URL 쿼리로 가므로 요청 예외 문구를 그대로 남기지 않는다.

교육용 분류이며 투자 권유가 아니다.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta, timezone

import requests
from flask import Blueprint, jsonify, request
from sqlalchemy import bindparam, text

import price_sources
from extensions import limiter

log = logging.getLogger(__name__)

dart_bp = Blueprint("dart_radar", __name__, url_prefix="/api/disclosures")

KST = timezone(timedelta(hours=9))
LIST_URL = "https://opendart.fss.or.kr/api/list.json"
PAGE_COUNT = 100
LISTED = frozenset("YKN")  # E(기타 법인)는 저장하지 않는다
# OpenDART 약관 제23조①(정확성 비보장)에 따라 고지한다.
NOTICE = ("교육용 분류이며 투자 권유가 아닙니다. 확률은 모델 판단 확률입니다. "
          "DART 자료의 정확성·완전성은 보장되지 않으니 원문을 확인하세요.")
DETAIL_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
MAX_LIMIT = 500
SYMBOL_DAYS = 30  # 날짜 없이 종목만 주면 최근 30일(주말·휴일에도 비지 않게)
MAX_SYMBOLS = 20  # 관심 종목 모아 보기(symbols)는 한 번에 20종목까지

TABLE = """CREATE TABLE IF NOT EXISTS dart_disclosures (
  rcept_no CHAR(14) PRIMARY KEY,
  rcept_dt DATE NOT NULL,
  corp_code CHAR(8) NOT NULL,
  corp_name VARCHAR(100) NOT NULL,
  stock_code VARCHAR(6) NOT NULL DEFAULT '',
  corp_cls CHAR(1) NOT NULL,
  report_nm VARCHAR(300) NOT NULL,
  rm VARCHAR(20) NOT NULL DEFAULT '',
  flr_nm VARCHAR(100) NOT NULL DEFAULT '',
  first_seen_at DATETIME NOT NULL COMMENT 'UTC',
  kind VARCHAR(30) NOT NULL,
  corrected BOOLEAN NOT NULL DEFAULT FALSE,
  risk BOOLEAN NOT NULL DEFAULT FALSE,
  kind_prob DECIMAL(4, 3) NULL,
  risk_prob DECIMAL(4, 3) NULL,
  judged_by VARCHAR(10) NOT NULL,
  model VARCHAR(40) NULL,
  judged_at DATETIME NOT NULL COMMENT 'UTC',
  KEY idx_dart_day (rcept_dt, first_seen_at),
  KEY idx_dart_stock (stock_code, rcept_dt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""

COLUMNS = (
    "rcept_no",
    "rcept_dt",
    "corp_code",
    "corp_name",
    "stock_code",
    "corp_cls",
    "report_nm",
    "rm",
    "flr_nm",
    "first_seen_at",
    "kind",
    "corrected",
    "risk",
    "kind_prob",
    "risk_prob",
    "judged_by",
    "model",
    "judged_at",
)


class DartError(RuntimeError):
    """DART 호출 실패. 문구에 요청 URL(키 포함)을 넣지 않는다."""


def ensure_dart_tables() -> None:
    """공시 레이더 테이블을 만든다(멱등)."""
    from db import engine

    with engine.begin() as conn:
        conn.execute(text(TABLE))


def known_numbers(numbers: Iterable[str]) -> set[str]:
    """이미 저장된 접수번호.

    @param numbers 확인할 접수번호들
    @returns 그중 테이블에 있는 것
    """
    from db import engine

    numbers = list(numbers)
    if not numbers:
        return set()
    query = text("SELECT rcept_no FROM dart_disclosures WHERE rcept_no IN :nos").bindparams(
        bindparam("nos", expanding=True)
    )
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(query, {"nos": numbers})}


def save(rows: list[dict]) -> int:
    """판정된 공시를 넣는다. 이미 있는 접수번호는 건드리지 않는다(INSERT IGNORE).

    @param rows COLUMNS 키를 가진 dict 목록
    @returns 넣으려 한 행 수
    """
    from db import engine

    if not rows:
        return 0
    statement = text(
        f"INSERT IGNORE INTO dart_disclosures ({', '.join(COLUMNS)}) VALUES ({', '.join(':' + c for c in COLUMNS)})"
    )
    with engine.begin() as conn:
        conn.execute(statement, rows)
    return len(rows)


def fetch_new(
    get: Callable, key: str, day: date, known: Callable[[list[str]], set[str]], full: bool = False
) -> tuple[list[dict], int]:
    """오늘 목록에서 아직 저장하지 않은 상장사 공시를 읽는다.

    @param get requests.get과 같은 모양의 함수(테스트는 가짜를 넣는다)
    @param key OpenDART 인증키
    @param day 접수일
    @param known 접수번호 목록 → 이미 저장된 것의 집합
    @param full True면 저장된 번호를 만나도 끝 쪽까지 읽는다(하루 전체 다시 훑기)
    @returns (새 공시 목록, DART 호출 수)
    @raises DartError status가 000·013이 아니거나(020 한도 초과 등) 요청이 실패했을 때
    """
    found: dict[str, dict] = {}
    calls, page = 0, 1
    while True:
        params = {
            "crtfc_key": key,
            "bgn_de": day.strftime("%Y%m%d"),
            "end_de": day.strftime("%Y%m%d"),
            "page_no": page,
            "page_count": PAGE_COUNT,
        }
        calls += 1
        try:
            response = get(LIST_URL, params=params, timeout=15)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            # 예외 문구에는 키가 든 URL이 있을 수 있다. 종류만 남긴다.
            raise DartError(f"DART list request failed: {type(exc).__name__}") from None
        status = body.get("status")
        if status == "013":  # 조회된 데이터 없음(휴일·이른 아침)
            break
        if status != "000":
            raise DartError(f"DART status {status}: {body.get('message', '')}")
        rows = body.get("list") or []
        seen = known([row["rcept_no"] for row in rows])
        for row in rows:
            if row["rcept_no"] not in seen and row.get("corp_cls") in LISTED:
                found.setdefault(row["rcept_no"], row)  # 쪽을 넘기는 사이 목록이 밀려 같은 건이 두 번 올 수 있다
        if (seen and not full) or page >= int(body.get("total_page") or 1):
            break
        page += 1
    return list(found.values()), calls


def _judge_rows(items: list[dict], use_jev: bool, budget_usd: float) -> tuple[list[dict], int]:
    """새 공시를 판정해 저장할 행으로 바꾼다. Jev 호출 수를 함께 돌려준다."""
    import jev_usage
    from deskjev import MODEL, disclosures

    client = jev_usage.client(timeout=10.0, max_retries=2) if use_jev else None
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    rows, billed = [], 0
    for item in items:
        judgment = None
        if client is not None and None in disclosures.by_rules(item["report_nm"]):
            try:
                # ponytail: 확인 후 기록이라 예산을 호출 몇 건(건당 약 $0.0001)만큼 넘을 수 있다(intent.py와 같음).
                if jev_usage.over_budget(budget_usd):
                    client = None
                else:
                    judgment = disclosures.judge(item["report_nm"], item.get("rm", ""), item["corp_cls"], client)
                    jev_usage.record(judgment.input_tokens)
                    billed += 1
            except Exception as exc:  # Jev 장애는 수집을 막지 않는다. 이번 회차의 나머지는 규칙만 쓴다.
                log.warning("dart radar: Jev unavailable, rules only (%s)", type(exc).__name__)
                client = None
        judgment = judgment or disclosures.judge(item["report_nm"], item.get("rm", ""), item["corp_cls"])
        rows.append(
            {
                "rcept_no": item["rcept_no"],
                "rcept_dt": datetime.strptime(item["rcept_dt"], "%Y%m%d").date(),
                "corp_code": item.get("corp_code", ""),
                "corp_name": item.get("corp_name", ""),
                "stock_code": (item.get("stock_code") or "").strip(),
                "corp_cls": item["corp_cls"],
                "report_nm": disclosures.normalize(item["report_nm"])[:300],
                "rm": item.get("rm") or "",
                "flr_nm": item.get("flr_nm") or "",
                "first_seen_at": now,
                "kind": judgment.kind,
                "corrected": judgment.corrected,
                "risk": judgment.risk,
                "kind_prob": judgment.kind_prob,
                "risk_prob": judgment.risk_prob,
                "judged_by": judgment.judged_by,
                "model": MODEL if judgment.judged_by == "jev" else None,
                "judged_at": now,
            }
        )
    return rows, billed


def collect(
    full: bool = False,
    *,
    get: Callable = requests.get,
    known: Callable[[list[str]], set[str]] = known_numbers,
    store: Callable[[list[dict]], int] = save,
    day: date | None = None,
    days_ago: int = 0,
) -> dict:
    """스케줄 작업: 오늘 새 공시를 읽어 판정하고 저장한다.

    @param full True면 하루 전체를 다시 훑는다
    @param get/known/store 테스트·시험 실행용 대역(기본은 requests와 MariaDB)
    @param day 접수일(기본 오늘 KST)
    @param days_ago day가 없을 때 오늘에서 뺄 날 수(00:10 전날 훑기는 1)
    @returns {"day", "new", "calls", "jev_calls"} 요약
    """
    from settings import Settings

    settings = Settings.from_env()
    if not settings.dart_api_key:
        log.warning("dart radar: DART_API_KEY is not set; skipping")
        return {"day": None, "new": 0, "calls": 0, "jev_calls": 0}
    day = day or datetime.now(KST).date() - timedelta(days=days_ago)
    items, calls = fetch_new(get, settings.dart_api_key, day, known, full=full)
    rows, billed = _judge_rows(items, settings.jev_enabled, settings.jev_monthly_budget_usd)
    store(rows)
    summary = {"day": day.isoformat(), "new": len(rows), "calls": calls, "jev_calls": billed}
    log.info("dart radar: %s", summary)
    return summary


# ── API ──────────────────────────────────────────────────────────────────────


def query(
    start: date, end: date, symbols: tuple[str, ...] | None, kind: str | None, risk: bool | None, limit: int
) -> list[dict]:
    """저장된 공시를 읽는다(최근 접수일, 최근에 본 것부터).

    @param start/end 접수일 범위(양 끝 포함)
    @param symbols 종목코드들(없으면 전체)
    @returns 행 dict 목록
    """
    from db import engine

    where, params = ["rcept_dt BETWEEN :start AND :end"], {"start": start, "end": end, "limit": limit}
    if symbols:
        where.append("stock_code IN :symbols")
        params["symbols"] = list(symbols)
    if kind:
        where.append("kind = :kind")
        params["kind"] = kind
    if risk is not None:
        where.append("risk = :risk")
        params["risk"] = risk
    statement = text(
        f"SELECT {', '.join(COLUMNS)} FROM dart_disclosures WHERE {' AND '.join(where)} "
        "ORDER BY rcept_dt DESC, first_seen_at DESC, rcept_no DESC LIMIT :limit"
    )
    if symbols:
        statement = statement.bindparams(bindparam("symbols", expanding=True))
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(statement, params)]


def _prob(value) -> float | None:
    return None if value is None else float(value)


def _item(row: dict) -> dict:
    from deskjev.disclosures import KINDS, MARKETS

    seen = row["first_seen_at"].replace(tzinfo=UTC).astimezone(KST)
    # 지난 날짜를 나중에 수집하면 처음 본 날이 접수일과 다르다. 그때는 날짜도 보인다.
    seen_text = seen.strftime("%H:%M" if seen.date() == row["rcept_dt"] else "%m/%d %H:%M")
    return {
        "rceptNo": row["rcept_no"],
        "date": row["rcept_dt"].isoformat(),
        "corpName": row["corp_name"],
        "stockCode": row["stock_code"],
        "market": MARKETS.get(row["corp_cls"], row["corp_cls"]),
        "reportName": row["report_nm"],
        "remark": row["rm"],
        "filer": row["flr_nm"],
        "kind": row["kind"],
        "kindLabel": KINDS.get(row["kind"], KINDS["other"])[0],
        "corrected": bool(row["corrected"]),
        "risk": bool(row["risk"]),
        "kindProb": _prob(row["kind_prob"]),
        "riskProb": _prob(row["risk_prob"]),
        "judgedBy": row["judged_by"],
        "firstSeenAt": seen.isoformat(),
        "firstSeenKst": seen_text,
        "url": DETAIL_URL.format(row["rcept_no"]),
    }


@dart_bp.get("")
@limiter.limit("60 per minute")
def list_disclosures():
    """GET /api/disclosures?date=YYYY-MM-DD&symbol=6자리&symbols=6자리,…&kind=&risk=1&limit= — 저장된 공시.

    date가 있으면 그날, 없으면 오늘(KST). date 없이 종목(symbol 하나 또는 symbols 여러 개, 관심 종목 모아 보기)만
    있으면 그 종목들의 최근 SYMBOL_DAYS일. 관심 종목은 서버에 저장하지 않는다.
    """
    from deskjev.disclosures import KINDS

    args = request.args
    raw_day = args.get("date", "").strip()
    try:
        # 3.11의 fromisoformat은 20260923도 받으므로 모양을 먼저 확인한다.
        if raw_day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_day):
            raise ValueError(raw_day)
        day = date.fromisoformat(raw_day) if raw_day else None
    except ValueError:
        return jsonify({"message": "date는 YYYY-MM-DD 형식이어야 합니다."}), 400
    symbol = args.get("symbol", "").strip() or None
    if symbol and not re.fullmatch(r"\d{6}", symbol):
        return jsonify({"message": "symbol은 6자리 종목코드여야 합니다."}), 400
    raw_symbols = args.get("symbols", "").strip()
    if symbol and raw_symbols:
        return jsonify({"message": "symbol과 symbols는 함께 쓸 수 없습니다."}), 400
    symbols = tuple(dict.fromkeys(code.strip() for code in raw_symbols.split(",") if code.strip()))
    if symbol:
        symbols = (symbol,)
    if len(symbols) > MAX_SYMBOLS or any(not re.fullmatch(r"\d{6}", code) for code in symbols):
        return jsonify({"message": f"symbols는 6자리 종목코드 {MAX_SYMBOLS}개 이하여야 합니다."}), 400
    kind = args.get("kind", "").strip() or None
    if kind and kind not in KINDS:
        return jsonify({"message": "알 수 없는 kind입니다."}), 400
    raw_risk = args.get("risk", "").strip()
    if raw_risk not in ("", "0", "1"):
        return jsonify({"message": "risk는 0 또는 1이어야 합니다."}), 400
    try:
        limit = int(args.get("limit") or 200)
    except ValueError:
        return jsonify({"message": "limit은 정수여야 합니다."}), 400
    if not 1 <= limit <= MAX_LIMIT:
        return jsonify({"message": f"limit은 1~{MAX_LIMIT} 사이여야 합니다."}), 400

    end = day or datetime.now(KST).date()
    start = end - timedelta(days=SYMBOL_DAYS - 1) if symbols and not day else end
    rows = query(start, end, symbols or None, kind, None if raw_risk == "" else raw_risk == "1", limit)
    return jsonify(
        {
            "date": end.isoformat() if start == end else None,  # 종목 30일 모드는 None
            "from": start.isoformat(),
            "to": end.isoformat(),
            "items": [_item(row) for row in rows],
            "kinds": {key: label for key, (label, _) in KINDS.items()},
            "notice": NOTICE,
            **price_sources.label("dart"),
        }
    )
