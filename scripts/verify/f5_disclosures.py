"""F5 공시 주행: 출처·정확성 고지, 관심 종목(symbols) 모아 보기, 입력 거절.

검증 스택은 DART를 수집하지 않으므로 `[검증용 예시]` 행 3개(관심 2종목 + 대조 1종목)를 넣고, 끝나면 지운다.
사용법: python3 scripts/verify/f5_disclosures.py (먼저 scripts/verify/stack.sh up·doctor)
"""

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

KST = timezone(timedelta(hours=9))
WATCHED = ("005930", "000660")
CONTROL = "035720"
MARK = "[검증용 예시]"
# 실제 접수번호(연도로 시작)와 겹치지 않는 9999로 시작하는 번호만 쓴다.
ROWS = [("99990000000001", WATCHED[0]), ("99990000000002", WATCHED[1]), ("99990000000003", CONTROL)]


def _seed() -> None:
    """예시 행을 넣는다. 값은 모두 이 파일의 상수라 SQL에 직접 넣어도 외부 입력이 없다."""
    today = datetime.now(KST).date().isoformat()
    values = ", ".join(
        f"('{no}', '{today}', '0000000{i}', '검증예시{i}', '{code}', 'Y', '{MARK} 단일판매·공급계약체결', '', '검증', "
        f"UTC_TIMESTAMP(), 'supply_contract', FALSE, FALSE, NULL, NULL, 'rule', NULL, UTC_TIMESTAMP())"
        for i, (no, code) in enumerate(ROWS, 1)
    )
    common.mariadb_scalar(
        "INSERT INTO dart_disclosures (rcept_no, rcept_dt, corp_code, corp_name, stock_code, corp_cls, report_nm, rm, "
        "flr_nm, first_seen_at, kind, corrected, risk, kind_prob, risk_prob, judged_by, model, judged_at) VALUES "
        + values
    )


def _cleanup() -> str:
    """예시 행을 지우고 남은 개수를 돌려준다(0이어야 한다)."""
    common.mariadb_scalar(f"DELETE FROM dart_disclosures WHERE report_nm LIKE '{MARK}%'")
    return common.mariadb_scalar(f"SELECT COUNT(*) FROM dart_disclosures WHERE report_nm LIKE '{MARK}%'")


def steps(client: common.Client, rec: common.Recorder) -> None:
    """F5 단계를 실행하고 기대값과 다르면 AssertionError를 낸다."""
    try:
        _seed()
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"예시 행을 넣지 못했습니다(dart_disclosures 표 없음?): {exc.stderr.strip()[:200]}") from None
    try:
        status, body = client.call("GET", "/api/disclosures")
        rec.add("f5-list", {}, status, {k: body.get(k) for k in ("attribution", "notice", "date")})
        assert status == 200, f"목록 기대 200, 실제 {status}/{body}"
        assert "DART" in body.get("attribution", ""), f"출처에 DART 없음: {body.get('attribution')!r}"
        assert "정확성" in body.get("notice", ""), f"고지에 '정확성' 없음: {body.get('notice')!r}"

        query = "/api/disclosures?symbols=" + ",".join((*WATCHED, WATCHED[0]))  # 중복 하나 포함
        status, body = client.call("GET", query)
        codes = sorted({item["stockCode"] for item in body.get("items", []) if MARK in item.get("reportName", "")})
        rec.add("f5-watchlist", {"symbols": [*WATCHED, WATCHED[0]]}, status, {"exampleStockCodes": codes})
        assert status == 200 and codes == sorted(WATCHED), f"관심 2종목만 기대, 실제 {status}/{codes}"

        for name, path in (("f5-bad-code", "/api/disclosures?symbols=abc"),
                           ("f5-both-params", "/api/disclosures?symbol=005930&symbols=000660"),
                           ("f5-too-many", "/api/disclosures?symbols=" + ",".join(f"{n:06d}" for n in range(21)))):
            status, body = client.call("GET", path)
            rec.add(name, {"path": path[:60]}, status, body)
            assert status == 400, f"{name} 기대 400, 실제 {status}"
    finally:
        left = _cleanup()
        rec.add("cleanup", {}, 0, {"exampleRowsLeft": left})
    assert left == "0", f"예시 행이 {left}개 남았습니다"


if __name__ == "__main__":
    sys.exit(common.run("F5", steps))
