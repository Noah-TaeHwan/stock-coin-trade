"""관심 종목 공시 모아 보기: symbols로 여러 종목의 최근 30일 공시를 실제 MariaDB에서 읽는다."""

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text

import bootstrap
import dart_radar
import db

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def tables():
    bootstrap.create_tables()


def _insert(conn, rcept_no, stock_code, day):
    conn.execute(
        text(
            "INSERT INTO dart_disclosures (rcept_no, rcept_dt, corp_code, corp_name, stock_code, corp_cls, report_nm, "
            "first_seen_at, kind, judged_by, judged_at) VALUES (:no, :day, '00000001', '테스트', :code, 'Y', "
            "'주요사항보고서', :now, 'other', 'rules', :now)"
        ),
        {"no": rcept_no, "day": day, "code": stock_code, "now": datetime(2026, 9, 26, 0, 0)},
    )


def test_symbols_returns_only_the_watched_codes():
    today = datetime.now(dart_radar.KST).date()
    prefix = uuid.uuid4().int % 10**8
    rows = [(f"{prefix:08d}{n:06d}", code) for n, code in enumerate(("900001", "900002", "900003"))]
    with db.engine.begin() as conn:
        for no, code in rows:
            _insert(conn, no, code, today)
    try:
        found = dart_radar.query(today - timedelta(days=29), today, ("900001", "900003"), None, None, 50)
        assert sorted(row["stock_code"] for row in found if row["rcept_no"].startswith(f"{prefix:08d}")) == [
            "900001",
            "900003",
        ]
    finally:
        with db.engine.begin() as conn:
            for no, _ in rows:
                conn.execute(text("DELETE FROM dart_disclosures WHERE rcept_no = :no"), {"no": no})


def test_a_single_symbol_still_works():
    assert dart_radar.query(date(2000, 1, 1), date(2000, 1, 1), ("900001",), None, None, 5) == []
